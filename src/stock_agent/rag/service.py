"""로컬 공시 저장소와 BM25·벡터·부모 문맥 결합 검색."""

import datetime as dt
import hashlib
import json
import re
import sqlite3
import threading
from pathlib import Path

import numpy as np
from openai import OpenAI

from stock_agent.rag.parser import VERSION, ENCODING, parse_archive, make_chunks
from stock_agent.vendors.dart_client import download_disclosure_original

MODEL = "text-embedding-3-small"
DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "data" / "disclosures"
_PREPARATION_LOCK = threading.RLock()


def embed_texts(texts: list[str]) -> np.ndarray:
    """공개 공시/검색어를 OpenAI에 배치 전송해 정규화 벡터를 반환한다.

    OPENAI_API_KEY를 사용하며 API 비용이 발생한다. 모델은 MODEL로 고정한다.
    공급자 오류는 그대로 전파하며 다른 모델로 자동 전환하지 않는다.
    """
    client = OpenAI(timeout=30, max_retries=0)
    vectors = []
    for start in range(0, len(texts), 64):
        result = client.embeddings.create(model=MODEL, input=texts[start:start + 64])
        vectors.extend(item.embedding for item in sorted(result.data, key=lambda d: d.index))
    values = np.asarray(vectors, dtype=np.float32)
    if values.ndim != 2 or len(values) != len(texts) or not np.isfinite(values).all():
        raise ValueError("임베딩 응답 모양·값 오류")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms == 0): raise ValueError("빈 임베딩 벡터")
    return values / norms


def _terms(text):
    # ponytail: 외부 형태소 분석기 없이 어절+한글 2글자 부분어 사용. 복합어 품질은 별도 평가.
    words = re.findall(r"[가-힣]+|[a-zA-Z0-9]+", text.lower())
    return words + [w[i:i + 2] for w in words if re.fullmatch(r"[가-힣]{3,}", w)
                    for i in range(len(w) - 1)]


def _database(root):
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "catalog.sqlite")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS reports (
            receipt TEXT PRIMARY KEY, corp TEXT NOT NULL, published TEXT NOT NULL,
            model TEXT NOT NULL, version TEXT NOT NULL, raw_hash TEXT NOT NULL,
            metadata TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY, receipt TEXT NOT NULL, vector_row INTEGER NOT NULL,
            payload TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            id UNINDEXED, receipt UNINDEXED, tokens);
    """)
    return db


def _write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_vectors(index: Path, ids: list[str]) -> np.ndarray | None:
    try:
        stored_ids = json.loads((index / "chunk_ids.json").read_text(encoding="utf-8"))
        vectors = np.load(index / "vectors.npy", allow_pickle=False)
    except (OSError, ValueError, EOFError):
        return None
    if (stored_ids != ids or vectors.ndim != 2 or len(vectors) != len(ids)
            or not len(ids) or not np.isfinite(vectors).all()
            or np.any(np.linalg.norm(vectors, axis=1) == 0)):
        return None
    return vectors


def _read_parsed(parsed: Path) -> tuple[list[dict], list[dict]] | None:
    try:
        blocks = [json.loads(line) for line in (parsed / "blocks.jsonl").read_text(encoding="utf-8").splitlines()]
        chunks = [json.loads(line) for line in (parsed / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    except (OSError, ValueError):
        return None
    if not blocks or not chunks:
        return None
    block_keys = {"block_id", "parent_id", "text"}
    chunk_keys = {"chunk_id", "block_id", "block_index", "parent_id", "search_text", "text"}
    if (any(not isinstance(b, dict) or not block_keys <= b.keys() for b in blocks)
            or any(not isinstance(c, dict) or not chunk_keys <= c.keys() for c in chunks)):
        return None
    if any(not isinstance(c["block_index"], int) or not 0 <= c["block_index"] < len(blocks)
           or blocks[c["block_index"]]["block_id"] != c["block_id"] for c in chunks):
        return None
    return blocks, chunks


def _prepare_report_locked(report: dict, root: Path, embed) -> dict:
    corp, receipt, published = report["corp_code"], report["rcept_no"], report["rcept_dt"]
    if not re.fullmatch(r"\d{8}", corp) or not re.fullmatch(r"\d{14}", receipt):
        raise ValueError("잘못된 공시 식별자")
    dt.datetime.strptime(published, "%Y%m%d")
    if any(term in report["report_nm"] for term in ("정정", "철회")) or any(c in report.get("rm", "") for c in "정철"):
        raise ValueError("정정·철회 관계를 확인하지 못한 공시는 준비하지 않습니다.")
    raw = root / "raw" / corp / receipt
    raw.mkdir(parents=True, exist_ok=True)
    archive = raw / "source.zip"
    if not archive.exists():
        payload = download_disclosure_original(receipt)
        temporary = raw / "source.zip.tmp"
        temporary.write_bytes(payload)
        temporary.replace(archive)
    payload = archive.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    index = root / "indexes" / VERSION / receipt
    parsed = root / "parsed" / receipt / VERSION
    try:
        manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    parsed_values = None
    if (manifest.get("raw_hash") == digest and manifest.get("parser_version") == VERSION
            and manifest.get("corp_code") == corp and manifest.get("rcept_dt") == published):
        parsed_values = _read_parsed(parsed)
    if parsed_values is not None:
        blocks, chunks = parsed_values
        ids = [c["chunk_id"] for c in chunks]
        vectors = _load_vectors(index, ids)
        with _database(root) as db:
            existing = db.execute("SELECT * FROM reports WHERE receipt=?", (receipt,)).fetchone()
            stored = db.execute("SELECT id, vector_row, payload FROM chunks WHERE receipt=? ORDER BY vector_row", (receipt,)).fetchall()
            fts_ids = [r[0] for r in db.execute("SELECT id FROM chunks_fts WHERE receipt=?", (receipt,))]
            if (existing and existing["model"] == MODEL and existing["version"] == VERSION
                    and existing["raw_hash"] == digest and existing["corp"] == corp
                    and existing["published"] == published and vectors is not None
                    and [r["id"] for r in stored] == ids
                    and [r["vector_row"] for r in stored] == list(range(len(ids)))
                    and [json.loads(r["payload"]) for r in stored] == chunks
                    and sorted(fts_ids) == sorted(ids)):
                return {"receipt": receipt, "chunks": len(chunks), "cached": True, "raw_hash": digest}
    else:
        blocks = parse_archive(payload, receipt)
        chunks = make_chunks(blocks)
        parsed.mkdir(parents=True, exist_ok=True)
        for name, values in [("blocks", blocks), ("chunks", chunks)]:
            destination = parsed / f"{name}.jsonl"
            temporary = destination.with_suffix(".jsonl.tmp")
            temporary.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in values), encoding="utf-8")
            temporary.replace(destination)
    if not chunks:
        raise ValueError("검색할 청크가 없습니다.")
    manifest = dict(report, raw_hash=digest, parser_version=VERSION,
                    retrieved_at=manifest.get("retrieved_at", dt.datetime.now(dt.timezone.utc).isoformat()))
    _write_json(raw / "manifest.json", manifest)
    ids = [c["chunk_id"] for c in chunks]
    signature = {"raw_hash": digest, "model": MODEL, "version": VERSION}
    try:
        indexed_signature = json.loads((index / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        indexed_signature = None
    vectors = _load_vectors(index, ids) if indexed_signature == signature else None
    if vectors is None:
        vectors = np.asarray(embed([c["search_text"] for c in chunks]), dtype=np.float32)
        if vectors.ndim != 2 or len(vectors) != len(chunks) or not np.isfinite(vectors).all():
            raise ValueError("청크·벡터 모양 또는 값 불일치")
        if np.any(np.linalg.norm(vectors, axis=1) == 0):
            raise ValueError("빈 임베딩 벡터")
        index.mkdir(parents=True, exist_ok=True)
        with (index / "vectors.tmp").open("wb") as file:
            np.save(file, vectors)
        (index / "vectors.tmp").replace(index / "vectors.npy")
        _write_json(index / "chunk_ids.json", ids)
        _write_json(index / "manifest.json", signature)
    # 이 트랜잭션 완료가 준비 완료 표시. 중간 실패 시 파일은 다음 호출에서 재사용.
    with _database(root) as db:
        db.execute("DELETE FROM chunks_fts WHERE receipt=?", (receipt,))
        db.execute("DELETE FROM chunks WHERE receipt=?", (receipt,))
        db.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?,?,?)",
                   (receipt, corp, published, MODEL, VERSION, digest, json.dumps(manifest)))
        for i, chunk in enumerate(chunks):
            db.execute("INSERT INTO chunks VALUES (?,?,?,?)",
                       (chunk["chunk_id"], receipt, i, json.dumps(chunk, ensure_ascii=False)))
            db.execute("INSERT INTO chunks_fts VALUES (?,?,?)",
                       (chunk["chunk_id"], receipt, " ".join(_terms(chunk["search_text"]))))
    return {"receipt": receipt, "blocks": len(blocks), "chunks": len(chunks),
            "cached": False, "raw_hash": digest, "embedding_model": MODEL}


def prepare_report(report: dict, root: Path = DEFAULT_ROOT, *, embed=embed_texts) -> dict:
    """공시 하나의 원문·추출·색인을 잠금 안에서 확인하고 부족한 단계만 준비한다.

    Args: report는 DART 실제 항목, root는 저장소, embed는 배치 임베딩 함수.
    Returns: 접수번호·청크 수·캐시 재사용 여부. 원문과 완료된 단계를 재사용한다.
    Raises: 미확인 정정/철회와 입력·파싱 오류는 ValueError. 외부·저장 오류는 전파.
    파일 저장 후 SQLite 트랜잭션으로 준비 완료를 기록하며 단일 프로세스만 지원한다.
    """
    with _PREPARATION_LOCK:
        return _prepare_report_locked(report, Path(root), embed)


def ensure_disclosures_ready(reports: list[dict], root: Path = DEFAULT_ROOT,
                             *, embed=embed_texts) -> list[dict]:
    """확정된 최대 두 공시를 준비하고 검색 가능한 접수번호별 결과를 반환한다.

    Args: reports는 회사·기준일·정정 검사까지 끝난 대상 목록, root는 저장소.
    Returns: 준비 결과 목록. 잠금 획득 뒤 원문·청크·색인 상태를 다시 확인한다.
    Raises: 두 건 초과는 ValueError. 각 문서의 준비 실패는 호출자에게 전파한다.
    다운로드·임베딩·로컬 파일 및 SQLite 쓰기가 발생할 수 있다.
    """
    if len(reports) > 2:
        raise ValueError("한 번에 준비할 공시는 최대 두 건입니다.")
    with _PREPARATION_LOCK:
        return [_prepare_report_locked(report, Path(root), embed) for report in reports]


def search_evidence(query: str, corp_code: str, as_of_date: str,
                    root: Path = DEFAULT_ROOT, *, receipt_ids: list[str] | None = None,
                    section_hint: str = "", limit: int = 5, embed=embed_texts) -> list[dict]:
    """검증된 회사·기준일까지 준비된 공시에서 근거를 하이브리드 검색한다.

    Args: query는 자연어 질문, corp_code/as_of_date는 고정 조사 조건,
        receipt_ids는 선택 문서, section_hint는 우선 목차, limit는 1~8개.
    Returns: 원문 구문·부모 문맥·출처·위치·검색 순위. 보고서가 없으면 빈 목록.
    임베딩 API 호출 외에는 원문 다운로드/재검색/답변 생성을 하지 않는다.
    잘못된 조건·모델/색인 불일치는 ValueError, 공급자 오류는 전파한다.
    """
    root = Path(root)
    if not query.strip() or len(query) > 2000 or not 1 <= limit <= 8:
        raise ValueError("검색어 또는 반환 수 범위 오류")
    if not re.fullmatch(r"\d{8}", corp_code): raise ValueError("회사 코드 오류")
    cutoff = dt.date.fromisoformat(as_of_date).strftime("%Y%m%d")
    if not (root / "catalog.sqlite").exists(): return []
    with _database(root) as db:
        reports = db.execute("SELECT * FROM reports WHERE corp=? AND published<=?",
                             (corp_code, cutoff)).fetchall()
        if receipt_ids is not None:
            reports = [r for r in reports if r["receipt"] in receipt_ids]
        if not reports: return []
        if any(r["model"] != MODEL or r["version"] != VERSION for r in reports):
            raise ValueError("색인 버전·임베딩 모델이 일치하지 않습니다.")
        receipts = [r["receipt"] for r in reports]
        placeholders = ",".join("?" for _ in receipts)
        rows = db.execute(f"SELECT * FROM chunks WHERE receipt IN ({placeholders})", receipts).fetchall()
        all_chunks = {r["id"]: json.loads(r["payload"]) for r in rows}
        # 목차 우선 검색은 정답 여부를 판정하지 않는다. 없으면 보고서 전체를 검색한다.
        allowed = {cid for cid, c in all_chunks.items() if not section_hint or section_hint in c["section"]}
        if not allowed: allowed = set(all_chunks)
        terms = list(dict.fromkeys(_terms(query)))[:80]
        expression = " OR ".join('"' + t + '"' for t in terms)
        keyword = []
        if expression:
            matches = db.execute(f"""SELECT id FROM chunks_fts WHERE chunks_fts MATCH ?
                AND receipt IN ({placeholders}) ORDER BY bm25(chunks_fts)""", [expression, *receipts])
            for row in matches:
                if row["id"] in allowed: keyword.append(row["id"])
                if len(keyword) >= 15: break
    q = embed([query])[0]
    candidates = []
    for report in reports:
        index = root / "indexes" / VERSION / report["receipt"]
        values = np.load(index / "vectors.npy", allow_pickle=False)
        ids = json.loads((index / "chunk_ids.json").read_text())
        if len(ids) != len(values) or values.shape[1] != len(q):
            raise ValueError("벡터 색인 모양 불일치")
        positions = [i for i, cid in enumerate(ids) if cid in allowed]
        scores = values[positions] @ q
        candidates.extend((ids[i], float(score)) for i, score in zip(positions, scores))
    semantic = [cid for cid, _ in sorted(candidates, key=lambda pair: (-pair[1], pair[0]))[:15]]
    fused = {}
    for ranking in (keyword, semantic):
        for rank, cid in enumerate(ranking, 1): fused[cid] = fused.get(cid, 0) + 1 / (60 + rank)
    row_receipts = {r["id"]: r["receipt"] for r in rows}
    meta = {r["receipt"]: json.loads(r["metadata"]) for r in reports}
    blocks_by_report, evidence, seen = {}, [], set()
    for cid in sorted(fused, key=lambda c: (-fused[c], c)):
        chunk = all_chunks[cid]
        if chunk["block_id"] in seen: continue
        seen.add(chunk["block_id"])
        receipt = row_receipts[cid]
        if receipt not in blocks_by_report:
            path = root / "parsed" / receipt / VERSION / "blocks.jsonl"
            blocks_by_report[receipt] = [json.loads(line) for line in path.read_text().splitlines()]
        blocks = blocks_by_report[receipt]
        i = chunk["block_index"]
        nearby = [b for b in blocks[max(0, i - 1):i + 2] if b["parent_id"] == chunk["parent_id"]]
        context = "\n".join(b["text"] if b["block_id"] != chunk["block_id"] else chunk["text"] for b in nearby)
        ids_context = ENCODING.encode(context)
        # 정답 자식 텍스트는 별도 필드로 항상 온전히 반환한다.
        evidence.append(dict(chunk, receipt_id=receipt, published_date=meta[receipt]["rcept_dt"],
            source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
            context=ENCODING.decode(ids_context[:1500]), context_truncated=len(ids_context) > 1500,
            rrf_score=fused[cid], keyword_rank=keyword.index(cid)+1 if cid in keyword else None,
            vector_rank=semantic.index(cid)+1 if cid in semantic else None))
        if len(evidence) >= limit: break
    return evidence


def retrieve_evidence(query: str, corp_code: str, as_of_date: str,
                      root: Path = DEFAULT_ROOT, *, receipt_ids: list[str],
                      section_hint: str = "", limit: int = 5, embed=embed_texts) -> list[dict]:
    """준비된 대상 접수번호 안에서 기존 파일럿의 순위 결합 방식으로 검색한다.

    Args: 회사·기준일·접수번호는 코드가 고정하고 query/section_hint만 모델 입력.
    Returns: 원문·부모 문맥·위치가 포함된 검색 근거. 미검색은 빈 목록.
    Raises: 입력·색인 불일치 및 임베딩 오류를 전파한다. 원문 준비를 반복하지 않는다.
    """
    return search_evidence(query, corp_code, as_of_date, root, receipt_ids=receipt_ids,
                           section_hint=section_hint, limit=limit, embed=embed)
