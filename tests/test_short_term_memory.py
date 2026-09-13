"""임시 DB·Mock 모델로 10턴 경계, 원문 보존과 실패 처리를 검증한다."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import conversations
from backend.short_term_memory import SessionSummary, prepare_short_term_memory
from stock_agent.gateways.llm import _resolve_model
from tests import test_conversations
from tests.test_chat_router import research_decision, test_graph


def summary(label="목표"):
    return SessionSummary(goal=label, constraints="조건", active_state="진행 중", resolved_questions="해결 근거")


class MemoryStoreTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "chat.sqlite3"
        self.enterContext(patch.object(conversations, "DB_PATH", self.path))
        conversations.initialize_database()
        self.cid = conversations.create_conversation()["id"]
        self.model = self.enterContext(patch("backend.short_term_memory.get_chat_model"))
        self.invoke = self.model.return_value.with_structured_output.return_value.invoke
        self.invoke.return_value = summary()

    def seed(self, count, status="completed"):
        ids = []
        for i in range(count):
            mid = conversations.begin_turn(self.cid, f"질문 {i}")
            conversations.finish_turn(mid, f"답변 {i}", status)
            ids.append(mid)
        return ids

    def test_ten_turns_no_summary_and_current_question_excluded(self):
        self.seed(10)
        mid = conversations.begin_turn(self.cid, "현재 질문")
        result = prepare_short_term_memory(mid)
        self.assertEqual(len(result["recent_messages"]), 20)
        self.assertEqual(result["recent_messages"][-1], ("assistant", "답변 9"))
        self.assertEqual(result["short_term_summary"], "")
        self.model.assert_not_called()

    def test_eleven_turns_then_next_turn_uses_prior_summary_once(self):
        ids = self.seed(11)
        mid = conversations.begin_turn(self.cid, "12번째 질문")
        result = prepare_short_term_memory(mid)
        self.assertEqual(result["recent_messages"][0], ("user", "질문 1"))
        self.assertEqual(self.invoke.call_args.args[0][2:], [("user", "질문 0"), ("assistant", "답변 0")])
        saved = conversations.get_conversation(self.cid)
        self.assertEqual(saved["last_summarized_message_id"], ids[0])
        self.assertEqual(len(saved["messages"]), 24)
        # 같은 요청 재구성은 중복 압축하지 않는다.
        prepare_short_term_memory(mid)
        self.invoke.assert_called_once()
        conversations.finish_turn(mid, "12번째 답변", "completed")
        mid = conversations.begin_turn(self.cid, "13번째 질문")
        prepare_short_term_memory(mid)
        messages = self.invoke.call_args.args[0]
        self.assertEqual(messages[1], ("user", "기존 요약:\n" + result["short_term_summary"]))
        self.assertEqual(messages[2:], [("user", "질문 1"), ("assistant", "답변 1")])

    def test_backlog_excludes_failed_interrupted_turns_and_other_sessions(self):
        self.seed(2, "error")
        self.seed(2, "interrupted")
        ids = self.seed(13)
        other = conversations.create_conversation()["id"]
        mid = conversations.begin_turn(other, "다른 세션")
        conversations.finish_turn(mid, "다른 답변", "completed")
        mid = conversations.begin_turn(self.cid, "현재 질문")
        result = prepare_short_term_memory(mid)
        self.assertEqual(len(self.invoke.call_args.args[0][2:]), 6)
        self.assertEqual(len(result["recent_messages"]), 20)
        self.assertEqual(conversations.get_conversation(self.cid)["last_summarized_message_id"], ids[2])
        self.assertEqual(conversations.get_conversation(other)["summary"], "")

    def test_summary_exception_or_invalid_result_preserves_db(self):
        ids = self.seed(11)
        conversations.save_memory_summary(self.cid, "기존 요약", ids[0])
        self.seed(1)
        mid = conversations.begin_turn(self.cid, "현재 질문")
        for failure in (RuntimeError("secret"), {"goal": " "}):
            with self.subTest(failure=failure):
                self.invoke.side_effect = failure if isinstance(failure, Exception) else None
                self.invoke.return_value = failure
                with self.assertRaises((RuntimeError, ValueError)):
                    prepare_short_term_memory(mid)
                saved = conversations.get_conversation(self.cid)
                self.assertEqual(saved["summary"], "기존 요약")
                self.assertEqual(saved["last_summarized_message_id"], ids[0])
                self.assertEqual(len(saved["messages"]), 26)

    def test_summary_and_boundary_update_roll_back_together(self):
        ids = self.seed(11)
        mid = conversations.begin_turn(self.cid, "현재 질문")
        with conversations._connection() as db:
            db.execute("CREATE TRIGGER fail_summary BEFORE UPDATE OF last_summarized_message_id ON conversations BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            prepare_short_term_memory(mid)
        saved = conversations.get_conversation(self.cid)
        self.assertEqual(saved["summary"], "")
        self.assertIsNone(saved["last_summarized_message_id"])

    def test_old_database_migration_preserves_history_and_is_repeatable(self):
        old_path = self.path.parent / "old.sqlite3"
        with sqlite3.connect(old_path) as db:
            db.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            db.execute("INSERT INTO conversations VALUES ('old', 'local', '기존 제목', 'now', 'now')")
        with patch.object(conversations, "DB_PATH", old_path):
            conversations.initialize_database()
            mid = conversations.begin_turn("old", "기존 질문")
            conversations.finish_turn(mid, "기존 답변", "completed")
            conversations.initialize_database()
            row = conversations.get_conversation("old")
            self.assertEqual(len(row["messages"]), 2)
            self.assertEqual(row["summary"], "")
            self.assertIsNone(row["last_summarized_message_id"])
            self.assertTrue(conversations.create_conversation()["id"])

    def test_summary_role_ignores_common_model(self):
        with patch.dict("os.environ", {"LLM_MODEL": "common", "SUMMARY_MODEL": ""}):
            self.assertEqual(_resolve_model("openai", "summary"), "gpt-5.6-luna")
            self.assertEqual(_resolve_model("openrouter", "summary"), "openai/gpt-5.6-luna")


class MemoryStreamTest(unittest.TestCase):
    setUp = test_conversations.ConversationTest.setUp
    create = test_conversations.ConversationTest.create
    send = test_conversations.ConversationTest.send
    messages = test_conversations.ConversationTest.messages

    def test_summary_is_in_system_prompt_history_keeps_roles_after_restart(self):
        cid = self.create()
        for i in range(11):
            mid = conversations.begin_turn(cid, f"질문 {i}")
            conversations.finish_turn(mid, f"답변 {i}", "completed")
        with patch("backend.short_term_memory.get_chat_model") as model:
            model.return_value.with_structured_output.return_value.invoke.return_value = summary("사용자 목표")
            self.send(cid, "현재 질문")
        system = self.factory.call_args.args[1]
        self.assertIn("[SHORT_TERM_MEMORY]", system)
        self.assertIn("사용자 목표", system)
        self.assertNotIn("질문 1", system)
        messages = self.answer.call_args.args[0]["messages"]
        self.assertEqual(len(messages), 21)
        self.assertEqual(messages[0], ("user", "질문 1"))
        self.assertEqual(messages[-1], ("user", "현재 질문"))
        saved_summary = conversations.get_conversation(cid)["summary"]
        conversations.initialize_database()
        self.assertEqual(conversations.get_conversation(cid)["summary"], saved_summary)

    def test_compression_failure_is_terminal_and_does_not_call_upper_agent(self):
        cid = self.create()
        for i in range(11):
            mid = conversations.begin_turn(cid, f"질문 {i}")
            conversations.finish_turn(mid, "답변", "completed")
        with patch("backend.short_term_memory.get_chat_model", side_effect=RuntimeError("private-key")):
            response = self.send(cid)
        self.assertIn("run.error", response.text)
        self.assertNotIn("private-key", response.text)
        self.answer.assert_not_called()
        self.assertEqual(self.messages(cid)[-1]["status"], "error")
        saved = conversations.get_conversation(cid)
        self.assertIsNone(saved["last_summarized_message_id"])

    def test_research_reentry_keeps_memory_but_workers_do_not_receive_it(self):
        cid = self.create()
        self.send(cid, "나의 선호를 기억해")
        self.answer.return_value = {"structured_response": research_decision()}
        graph, parser, workers = test_graph()
        with patch("backend.main.graph", graph), patch("stock_agent.agents.orchestrator.stream_agent_text", return_value="종합") as finish:
            self.send(cid, "삼성전자 조사")
        first = self.answer.call_args.args[0]["messages"]
        final = finish.call_args.args[1]["messages"]
        self.assertEqual(first[:2], final[:2])
        self.assertEqual(first[-1], ("user", "삼성전자 조사"))
        self.assertEqual(final.count(("user", "삼성전자 조사")), 1)
        for state in (parser.call_args.args[0], workers["business"].call_args.args[0]):
            self.assertNotIn("recent_messages", state)
            self.assertNotIn("short_term_summary", state)
