"""실제 LangChain/SDK와 가짜 HTTP 응답으로 Codex 모델 계약을 검증한다."""

import json
import unittest
from unittest.mock import Mock, patch

import httpx
import openai
from langchain_core.tools import tool

from backend.short_term_memory import SessionSummary
from stock_agent.gateways.agent import create_tool_agent
from stock_agent.gateways.codex import CODEX_BASE_URL, ChatCodex, CodexHttpAuth, create_codex_model
from stock_agent.gateways.codex_auth import CodexAuth, CodexCredentials
from stock_agent.state import ParsedRequest


def sse_response(request_body, text="완료", *, call=None, terminal="completed"):
    """텍스트 또는 도구 호출 한 번의 실제 Responses SSE 형태를 만든다."""
    response = {
        "id": "resp_test", "object": "response", "created_at": 1,
        "model": "gpt-5.6-luna", "status": "in_progress", "error": None,
        "incomplete_details": None, "output": [], "parallel_tool_calls": True,
        "tool_choice": "auto", "tools": request_body.get("tools", []),
        "text": request_body.get("text", {"format": {"type": "text"}}),
        "usage": None,
    }
    events = [{"type": "response.created", "response": dict(response)}]
    if call:
        reasoning = {"type": "reasoning", "id": "rs_test", "summary": []}
        events.append({"type": "response.output_item.added", "output_index": 0, "item": dict(reasoning)})
        reasoning["encrypted_content"] = "encrypted-reasoning"
        events.append({"type": "response.output_item.done", "output_index": 0, "item": reasoning})
        item = {"type": "function_call", "id": "fc_test", "call_id": "call_test",
                "name": call[0], "arguments": "", "status": "in_progress"}
        events.append({"type": "response.output_item.added", "output_index": 1, "item": dict(item)})
        arguments = json.dumps(call[1])
        events.append({"type": "response.function_call_arguments.delta", "output_index": 1,
                       "item_id": "fc_test", "delta": arguments})
        item = {**item, "arguments": arguments, "status": "completed"}
        events.append({"type": "response.output_item.done", "output_index": 1, "item": item})
        response["output"] = [reasoning, item]
    else:
        item = {"type": "message", "id": "msg_test", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}]}
        events.extend([
            {"type": "response.output_item.added", "output_index": 0,
             "item": {**item, "content": [], "status": "in_progress"}},
            {"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
             "item_id": "msg_test", "delta": text},
            {"type": "response.output_text.done", "output_index": 0, "content_index": 0,
             "item_id": "msg_test", "text": text},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
        ])
        response["output"] = [item]
    if terminal:
        response["status"] = terminal
        response["usage"] = {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8,
                             "input_tokens_details": {"cached_tokens": 0},
                             "output_tokens_details": {"reasoning_tokens": 0}}
        if terminal == "incomplete":
            response["incomplete_details"] = {"reason": "max_output_tokens"}
        if terminal == "failed":
            response["error"] = {"code": "server_error", "message": "failed"}
        events.append({"type": f"response.{terminal}", "response": response})
    encoded = "".join(f"data: {json.dumps({**event, 'sequence_number': i}, ensure_ascii=False)}\n\n"
                      for i, event in enumerate(events))
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=encoded.encode())


class CodexModelTest(unittest.IsolatedAsyncioTestCase):
    async def test_factory_serializes_reasoning_into_responses_payload(self):
        for effort in (None, "high", "none"):
            model = create_codex_model("gpt-5.6-terra", reasoning_effort=effort)
            try:
                payload = model._get_request_payload("test")
                if effort is None:
                    self.assertNotIn("reasoning", payload)
                else:
                    self.assertEqual(payload["reasoning"], {"effort": effort})
                self.assertTrue(payload["stream"])
                self.assertFalse(payload["store"])
            finally:
                model.http_client.close()
                await model.http_async_client.aclose()

    def model(self, handler, auth=None):
        auth = auth or Mock(spec=CodexAuth)
        if not auth.credentials.side_effect:
            auth.credentials.return_value = CodexCredentials("fake-token", "fake-account", 9999999999)
        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport, auth=CodexHttpAuth(auth), follow_redirects=False)
        async_client = httpx.AsyncClient(transport=transport, auth=CodexHttpAuth(auth), follow_redirects=False)
        self.addCleanup(client.close)
        self.addAsyncCleanup(async_client.aclose)
        return ChatCodex(model="gpt-5.6-luna", api_key="dummy", base_url=CODEX_BASE_URL,
                         streaming=True, store=False, max_retries=0,
                         http_client=client, http_async_client=async_client)

    def test_invoke_and_stream_preserve_text_usage_and_instructions(self):
        requests = []

        def handler(request):
            requests.append((dict(request.headers), json.loads(request.content)))
            self.assertEqual(str(request.url), CODEX_BASE_URL + "/responses")
            return sse_response(requests[-1][1])

        model = self.model(handler)
        message = model.invoke([("system", "기존 시스템 지시"), ("user", "질문")])
        self.assertEqual(message.text, "완료")
        self.assertEqual(message.usage_metadata["total_tokens"], 8)
        self.assertEqual(message.response_metadata["status"], "completed")
        self.assertEqual("".join(chunk.text for chunk in model.stream("질문")), "완료")
        headers, payload = requests[0]
        self.assertEqual(headers["authorization"], "Bearer fake-token")
        self.assertEqual(headers["chatgpt-account-id"], "fake-account")
        self.assertEqual(headers["originator"], "stock-agent")
        self.assertEqual(headers["user-agent"], "stock-agent/0.1.0")
        self.assertEqual(headers["openai-beta"], "responses=experimental")
        self.assertEqual(headers["accept"], "text/event-stream")
        self.assertEqual(payload["instructions"], "기존 시스템 지시")
        self.assertEqual(payload["input"], [{"role": "user", "content": "질문", "type": "message"}])
        self.assertIs(payload["stream"], True)
        self.assertIs(payload["store"], False)
        self.assertIn("reasoning.encrypted_content", payload["include"])

    async def test_async_invoke_and_stream(self):
        model = self.model(lambda request: sse_response(json.loads(request.content)))
        result = await model.ainvoke("질문")
        self.assertEqual(result.text, "완료")
        self.assertEqual(result.usage_metadata["total_tokens"], 8)
        chunks = [chunk async for chunk in model.astream("질문")]
        self.assertEqual("".join(chunk.text for chunk in chunks), "완료")
        self.assertEqual(chunks[-1].response_metadata["status"], "completed")

    async def test_structured_summary_sync_and_async(self):
        expected = SessionSummary(goal="목표", constraints="조건", active_state="진행", resolved_questions="해결")
        requests = []

        def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            return sse_response(payload, expected.model_dump_json())

        structured = self.model(handler).with_structured_output(SessionSummary)
        self.assertEqual(structured.invoke("요약"), expected)
        self.assertEqual(await structured.ainvoke("요약"), expected)
        for payload in requests:
            self.assertEqual(payload["text"]["format"]["type"], "json_schema")
            self.assertEqual(payload["text"]["format"]["schema"]["required"],
                             ["goal", "constraints", "active_state", "resolved_questions"])

    def test_real_agent_tool_loop_and_structured_parser_replay(self):
        saved = []

        @tool
        def save_preference(preference: str) -> str:
            """검증용 선호를 메모리에 저장한다."""
            saved.append(preference)
            return "저장 완료"

        expected = ParsedRequest(company_candidates=["삼성전자"], research_question="실적 분석")
        requests = []

        def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if len(requests) == 1:
                return sse_response(payload, call=("save_preference", {"preference": "한국어"}))
            return sse_response(payload, expected.model_dump_json())

        model = self.model(handler)
        with patch("stock_agent.gateways.agent.get_chat_model", return_value=model):
            agent = create_tool_agent([save_preference], "현재 조사 지시", response_format=ParsedRequest,
                                      model_role="parser", trace_node_name="codex_mock")
        result = agent.invoke({"messages": [("user", "한국어로 삼성전자를 분석해 줘")]})
        self.assertEqual(result["structured_response"], expected)
        self.assertEqual(saved, ["한국어"])
        self.assertEqual(len(requests), 2)
        replay = requests[1]
        self.assertEqual(replay["instructions"], "현재 조사 지시")
        self.assertEqual(replay["text"]["format"]["type"], "json_schema")
        self.assertNotIn("previous_response_id", replay)
        self.assertTrue(all("id" not in item for item in replay["input"]))
        reasoning = next(item for item in replay["input"] if item["type"] == "reasoning")
        self.assertEqual(reasoning["encrypted_content"], "encrypted-reasoning")
        call = next(item for item in replay["input"] if item["type"] == "function_call")
        output = next(item for item in replay["input"] if item["type"] == "function_call_output")
        self.assertEqual(call["call_id"], output["call_id"])
        self.assertEqual(output["output"], "저장 완료")

    async def test_unfinished_streams_fail_sync_and_async(self):
        for terminal in (None, "incomplete", "failed"):
            with self.subTest(terminal=terminal):
                model = self.model(lambda request: sse_response(json.loads(request.content), terminal=terminal))
                with self.assertRaises(ValueError):
                    model.invoke("질문")
                with self.assertRaises(ValueError):
                    await model.ainvoke("질문")

    async def test_401_refreshes_once_for_sync_and_async(self):
        for use_async in (False, True):
            with self.subTest(use_async=use_async):
                auth = Mock(spec=CodexAuth)
                auth.credentials.side_effect = [CodexCredentials("old", "account", 9999999999),
                                                CodexCredentials("new", "account", 9999999999)]
                tokens = []

                def handler(request):
                    tokens.append(request.headers["authorization"])
                    if len(tokens) == 1:
                        return httpx.Response(401, json={"error": {"message": "expired", "type": "invalid_request_error"}})
                    return sse_response(json.loads(request.content))

                model = self.model(handler, auth)
                result = await model.ainvoke("질문") if use_async else model.invoke("질문")
                self.assertEqual(result.text, "완료")
                self.assertEqual(tokens, ["Bearer old", "Bearer new"])
                self.assertEqual(auth.credentials.call_count, 2)
                auth.credentials.assert_called_with(force_refresh=True, rejected_access_token="old")

    def test_429_propagates_without_refresh_or_fallback(self):
        auth = Mock(spec=CodexAuth)
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(429, json={"error": {"message": "usage limit", "type": "usage_limit_reached"}})

        with self.assertRaises(openai.RateLimitError):
            self.model(handler, auth).invoke("질문")
        self.assertEqual(len(calls), 1)
        auth.credentials.assert_called_once_with()

    def test_auth_rejects_a_different_destination(self):
        auth = Mock(spec=CodexAuth)
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)),
                          auth=CodexHttpAuth(auth)) as client:
            with self.assertRaises(ValueError):
                client.get("https://example.com/responses")
        auth.credentials.assert_not_called()


if __name__ == "__main__":
    unittest.main()
