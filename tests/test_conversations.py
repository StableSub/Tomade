"""임시 SQLite와 Mock으로 대화 격리·복원·삭제·응답 중단을 검증한다."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend import conversations
from backend.main import app, _stream_saved_chat_events
from stock_agent.agents.orchestrator import UpperDecision


class ConversationTest(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(conversations, "DB_PATH", Path(temporary) / "chat.sqlite3"))
        self.enterContext(patch("stock_agent.tools.user_memory.MEMORY_PATH", Path(temporary) / "USER.md"))
        self.enterContext(patch("stock_agent.graph.trajectory_run"))
        self.factory = self.enterContext(patch("stock_agent.agents.orchestrator.create_tool_agent"))
        self.answer = self.factory.return_value.invoke
        self.answer.return_value = {"structured_response": UpperDecision(intent="general", final_answer="일반 답변입니다.")}
        self.classify = self.answer
        self.client = self.enterContext(TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5000)))

    def create(self):
        response = self.client.post("/api/conversations")
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def messages(self, conversation_id):
        return self.client.get(f"/api/conversations/{conversation_id}").json()["messages"]

    def send(self, conversation_id, message="PER가 뭐야?"):
        return self.client.post("/api/chat/stream", json={"conversation_id": conversation_id, "message": message})

    def test_isolated_history_order_title_and_restart(self):
        first, second = self.create(), self.create()
        self.assertIn("run.completed", self.send(first).text)
        self.send(second, "분산투자 설명해줘")
        self.send(first, "배당이 뭐야?")
        expected = ["PER가 뭐야?", "일반 답변입니다.", "배당이 뭐야?", "일반 답변입니다."]
        self.assertEqual([m["content"] for m in self.messages(first)], expected)
        self.assertEqual(len(self.messages(second)), 2)
        listed = self.client.get("/api/conversations")
        self.assertEqual(listed.headers["cache-control"], "no-store")
        self.assertEqual(listed.json()[0]["id"], first)
        self.assertEqual(listed.json()[0]["title"], "PER가 뭐야?")
        conversations.initialize_database()
        self.assertEqual([m["content"] for m in self.messages(first)], expected)
        # 해당 세션의 완료된 대화만 역할을 유지해 전달한다.
        self.assertEqual(self.answer.call_args.args[0]["messages"], [("user", "PER가 뭐야?"), ("assistant", "일반 답변입니다."), ("user", "배당이 뭐야?")])

    def test_delete_cascades_and_missing_chat_never_calls_model(self):
        conversation_id = self.create()
        self.send(conversation_id)
        self.assertEqual(self.client.delete(f"/api/conversations/{conversation_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/conversations/{conversation_id}").status_code, 404)
        self.classify.reset_mock()
        self.assertEqual(self.send(conversation_id).status_code, 404)
        self.classify.assert_not_called()
        with conversations._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_pending_blocks_duplicate_and_delete_and_recovers_on_restart(self):
        conversation_id = self.create()
        conversations.begin_turn(conversation_id, "첫 질문")
        self.assertEqual(self.send(conversation_id).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/conversations/{conversation_id}").status_code, 409)
        self.classify.assert_not_called()
        self.assertEqual(len(self.messages(conversation_id)), 2)
        conversations.initialize_database()
        self.assertEqual(self.messages(conversation_id)[1]["status"], "interrupted")
        self.assertIn("run.completed", self.send(conversation_id).text)

    def test_error_is_saved_without_private_exception(self):
        conversation_id = self.create()
        self.answer.side_effect = RuntimeError("secret-account-token")
        response = self.send(conversation_id)
        self.assertIn("run.error", response.text)
        messages = self.messages(conversation_id)
        self.assertEqual(messages[1]["status"], "error")
        self.assertNotIn("secret-account-token", str(messages))

    def test_research_saves_only_final_answer(self):
        conversation_id = self.create()
        from tests.test_chat_router import research_decision, test_graph
        self.answer.return_value = {"structured_response": research_decision()}
        graph, _, _ = test_graph()
        with patch("backend.main.graph", graph), patch("stock_agent.agents.orchestrator.stream_agent_text", return_value="최종 조사 답변"):
            self.send(conversation_id, "삼성전자 분석해줘")
        messages = self.messages(conversation_id)
        self.assertEqual(messages[1]["content"], "최종 조사 답변")
        self.assertNotIn("internal-tool-result", str(messages))

    def test_terminal_saved_before_delivery_and_disconnect_recorded(self):
        conversation_id = self.create()
        async def exercise():
            message_id = conversations.begin_turn(conversation_id, "질문")
            stream = _stream_saved_chat_events("질문", message_id)
            await anext(stream)
            await stream.aclose()
            self.assertEqual(conversations.get_conversation(conversation_id)["messages"][1]["status"], "interrupted")
            message_id = conversations.begin_turn(conversation_id, "재시도")
            stream = _stream_saved_chat_events("재시도", message_id)
            async for frame in stream:
                if frame.startswith("event: run.completed"):
                    self.assertEqual(conversations.get_conversation(conversation_id)["messages"][-1]["status"], "completed")
        asyncio.run(exercise())

    def test_validation_and_local_access(self):
        conversation_id = self.create()
        for target, message in [("invalid-id", "질문"), (conversation_id, " "), (conversation_id, "x" * 301)]:
            self.assertEqual(self.send(target, message).status_code, 422)
        self.assertEqual(self.messages(conversation_id), [])
        for method, path in [("GET", "/api/conversations"), ("POST", "/api/conversations"),
                             ("GET", f"/api/conversations/{conversation_id}"), ("DELETE", f"/api/conversations/{conversation_id}")]:
            response = self.client.request(method, path, headers={"Origin": "https://example.com"})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.send(str(uuid4())).status_code, 404)
        self.classify.assert_not_called()

    def test_other_owner_not_listed_or_accessible(self):
        conversation_id = self.create()
        with conversations._connection() as db:
            db.execute("UPDATE conversations SET user_id = 'other' WHERE id = ?", (conversation_id,))
        self.assertEqual(self.client.get("/api/conversations").json(), [])
        self.assertEqual(self.client.get(f"/api/conversations/{conversation_id}").status_code, 404)
        self.assertEqual(self.send(conversation_id).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/conversations/{conversation_id}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
