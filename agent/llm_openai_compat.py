from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: Dict[str, Any]


class LLMError(RuntimeError):
    pass


class OpenAICompatChat:
    """
    Minimal OpenAI-compatible Chat Completions client with tool-calling support.

    Uses: POST {base_url}/chat/completions
    Env wiring is in agent/cli.py (OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL).
    """

    def __init__(self, *, base_url: str, api_key: Optional[str], model: str, temperature: float = 0.2) -> None:
        if not api_key:
            raise SystemExit("OPENAI_API_KEY is required.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    def run_with_tools(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools: List[ToolSpec],
        tool_handler: Callable[[str, Dict[str, Any]], Dict[str, Any]],
        max_tool_round_trips: int = 24,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        tool_payload = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema,
                },
            }
            for t in tools
        ]

        for _ in range(max_tool_round_trips):
            resp = self._chat(messages=messages, tools=tool_payload)
            msg = resp["choices"][0]["message"]

            # Tool calls?
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or "",
                        "tool_calls": tool_calls,
                    }
                )
                for tc in tool_calls:
                    fn = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = {"_raw": raw_args}

                    result = tool_handler(fn, args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result),
                        }
                    )
                continue

            # No tool calls -> final content should be JSON decision
            content = (msg.get("content") or "").strip()
            messages.append({"role": "assistant", "content": content})

            decision = _safe_json_parse(content)
            if not isinstance(decision, dict) or "status" not in decision:
                # If model didn't follow the contract, coerce into a continue
                return {"status": "continue", "notes": content[:2000]}, messages

            return decision, messages

        return {"status": "error", "error": "Exceeded max tool round-trips without producing a decision."}, messages

    def _chat(self, *, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        with httpx.Client(timeout=90) as client:
            r = client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                raise LLMError(f"LLM HTTP {r.status_code}: {r.text[:2000]}")
            return r.json()


def _safe_json_parse(s: str) -> Any:
    try:
        return json.loads(s)
    except Exception:
        # try to salvage JSON blob inside text
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except Exception:
                return None
        return None
