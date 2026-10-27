"""Chat completion clients (knowledge Q&A synthesis).

The gateway only accepts the ``course-chat`` model. Service code always passes
retrieved context explicitly; the client itself only performs the HTTP call.
"""
from __future__ import annotations

import json

import requests


class ChatError(RuntimeError):
    """The chat gateway rejected the request or is unavailable."""


class ChatClient:
    def complete(self, messages: list[dict]) -> str:
        raise NotImplementedError

    def stream(self, messages: list[dict]):
        """Yield answer text deltas. Base clients fall back to one chunk."""
        yield self.complete(messages)


class GatewayChatClient(ChatClient):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int,
        temperature: float,
        max_tokens: int,
    ):
        if not base_url:
            raise ChatError("缺少 EMBEDDING_BASE_URL（问答复用该网关地址）")
        if not api_key:
            raise ChatError("缺少 EMBEDDING_API_KEY")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def complete(self, messages: list[dict]) -> str:
        try:
            response = requests.post(
                self.url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ChatError(f"问答接口调用失败：{error}") from error
        if not response.ok:
            try:
                detail = response.json().get("error", {})
                message = detail.get("message") if isinstance(detail, dict) else None
            except ValueError:
                message = None
            raise ChatError(message or f"问答接口返回 {response.status_code}")
        return response.json()["choices"][0]["message"]["content"].strip()

    def stream(self, messages: list[dict]):
        try:
            response = requests.post(
                self.url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "stream": True,
                },
                timeout=self.timeout,
                stream=True,
            )
        except requests.RequestException as error:
            raise ChatError(f"问答接口调用失败：{error}") from error

        with response:
            if not response.ok:
                try:
                    detail = response.json().get("error", {})
                    message = (
                        detail.get("message") if isinstance(detail, dict) else None
                    )
                except ValueError:
                    message = None
                raise ChatError(message or f"问答接口返回 {response.status_code}")

            try:
                # Decode bytes ourselves: the gateway sends ``text/event-stream``
                # without a charset, so requests would fall back to ISO-8859-1.
                # Under latin-1, UTF-8 continuation bytes such as 0x85 become
                # U+0085, which str.splitlines() treats as a line break and
                # truncates the JSON chunk.
                for raw_line in response.iter_lines(decode_unicode=False):
                    if isinstance(raw_line, bytes):
                        line = raw_line.decode("utf-8", errors="replace").strip()
                    else:
                        line = (raw_line or "").strip()
                    if not line or line.startswith(":") or not line.startswith(
                        "data:"
                    ):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except ValueError as error:
                        raise ChatError("问答接口返回了无法解析的流式数据") from error

                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield content
            except requests.RequestException as error:
                raise ChatError(f"问答流式读取失败：{error}") from error


class StubChatClient(ChatClient):
    """Offline stub: echoes that the answer derives from supplied context."""

    def complete(self, messages: list[dict]) -> str:
        context = next(
            (m["content"] for m in messages if m.get("role") == "system"), ""
        )
        question = next(
            (m["content"] for m in messages if m.get("role") == "user"), ""
        )
        first_line = ""
        for line in context.splitlines():
            line = line.strip("-·• \n")
            if line:
                first_line = line[:80]
                break
        return f"（离线模式）根据资料，关于“{question[:40]}”：{first_line}"


def build_chat_client(config) -> ChatClient:
    backend = config["LLM_BACKEND"]
    if backend == "stub":
        return StubChatClient()
    if backend != "api":
        raise ChatError(f"未知 LLM_BACKEND：{backend}")
    return GatewayChatClient(
        base_url=config["EMBEDDING_BASE_URL"],
        api_key=config["EMBEDDING_API_KEY"],
        model=config["LLM_MODEL"],
        timeout=config["LLM_TIMEOUT"],
        temperature=config["LLM_TEMPERATURE"],
        max_tokens=config["LLM_MAX_TOKENS"],
    )
