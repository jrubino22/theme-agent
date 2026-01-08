from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


class MCPError(RuntimeError):
    pass


@dataclass
class MCPClient:
    name: str
    proc: subprocess.Popen

    _id: int = 0
    _lock: threading.Lock = threading.Lock()

    @staticmethod
    def from_cmd(cmd: Optional[str], *, name: str) -> "MCPClient":
        if not cmd:
            raise MCPError("No MCP command provided.")
        # Launch as a shell command string for convenience
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if not proc.stdin or not proc.stdout:
            raise MCPError("Failed to start MCP process with stdio.")
        client = MCPClient(name=name, proc=proc)
        # Initialize session (best-effort)
        client._request("initialize", {"clientInfo": {"name": "theme-agent", "version": "0.2.0"}})
        return client

    def close(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass

    def list_tools(self) -> List[Dict[str, Any]]:
        resp = self._request("tools/list", {})
        tools = resp.get("tools") or []
        return tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._request("tools/call", {"name": tool_name, "arguments": arguments})
        return resp

    def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._id += 1
            req_id = self._id

        req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        line = json.dumps(req)

        if not self.proc.stdin or not self.proc.stdout:
            raise MCPError(f"{self.name} MCP process stdio not available.")

        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()

            # Read a single response line (JSON-RPC)
            resp_line = self.proc.stdout.readline()
            if not resp_line:
                raise MCPError(f"{self.name} MCP server returned no response for method={method}")

            resp = json.loads(resp_line)
            if "error" in resp and resp["error"]:
                raise MCPError(f"{self.name} MCP error: {resp['error']}")
            result = resp.get("result")
            if result is None:
                raise MCPError(f"{self.name} MCP missing result field: {resp}")
            return result
        except json.JSONDecodeError as e:
            raise MCPError(f"{self.name} MCP invalid JSON response: {e}")
        except Exception as e:
            raise MCPError(f"{self.name} MCP request failed: {type(e).__name__}: {e}")
