"""장기 기억 파일과 실제 LangChain Tool loop를 외부 호출 없이 검증한다."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from stock_agent.tools import user_memory as memory
from stock_agent.agents.orchestrator import upper_agent_node
from tests import test_conversations


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class UserMemoryTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "memory" / "local" / "USER.md"
        self.enterContext(patch.object(memory, "MEMORY_PATH", self.path))

    def update(self, **args):
        return memory.create_memory_tool().invoke(args)

    def test_crud_and_partial_matching(self):
        self.assertEqual(memory.read_user_memory(), "")
        self.assertFalse(self.path.exists())
        self.update(action="add", content="사용자는 단기 투자 선호")
        self.update(action="add", content="사용자는 한국어 선호")
        self.assertTrue(self.update(action="replace", old_text="단기 투자", content="사용자는 장기 투자 선호")["success"])
        self.assertIn("한국어", memory.read_user_memory())
        self.assertTrue(self.update(action="remove", old_text="장기 투자")["success"])
        self.assertEqual(memory.read_user_memory(), "사용자는 한국어 선호")
        self.update(action="remove", old_text="한국어")
        self.assertEqual(memory.read_user_memory(), "")

    def test_duplicate_ambiguous_missing_and_invalid_content(self):
        for content in ("투자 성향 A", "투자 지식 B"):
            self.update(action="add", content=content)
        original = self.path.read_text()
        self.assertFalse(self.update(action="add", content="투자 성향 A")["changed"])
        for args in ({"action":"remove", "old_text":"투자"}, {"action":"replace", "old_text":"없음", "content":"새 내용"},
                     {"action":"add", "content":" "}, {"action":"add", "content":"A\n§\nB"}):
            self.assertFalse(self.update(**args)["success"])
            self.assertEqual(self.path.read_text(), original)

    def test_failed_write_and_unreadable_file_are_not_overwritten(self):
        self.update(action="add", content="보존할 기억")
        with patch.object(memory.os, "replace", side_effect=OSError("private path")):
            result = self.update(action="add", content="새 기억")
        self.assertFalse(result["success"])
        self.assertNotIn("private path", str(result))
        self.assertEqual(memory.read_user_memory(), "보존할 기억")
        self.path.write_bytes(b'\xff')
        self.assertFalse(self.update(action="add", content="새 기억")["success"])
        self.assertEqual(self.path.read_bytes(), b'\xff')

    def test_concurrent_sessions_preserve_each_others_entries(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: self.update(action="add", content=f"사실 {i}"), range(12)))
        self.assertTrue(all(result["success"] for result in results))
        self.assertEqual(len(memory.read_user_memory().split(memory.ENTRY_SEPARATOR)), 12)

    def test_three_attempt_limit(self):
        tool = memory.create_memory_tool()
        for i in range(3):
            self.assertTrue(tool.invoke({"action":"add", "content":f"사실 {i}"})["success"])
        self.assertTrue(tool.invoke({"action":"add", "content":"한도 초과"})["done"])
        self.assertNotIn("한도 초과", memory.read_user_memory())

    def test_actual_agent_tool_loop_then_structured_answer(self):
        model = ToolModel(responses=[
            AIMessage(content="", tool_calls=[{"name":"update_memory", "args":{"action":"add", "content":"사용자는 장기 투자 선호"}, "id":"memory1", "type":"tool_call"}]),
            AIMessage(content="", tool_calls=[{"name":"UpperDecision", "args":{"intent":"general", "final_answer":"기억했습니다.", "research_plan":None}, "id":"answer1", "type":"tool_call"}]),
        ])
        with patch("stock_agent.gateways.agent.get_chat_model", return_value=model):
            result = upper_agent_node({"raw_user_input":"나는 장기 투자가 좋아", "memory_enabled":True})
        self.assertEqual(result["final_answer"], "기억했습니다.")
        self.assertEqual(memory.read_user_memory(), "사용자는 장기 투자 선호")

    def test_actual_loop_continues_after_missing_target(self):
        self.update(action="add", content="남길 기억")
        model = ToolModel(responses=[
            AIMessage(content="", tool_calls=[{"name":"update_memory", "args":{"action":"remove", "old_text":"없는 기억"}, "id":"bad1", "type":"tool_call"}]),
            AIMessage(content="", tool_calls=[{"name":"UpperDecision", "args":{"intent":"general", "final_answer":"대상이 없어 삭제하지 못했습니다.", "research_plan":None}, "id":"answer2", "type":"tool_call"}]),
        ])
        with patch("stock_agent.gateways.agent.get_chat_model", return_value=model):
            result = upper_agent_node({"raw_user_input":"없는 기억 삭제해", "memory_enabled":True})
        self.assertIn("삭제하지 못", result["final_answer"])
        self.assertEqual(memory.read_user_memory(), "남길 기억")
        schema = memory.create_memory_tool().args
        self.assertEqual(set(schema), {"action", "content", "old_text"})


class MemoryChatTest(unittest.TestCase):
    setUp = test_conversations.ConversationTest.setUp
    create = test_conversations.ConversationTest.create
    send = test_conversations.ConversationTest.send

    def test_memory_shared_across_chats_and_independent_research_excluded(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(memory, "MEMORY_PATH", Path(directory)/"USER.md"):
            memory.create_memory_tool().invoke({"action":"add", "content":"사용자는 장기 투자 선호"})
            for cid in (self.create(), self.create()):
                self.send(cid)
                self.assertIn("[MEMORY]\n사용자는 장기 투자 선호", self.factory.call_args.args[1])
                self.assertEqual(self.factory.call_args.args[0][0].name, "update_memory")
            self.client.post('/api/chat/stream', json={"message":"안녕"})
            self.assertIn("[MEMORY]", self.factory.call_args.args[1])
            with patch('backend.main.trajectory_run'):
                self.client.post('/api/research/stream', json={"message":"삼성전자"})
            self.assertEqual(self.factory.call_args.args[0], [])
