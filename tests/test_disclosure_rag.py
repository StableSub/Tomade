"""외부 API 없이 원문 보존·캐시·검색 경계·고정 Tool 입력을 검증한다."""

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from stock_agent.rag.parser import parse_archive, make_chunks
from stock_agent.rag.service import prepare_report, search_evidence
from stock_agent.tools.disclosure_rag import make_disclosure_search_tool
from stock_agent.vendors.dart_client import list_disclosure_reports, download_disclosure_original

REPORT = {"corp_code": "00126380", "rcept_no": "20260310002820",
          "rcept_dt": "20260310", "report_nm": "사업보고서 (2025.12)", "rm": "연"}
XML = '''<DOCUMENT><SECTION-1><TITLE>사업의 내용</TITLE>
<P>R&D 연구개발로 반도체 제품을 생산합니다.</P></SECTION-1>
<SECTION-1><TITLE>차입금 주석</TITLE><P>연결 기준, 단위: 백만원</P>
<TABLE><TR><TD><P>상환 계획</P><TABLE><THEAD><TR><TH>항목</TH><TH>2025년</TH></TR></THEAD>
<TBODY><TR><TD ROWSPAN="2">차입금</TD><TD>100</TD></TR><TR><TD>200</TD></TR></TBODY>
</TABLE><P>만기 전에 상환합니다.</P></TD></TR></TABLE></SECTION-1></DOCUMENT>'''


def archive(text=XML, name="report.xml"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z: z.writestr(name, text)
    return b.getvalue()


def fake_embed(texts):
    return np.asarray([[1., 0.] for _ in texts], dtype=np.float32)


class RagTest(unittest.TestCase):
    def test_structure_table_and_bare_ampersand(self):
        blocks = parse_archive(archive(), REPORT["rcept_no"])
        self.assertTrue(any("R&D" in b["text"] for b in blocks))
        table = next(b for b in blocks if b["kind"] == "table")
        self.assertEqual(table["rows"], ["항목 | 2025년", "차입금 | 100", "차입금 | 200"])
        chunks = make_chunks(blocks)
        self.assertTrue(any("백만원" in c["search_text"] and "차입금 | 100" in c["text"] for c in chunks))
        self.assertTrue(all(c["source_line"] > 0 for c in chunks))

    def test_unsafe_zip_and_xml_declaration(self):
        for payload in [archive(name="../x.xml"), archive('<!DOCTYPE x>'+XML)]:
            with self.assertRaises(ValueError): parse_archive(payload, REPORT["rcept_no"])

    @patch("stock_agent.rag.service.download_disclosure_original", return_value=archive())
    def test_store_cache_hybrid_and_date_company_filter(self, download):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = prepare_report(REPORT, root, embed=fake_embed)
            self.assertFalse(first["cached"])
            self.assertTrue(prepare_report(REPORT, root, embed=Mock(side_effect=AssertionError))["cached"])
            download.assert_called_once()
            result = search_evidence("차입금", "00126380", "2026-03-10", root, embed=fake_embed)
            self.assertTrue(any("차입금 | 100" in r["text"] for r in result))
            self.assertTrue(all(r["keyword_rank"] or r["vector_rank"] for r in result))
            no_call = Mock(side_effect=AssertionError)
            self.assertEqual(search_evidence("차입금", "00126380", "2026-03-09", root, embed=no_call), [])
            self.assertEqual(search_evidence("차입금", "00000000", "2026-03-10", root, embed=no_call), [])

    def test_unresolved_correction_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): prepare_report(dict(REPORT, rm="정"), Path(tmp), embed=fake_embed)

    @patch("stock_agent.tools.disclosure.retrieve_evidence", return_value=[])
    @patch("stock_agent.tools.disclosure.ensure_disclosures_ready")
    @patch("stock_agent.tools.disclosure.discover_disclosures",
           return_value={"reports": [REPORT], "limitations": [], "reason": None})
    def test_tool_fixed_scope_runtime_owns_budget(self, discover, ready, search):
        tool = make_disclosure_search_tool("00126380", "2026-03-10")
        for _ in range(4):
            result = json.loads(tool.invoke({"question": "차입금"}))
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["reason"], "no_hits")
        self.assertEqual(search.call_count, 4)
        self.assertEqual(search.call_args.args[1:3], ("00126380", "2026-03-10"))
        self.assertEqual(search.call_args.kwargs["receipt_ids"], [REPORT["rcept_no"]])
        self.assertEqual(set(tool.args), {"question", "section_hint"})

    @patch("stock_agent.vendors.dart_client._get_api_key", return_value="test-only")
    @patch("stock_agent.vendors.dart_client.requests.get")
    def test_discovery_pagination_and_api_errors(self, get, key):
        get.side_effect = [Mock(json=lambda: {"status":"000", "total_page":2, "list":[REPORT]}),
                           Mock(json=lambda: {"status":"000", "total_page":2, "list":[]})]
        self.assertEqual(list_disclosure_reports("00126380", "2026-01-01", "2026-03-10"), [REPORT])
        self.assertEqual(get.call_args.kwargs["params"]["end_de"], "20260310")
        self.assertEqual(get.call_args.kwargs["params"]["page_no"], 2)
        get.side_effect = None
        get.return_value = Mock(json=lambda: {"status": "020"})
        with self.assertRaises(RuntimeError): list_disclosure_reports("00126380", "2026-01-01", "2026-03-10")
        get.return_value = Mock(content=b'<result><status>014</status></result>')
        with self.assertRaises(RuntimeError): download_disclosure_original("20260310002820")


if __name__ == "__main__": unittest.main()
