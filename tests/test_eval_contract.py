"""외부 API 없이 평가 계약·잘못된 채점·반복 비교를 검증한다."""

import copy
import datetime
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

EVAL_ROOT = Path(__file__).resolve().parents[1] / "evals"
sys.path.insert(0, str(EVAL_ROOT / "scripts"))

import run_eval
from dataset_io import load_dataset, write_json
from validate_datasets import validate_datasets
from stock_agent.state import ParsedRequest


class EvalContractTest(unittest.TestCase):
    """정상/오류 반례와 고정 환경으로 평가 자체의 회귀를 검사한다."""

    def test_codex_subscription_is_distinguished_from_api_billing(self):
        model = Mock(model_name="gpt-5.6-luna", openai_api_base="https://chatgpt.com/backend-api/codex")
        with patch.object(run_eval, "get_chat_model", return_value=model):
            config = run_eval.current_model_config(["parsing"])
        self.assertEqual(config["parser"]["provider"], "openai_codex")
        self.assertNotIn("api_key", config["parser"])

    def test_prompt_hashes_include_common_rules_and_ignore_current_date(self):
        from stock_agent.prompts import builder
        before = run_eval.prompt_hashes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(builder.PROMPT_DIR, root, dirs_exist_ok=True)
            common = root / "common.md"
            common.write_text(common.read_text().replace("확인하지 않은 사실", "검증하지 않은 사실"))
            with patch.object(builder, "PROMPT_DIR", root):
                after = run_eval.prompt_hashes()
        self.assertNotEqual(before["parser"], after["parser"])
        self.assertNotEqual(before["planner"], after["planner"])
        with patch("stock_agent.agents.orchestrator.datetime.date") as date:
            date.today.side_effect = AssertionError("Prompt hash must not read the clock")
            self.assertEqual(before, run_eval.prompt_hashes())

    def test_current_datasets(self):
        self.assertEqual(validate_datasets(), {
            "input_parsing": 12, "planner_routing": 12,
            "end_to_end": 3, "grounding": 1,
        })

    def test_parser_uses_fixed_clock_and_company_fixture(self):
        case = load_dataset("input_parsing.json")[0]
        fake = Mock()
        fake.invoke.return_value = {"structured_response": ParsedRequest(
            company_candidates=["삼성전자"], research_question="주가 변동 이유",
            period_days=30,
        )}
        with (
            patch("stock_agent.control.request_parser.create_tool_agent", return_value=fake) as create_agent,
            patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")),
        ):
            result = run_eval.run_parsing_case(case, 1, verbose=False)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["actual"]["research_mandate"]["as_of_date"], case["today"])
        self.assertIn(case["today"], create_agent.call_args.args[1])
        self.assertEqual(
            fake.invoke.call_args.args[0]["messages"],
            [("user", case["raw_user_input"])],
        )
        self.assertIs(run_eval.datetime, datetime)

    def test_wrong_date_and_company_fail(self):
        case = load_dataset("input_parsing.json")[0]
        for field, wrong in (("as_of_date", "2026-08-24"), ("ticker", "035720"), ("period_days", 90)):
            with self.subTest(field=field):
                mandate = dict(case["expected"])
                mandate[field] = wrong
                with patch.object(run_eval, "invoke_node", return_value={"research_mandate": mandate}):
                    result = run_eval.run_parsing_case(case, 1, verbose=False)
                self.assertEqual(result["status"], "fail")
                self.assertFalse(result["checks"][field])

    def test_wrong_rejection_reason_does_not_pass_future_case(self):
        case = load_dataset("input_parsing.json")[10]
        for message, expected in [
            ("상장 회사명을 찾지 못했습니다.", "fail"),
            ("분석 기준일은 오늘보다 미래일 수 없습니다.", "pass"),
            ("", "fail"),
        ]:
            with patch.object(run_eval, "invoke_node", return_value={"input_error": message}):
                result = run_eval.run_parsing_case(case, 1, verbose=False)
            self.assertEqual(result["status"], expected)

    def test_error_date_runs_through_real_parser_validation(self):
        case = load_dataset("input_parsing.json")[10]
        fake = Mock()
        fake.invoke.return_value = {"structured_response": ParsedRequest(
            company_candidates=["삼성전자"], research_question="주가",
            as_of_date="2099-01-01", period_days=1,
        )}
        with patch("stock_agent.control.request_parser.create_tool_agent", return_value=fake):
            result = run_eval.run_parsing_case(case, 1, verbose=False)
        self.assertEqual(result["status"], "pass")

    def test_routing_uses_case_conditions(self):
        case = load_dataset("planner_routing.json")[0]
        case.update(as_of_date="2025-07-31", period_days=10)
        mandate = run_eval.build_routing_mandate(case)
        self.assertEqual(mandate["as_of_date"], "2025-07-31")
        self.assertEqual(mandate["period_days"], 10)

    def test_routing_invokes_upper_agent_with_case_context(self):
        from tests.test_chat_router import research_decision
        case = load_dataset("planner_routing.json")[0]
        with patch.object(run_eval, "invoke_node", return_value={"research_plan": research_decision().research_plan}) as invoke:
            run_eval.run_routing_case(case, 1, verbose=False)
        state = invoke.call_args.args[1]
        self.assertTrue(state["research_only"])
        for value in (case["corp_name"], case["as_of_date"], case["question"]):
            self.assertIn(value, state["raw_user_input"])
        self.assertNotIn("research_mandate", state)

    def test_dataset_validation_rejects_bad_contracts(self):
        mutations = [
            ("input_parsing", lambda rows: rows[0].update(expected_error="wrong")),
            ("input_parsing", lambda rows: rows[0]["expected"].update(period_days=0)),
            ("input_parsing", lambda rows: rows[0]["expected"].update(ticker="123")),
            ("input_parsing", lambda rows: rows[0].update(today="not-a-date")),
            ("input_parsing", lambda rows: rows[0].update(label_rationale="")),
            ("planner_routing", lambda rows: rows[0].update(expected_agents=["market"])),
            ("planner_routing", lambda rows: rows[0].update(expected_agents=["business", "business"])),
            ("end_to_end", lambda rows: rows[0].update(evaluation_status="ready")),
            ("grounding", lambda rows: rows[0].update(fixture="missing.json")),
            ("grounding", lambda rows: rows[0].update(fixture="../README.md")),
            ("grounding", lambda rows: rows[0]["expected_facts"][0].update(absolute_tolerance=-1)),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(EVAL_ROOT / "datasets", root / "datasets")
                shutil.copytree(EVAL_ROOT / "fixtures", root / "fixtures")
                path = root / "datasets" / f"{name}.json"
                rows = json.loads(path.read_text())
                mutate(rows)
                write_json(path, rows)
                with self.assertRaises(ValueError):
                    validate_datasets(root)

    def test_comparison_preserves_errors_and_contract_boundary(self):
        def trial(status):
            return {"case_id": "parsing-001", "suite": "parsing", "status": status, "latency_ms": 1}
        metadata = {"contract_hashes": {"x": "hash"}, "suites": ["parsing"],
                    "case_ids": ["parsing-001"], "requested_runs": 1}
        baseline = {"metadata": metadata, "runs": [trial("fail")]}
        self.assertEqual(run_eval.compare_runs(baseline, metadata, [trial("pass")])[0]["verdict"], "improved")
        baseline["runs"] = [trial("error")]
        self.assertEqual(run_eval.compare_runs(baseline, metadata, [trial("pass")])[0]["verdict"], "unknown")
        incompatible = copy.deepcopy(metadata)
        incompatible["contract_hashes"]["x"] = "other"
        with self.assertRaises(ValueError):
            run_eval.compare_runs(baseline, incompatible, [trial("pass")])
        with self.assertRaises(ValueError):
            run_eval.compare_runs({"metadata": {}, "runs": []}, metadata, [])

    def test_unknown_case_fails_before_model_initialization(self):
        with (
            patch.object(sys, "argv", ["run_eval.py", "--case-id", "missing"]),
            patch.object(run_eval, "current_model_config") as model_config,
        ):
            with self.assertRaises(ValueError):
                run_eval.main()
        model_config.assert_not_called()

    def test_report_labels_unscored_dimensions(self):
        results = [{"case_id": "parsing-001", "suite": "parsing", "status": "pass", "latency_ms": 1}]
        metadata = {"label": "local", "started_at": "", "finished_at": "",
                    "suites": ["parsing"], "requested_runs": 1}
        report = run_eval.render_report(metadata, run_eval.summarize_results(results), results)
        self.assertIn("금융 정확도는 미평가", report)
        self.assertIn("1/1", report)

    def test_runner_saves_and_compares_without_live_calls(self):
        fake = Mock()
        fake.invoke.return_value = {"structured_response": ParsedRequest(
            company_candidates=["삼성전자"], research_question="주가 변동 이유",
            period_days=30,
        )}
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "baseline"
            second = Path(directory) / "candidate"
            argv = ["run_eval.py", "--suite", "parsing", "--case-id", "parsing-001", "--runs", "2"]
            with (
                patch("stock_agent.control.request_parser.create_tool_agent", return_value=fake),
                patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")),
                patch.object(run_eval, "current_model_config", return_value={"parser": {"model": "mock"}}),
                patch.object(run_eval, "result_directory", return_value=first),
                patch.object(sys, "argv", argv),
            ):
                run_eval.main()
            with (
                patch("stock_agent.control.request_parser.create_tool_agent", return_value=fake),
                patch.object(run_eval, "current_model_config", return_value={"parser": {"model": "mock"}}),
                patch.object(run_eval, "result_directory", return_value=second),
                patch.object(sys, "argv", argv + ["--compare", str(first / "runs.json")]),
            ):
                run_eval.main()
            saved = json.loads((second / "summary.json").read_text())
            self.assertEqual(saved["summary"]["total_runs"], 2)
            self.assertEqual(saved["summary"]["comparison"][0]["verdict"], "unchanged")
            self.assertTrue(saved["metadata"]["contract_hashes"])
            self.assertTrue(saved["metadata"]["implementation_hashes"])
            self.assertIn("미평가", (second / "report.md").read_text())

    def test_incompatible_baseline_stops_before_models(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            write_json(path, {"metadata": {}, "runs": []})
            with (
                patch.object(sys, "argv", ["run_eval.py", "--compare", str(path)]),
                patch.object(run_eval, "current_model_config") as models,
            ):
                with self.assertRaises(ValueError):
                    run_eval.main()
            models.assert_not_called()


if __name__ == "__main__":
    unittest.main()
