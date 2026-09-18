"""DART 태그 구조를 보존하는 원문 파서와 부모·자식 청킹."""

import hashlib
import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath
from xml.etree.ElementTree import Element

import tiktoken

VERSION = "dart-blocks-v1-600-80"
ENCODING = tiktoken.get_encoding("cl100k_base")


class _DartTree(HTMLParser):
    # DART 원문에는 XML에서 허용하지 않는 R&D 같은 bare &가 있어 HTML tokenizer 사용.
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Element(tag, {k: v or "" for k, v in attrs})
        node.set("source_line", str(self.getpos()[0]))
        node.set("source_column", str(self.getpos()[1]))
        self.stack[-1].append(node)
        if tag not in {"br", "img", "hr", "meta", "link", "input"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in {"br", "img", "hr", "meta", "link", "input"}:
            return
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            raise ValueError(f"지원하지 않는 태그 중첩: {tag}")
        self.stack.pop()

    def handle_data(self, data):
        node = self.stack[-1]
        if len(node):
            node[-1].tail = (node[-1].tail or "") + data
        else:
            node.text = (node.text or "") + data


def _text(node):
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _table(node):
    rows, spans = [], {}
    header_rows = len(node.findall("./thead/tr"))
    for ri, row in enumerate(node.iter("tr")):
        cells, col = [], 0
        for cell in row:
            if cell.tag not in {"td", "th", "tu", "te"}:
                continue
            while (ri, col) in spans:
                cells.append(spans[(ri, col)]); col += 1
            value = _text(cell)
            rs, cs = int(cell.get("rowspan", "1")), int(cell.get("colspan", "1"))
            if not 1 <= rs <= 1000 or not 1 <= cs <= 200:
                raise ValueError("표 병합 셀 범위 초과")
            for offset in range(cs):
                cells.append(value)
                for future in range(ri + 1, ri + rs):
                    spans[(future, col + offset)] = value
            col += cs
        while (ri, col) in spans:
            cells.append(spans[(ri, col)]); col += 1
        if cells:
            rows.append(" | ".join(cells))
    return rows, min(header_rows or 1, len(rows))


def parse_archive(payload: bytes, receipt_id: str) -> list[dict]:
    """ZIP의 UTF-8 DART XML을 파일·절·문단·표 블록으로 변환한다.

    Args: payload는 원문 ZIP, receipt_id는 출처 ID다.
    Returns: 원문 파일·줄 번호·목차·표 헤더를 보존한 블록 목록.
    Raises: 위험한 경로/크기·미지원 구조·빈 문서는 ValueError. 디스크 추출 없음.
    """
    blocks = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        if len(infos) > 100 or sum(i.file_size for i in infos) > 100_000_000:
            raise ValueError("원문 ZIP 크기/파일 수 한도 초과")
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise ValueError("안전하지 않은 ZIP 경로")
            if not info.filename.lower().endswith(".xml"):
                raise ValueError(f"미지원 원문 형식: {path.suffix}")
            source = archive.read(info).decode("utf-8-sig")
            if "<!ENTITY" in source.upper() or "<!DOCTYPE" in source.upper():
                raise ValueError("외부 선언이 있는 원문은 지원하지 않습니다.")
            parser = _DartTree(); parser.feed(source); parser.close()
            if len(parser.stack) != 1:
                raise ValueError("닫히지 않은 원문 태그")

            def walk(node, headings, parent):
                title = next((c for c in node if c.tag in {"title", "cover-title"}), None)
                if title is not None:
                    headings = headings + [_text(title)]
                    parent = f"{info.filename}:{node.get('source_line', '0')}"
                if node.tag == "table" and any(c.tag == "table" for c in list(node.iter())[1:]):
                    # DART 레이아웃용 외곽 표는 건너뛰고 내부 문단·실제 표를 추출한다.
                    for child in node:
                        walk(child, headings, parent)
                    return
                if node.tag in {"p", "table"}:
                    value = _text(node)
                    if not value:
                        return
                    block = {
                        "block_id": f"{receipt_id}:{info.filename}:{node.get('source_line')}:{node.get('source_column')}",
                        "parent_id": parent, "member": info.filename,
                        "source_line": int(node.get("source_line", "0")),
                        "section": " > ".join(headings),
                        "kind": node.tag, "text": value,
                    }
                    if node.tag == "table":
                        rows, count = _table(node)
                        block.update(rows=rows, header_rows=count, text="\n".join(rows))
                    blocks.append(block)
                    return
                if node.tag in {"title", "cover-title", "script", "style"}:
                    return
                for child in node:
                    walk(child, headings, parent)

            walk(parser.root, [], info.filename)
    if not blocks:
        raise ValueError("검색할 본문·표를 추출하지 못했습니다.")
    return blocks


def make_chunks(blocks: list[dict]) -> list[dict]:
    """블록을 약 600토큰 자식으로 나누고 부모·원문 위치를 연결한다.

    긴 본문은 80토큰 겹침, 표는 행별 분할과 헤더 반복을 적용한다.
    Returns: 검색 텍스트와 원문 위치가 있는 청크. 과대 표 행은 ValueError.
    원문 숫자를 변환하거나 계산하지 않는다.
    """
    chunks = []
    for index, block in enumerate(blocks):
        context = []
        for neighbor in blocks[max(0, index - 2):index]:
            if neighbor["parent_id"] == block["parent_id"]:
                context.append(neighbor["text"][:400])
        prefix = block["section"] + "\n" + "\n".join(context)
        if block["kind"] == "table":
            rows = block["rows"]
            h = block["header_rows"]
            header = "\n".join(rows[:h])
            parts, batch, start = [], [], h
            for ri in range(h, len(rows)):
                row = rows[ri]
                if len(ENCODING.encode(prefix + header + row)) > 7500:
                    raise ValueError("미지원 과대 표 행: 열 분할이 필요합니다.")
                if batch and len(ENCODING.encode(header + "\n" + "\n".join(batch + [row]))) > 600:
                    parts.append((header + "\n" + "\n".join(batch), start + 1, ri))
                    batch, start = [], ri
                batch.append(row)
            parts.append((header + "\n" + "\n".join(batch), start + 1 if batch else 1, len(rows)))
        else:
            # Unicode 문자 경계를 유지하며 목표 크기에서 나눈다.
            text, parts, pos = block["text"], [], 0
            while pos < len(text):
                end = min(pos + 600, len(text))
                while end < len(text) and len(ENCODING.encode(text[pos:end])) < 600:
                    end = min(end + 100, len(text))
                while len(ENCODING.encode(text[pos:end])) > 600:
                    end -= 1
                parts.append((text[pos:end], pos, end))
                if end == len(text): break
                overlap = end
                while overlap > pos and len(ENCODING.encode(text[overlap:end])) < 80:
                    overlap -= 1
                pos = max(pos + 1, overlap)
        for part_index, (text, start, end) in enumerate(parts):
            chunk_id = hashlib.sha256(f"{block['block_id']}:{part_index}:{VERSION}".encode()).hexdigest()[:24]
            chunks.append({
                "chunk_id": chunk_id, "block_id": block["block_id"],
                "parent_id": block["parent_id"], "block_index": index,
                "member": block["member"], "source_line": block["source_line"],
                "section": block["section"], "kind": block["kind"],
                "range": [start, end], "text": text,
                "search_text": prefix + "\n" + text,
            })
    return chunks
