"""Codex 구독 통신을 기존 LangChain 모델 계약에 연결한다."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import aclosing, closing
from typing import Any, Literal

import httpx
from langchain_core.language_models.chat_models import agenerate_from_stream, generate_from_stream
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from stock_agent.gateways.codex_auth import CodexAuth

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"


class CodexHttpAuth(httpx.Auth):
    """요청마다 최신 OAuth 인증을 적용하고 401에 한 번만 갱신한다.

    Args:
        auth: 프로젝트 전용 인증 저장소. 모델 역할 사이에서 공유할 수 있다.
    Note:
        토큰은 지정된 Codex Responses 주소에만 전달한다. 429는 갱신하지
        않으며 인증/네트워크 오류는 호출자에게 전달한다.
    """

    def __init__(self, auth: CodexAuth):
        self.auth = auth

    @staticmethod
    def _check_url(request: httpx.Request) -> None:
        if str(request.url) != CODEX_BASE_URL + "/responses":
            raise ValueError("Codex 인증은 지정된 Responses 주소에만 사용할 수 있습니다.")

    @staticmethod
    def _authorize(request: httpx.Request, credentials: Any) -> None:
        request.headers["Authorization"] = f"Bearer {credentials.access_token}"
        request.headers["ChatGPT-Account-Id"] = credentials.account_id
        request.headers["originator"] = "stock-agent"
        request.headers["User-Agent"] = "stock-agent/0.1.0"
        request.headers["OpenAI-Beta"] = "responses=experimental"
        request.headers["Accept"] = "text/event-stream"

    def sync_auth_flow(self, request: httpx.Request):
        """동기 요청에 인증을 적용한다. 거절된 토큰만 한 번 갱신한다."""
        self._check_url(request)
        credentials = self.auth.credentials()
        self._authorize(request, credentials)
        response = yield request
        if response.status_code == 401:
            response.read()
            credentials = self.auth.credentials(
                force_refresh=True, rejected_access_token=credentials.access_token,
            )
            self._authorize(request, credentials)
            yield request

    async def async_auth_flow(self, request: httpx.Request):
        """파일 잠금·토큰 갱신을 별도 스레드에서 처리해 이벤트 루프를 유지한다."""
        self._check_url(request)
        credentials = await asyncio.to_thread(self.auth.credentials)
        self._authorize(request, credentials)
        response = yield request
        if response.status_code == 401:
            await response.aread()
            credentials = await asyncio.to_thread(
                self.auth.credentials, force_refresh=True,
                rejected_access_token=credentials.access_token,
            )
            self._authorize(request, credentials)
            yield request


class ChatCodex(ChatOpenAI):
    """Codex Responses를 호출하는 LangChain Chat Model.

    Args:
        model: 로그인한 계정에서 사용할 수 있는 Codex 모델 ID.
        **kwargs: ChatOpenAI 설정. 클라이언트 인증은 create_codex_model이 구성한다.
    Note:
        Tool 실행·Agent loop는 LangChain에 남긴다. 구조화 출력과 Tool Call은
        기존 SDK로 변환하며 서버 저장 없이 전체 메시지를 재전송한다.
        invoke도 내부적으로 스트림을 모은다. 완료 이벤트가 없거나 응답이
        incomplete이면 ValueError로 실패해 부분 결과를 성공으로 쓰지 않는다.
    """

    use_responses_api: Literal[True] = True
    store: Literal[False] = False
    use_previous_response_id: Literal[False] = False
    streaming: Literal[True] = True
    disable_streaming: Literal[False] = False

    def _get_request_payload(self, input_, *, stop=None, **kwargs) -> dict:
        # SDK가 구조화 출력과 과거 메시지를 변환하기 전에 전송 조건을 고정한다.
        kwargs.update(stream=True, store=False)
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        unsupported = {"previous_response_id", "max_output_tokens", "temperature", "top_p"} & payload.keys()
        if unsupported:
            raise ValueError("Codex 구독 호출에서 지원하지 않는 설정: " + ", ".join(sorted(unsupported)))

        instructions = [payload.pop("instructions", "")]
        while payload["input"] and payload["input"][0].get("role") in {"system", "developer"}:
            content = payload["input"].pop(0)["content"]
            if isinstance(content, str):
                instructions.append(content)
            else:
                instructions.extend(part["text"] for part in content)
        payload["instructions"] = "\n\n".join(text for text in instructions if text) or "You are a helpful assistant."
        payload["include"] = list(dict.fromkeys([*payload.get("include", []), "reasoning.encrypted_content"]))
        # store=false 응답은 서버의 item ID에 의존하지 않고 본문과 call_id로 재생한다.
        for item in payload["input"]:
            item.pop("id", None)
        return payload

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        return generate_from_stream(self._stream(messages, stop=stop, run_manager=run_manager, **kwargs))

    async def _agenerate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        return await agenerate_from_stream(self._astream(messages, stop=stop, run_manager=run_manager, **kwargs))

    @staticmethod
    def _completed(chunk: ChatGenerationChunk) -> bool:
        status = chunk.message.response_metadata.get("status")
        if status is not None and status != "completed":
            raise ValueError("Codex 모델 응답이 완료되지 않았습니다. 요청을 다시 확인하세요.")
        return status == "completed"

    def _stream(self, *args, **kwargs) -> Iterator[ChatGenerationChunk]:
        completed = False
        with closing(super()._stream(*args, **kwargs)) as stream:
            for chunk in stream:
                completed = self._completed(chunk) or completed
                yield chunk
        if not completed:
            raise ValueError("Codex 스트림이 완료 이벤트 없이 종료되었습니다.")

    async def _astream(self, *args, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        completed = False
        async with aclosing(super()._astream(*args, **kwargs)) as stream:
            async for chunk in stream:
                completed = self._completed(chunk) or completed
                yield chunk
        if not completed:
            raise ValueError("Codex 스트림이 완료 이벤트 없이 종료되었습니다.")


def create_codex_model(model: str, auth: CodexAuth | None = None) -> ChatCodex:
    """구독 인증을 적용한 모델을 만든다. 생성 시에는 로그인·외부 호출을 하지 않는다.

    Args:
        model: 역할별 Codex 모델 ID.
        auth: 선택적인 인증 관리자. 생략하면 프로젝트 전용 기본 저장소를 사용한다.
    Returns:
        invoke/ainvoke/stream/astream과 기존 Tool·구조화 출력을 제공하는 모델.
    Note:
        실제 호출 시 인증 파일을 읽으며 401만 한 번 갱신한다. 그 외 재시도와
        유료 API fallback은 없다. 네트워크 읽기 제한 시간은 120초다.
    """
    http_auth = CodexHttpAuth(auth or CodexAuth())
    timeout = httpx.Timeout(120, connect=10)
    return ChatCodex(
        model=model,
        api_key="codex-oauth",
        base_url=CODEX_BASE_URL,
        streaming=True,
        store=False,
        include=["reasoning.encrypted_content"],
        max_retries=0,
        timeout=timeout,
        http_client=httpx.Client(auth=http_auth, timeout=timeout, follow_redirects=False),
        http_async_client=httpx.AsyncClient(auth=http_auth, timeout=timeout, follow_redirects=False),
    )
