from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx


class LLMError(RuntimeError):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: Dict[str, Any]


def _to_openai_tools_payload(tools: List[ToolSpec]) -> List[Dict[str, Any]]:
    """
    Convert ToolSpec -> OpenAI-compatible tools payload.
    """
    out: List[Dict[str, Any]] = []
    for t in tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema,
                },
            }
        )
    return out


class OpenAICompatChat:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        timeout_sec: Optional[float] = None,
        max_retries: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

        # Default to something sane for tool-using agents.
        # You can override with env LLM_TIMEOUT_SEC.
        if timeout_sec is None:
            timeout_sec = float(os.environ.get("LLM_TIMEOUT_SEC", "180"))

        self.timeout = httpx.Timeout(
            connect=10.0,
            read=timeout_sec,
            write=30.0,
            pool=timeout_sec,
        )
        self.max_retries = max_retries

    def run_with_tools(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools: List[ToolSpec],
        tool_handler: Callable[[str, Dict[str, Any]], Dict[str, Any]],
        max_tool_round_trips: int = 20,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        tool_payload = _to_openai_tools_payload(tools)

        # One loop where the model can call tools repeatedly.
        for _ in range(max_tool_round_trips):
            resp = self._chat(messages=messages, tools=tool_payload)

            # OpenAI compat: choices[0].message
            choice = (resp.get("choices") or [{}])[0]
            msg = choice.get("message") or {}

            # If the model asked to call tools:
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                # Add assistant message with tool_calls
                messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})

                # Execute each tool call and add tool results
                for call in tool_calls:
                    fn = (call.get("function") or {})
                    name = fn.get("name")
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}

                    if not name:
                        result = {"ok": False, "error": "Missing tool name."}
                    else:
                        result = tool_handler(name, args if isinstance(args, dict) else {})

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "content": json.dumps(result),
                        }
                    )

                continue

            # Otherwise, we expect model to output JSON in content
            content = msg.get("content") or ""
            try:
                decision = json.loads(content)
            except Exception:
                # Keep minimal: surface raw content for debugging
                decision = {"status": "continue", "plan": "Model returned non-JSON.", "edits": content[:2000]}
            messages.append({"role": "assistant", "content": content})
            return decision, messages

        raise LLMError(f"Exceeded max_tool_round_trips={max_tool_round_trips}")

    def _chat(self, *, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools is not None:
            payload["tools"] = tools

        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(url, headers=headers, json=payload)
                if r.status_code >= 400:
                    raise LLMError(f"LLM HTTP {r.status_code}: {r.text[:2000]}")
                return r.json()
            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                last_err = e
                if attempt >= self.max_retries:
                    raise
                continue
            except httpx.HTTPError as e:
                last_err = e
                if attempt >= self.max_retries:
                    raise
                continue

        # Should never hit, but just in case
        raise LLMError(f"LLM request failed: {type(last_err).__name__}: {last_err}")