"""Built-in tools that the server itself can execute (no external caller needed).

The human worker picks a tool in the Workbench; if it is one of these built-ins,
the backend runs it and appends the result as a tool message, then the same
conversation continues so the worker can reply or call again (multi-round).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# Default command timeout (seconds).
SHELL_TIMEOUT = 60

# Where run_shell commands actually execute. Defaults to the WorkBuddy sandbox
# exposed on this server's loopback via an SSH reverse tunnel (sandbox:8788 ->
# server:127.0.0.1:8788). Override with the EXEC_URL env var.
EXEC_URL = os.environ.get("EXEC_URL", "http://127.0.0.1:8788/exec")
EXEC_TOKEN = os.environ.get("EXEC_TOKEN", "wb-sandbox-humanllm-7f3a9c2e")

BUILTIN_TOOLS: dict[str, dict] = {
    "run_shell": {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Execute a shell command on the server and return stdout/stderr "
                "and the exit code. Use this for anything that needs real execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    }
                },
                "required": ["command"],
            },
        },
    },
}


async def execute_tool_call(call: dict) -> str:
    """Execute one built-in tool call and return its textual result."""
    fn = call.get("function") or {}
    name = fn.get("name", "")
    if name not in BUILTIN_TOOLS:
        return f"Error: unknown tool '{name}'"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except Exception:
        return "Error: tool arguments are not valid JSON"
    if name == "run_shell":
        return await _run_shell_remote(args)
    return f"Error: unknown tool '{name}'"


async def _run_shell_remote(args: dict) -> str:
    """Forward the command to the WorkBuddy sandbox executor over HTTP and
    format the returned stdout/stderr/exit code for the conversation."""
    cmd = args.get("command", "")
    if not cmd or not isinstance(cmd, str):
        return "Error: no command provided"
    body = json.dumps({"command": cmd, "timeout": SHELL_TIMEOUT}).encode("utf-8")
    req = urllib.request.Request(
        EXEC_URL,
        data=body,
        headers={"Content-Type": "application/json", "X-Exec-Token": EXEC_TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=SHELL_TIMEOUT + 10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return f"Error: executor returned HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: cannot reach executor ({EXEC_URL}): {exc}"
    parts = [f"exit_code: {result.get('exit_code')}"]
    if result.get("stdout"):
        parts.append("stdout:\n" + result["stdout"].strip())
    if result.get("stderr"):
        parts.append("stderr:\n" + result["stderr"].strip())
    if not result.get("ok") and not result.get("stdout") and not result.get("stderr"):
        return f"Error: {result.get('error', 'unknown executor error')}"
    return "\n\n".join(parts)


def merge_builtin_tools(tools: list | None) -> list:
    """Ensure every request can use the built-in tools, appended after the
    caller's own tool definitions."""
    tools = [t for t in (tools or []) if isinstance(t, dict)]
    names = {t.get("function", {}).get("name") for t in tools}
    for name, definition in BUILTIN_TOOLS.items():
        if name not in names:
            tools.append(definition)
    return tools
