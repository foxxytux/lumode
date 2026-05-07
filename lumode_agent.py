#!/usr/bin/env python3
"""Lumode - a Lumo-powered coding agent for local workspace tasks."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from lumo_cli import Colors, LumoClient, extract_firefox_cookies


DEFAULT_MAX_FILE_BYTES = 80_000
DEFAULT_MAX_COMMAND_BYTES = 80_000
DEFAULT_MAX_TOOL_ROUNDS = 8
DEFAULT_MAX_SEARCH_BYTES = 30_000
DEFAULT_AUTO_COMPACT_CHARS = 120_000
DEFAULT_COMPACT_KEEP_MESSAGES = 8
DEFAULT_COMPACT_SUMMARY_CHARS = 8_000
LUMODE_VERSION = "0.2.0"
SESSION_DIR = Path.home() / ".config" / "lumode" / "sessions"
SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# ── Command metadata for completions ─────────────────────────────────────────
_CMD_META: dict[str, str] = {
    "/help": "Show all commands",
    "/add": "Add file/dir as context",
    "/tree": "Add directory tree",
    "/run": "Run shell command → context",
    "/search": "Web search → context",
    "/fetch": "Fetch URL → context",
    "/context": "List pending context",
    "/apply": "Apply diff from last response",
    "/compact": "Compact history to summary",
    "/auto-compact": "Configure auto-compaction",
    "/status": "Session & context status",
    "/history": "Show chat history",
    "/last": "Show or save last response",
    "/drop": "Drop a context item",
    "/note": "Add text note as context",
    "/prompt": "Show/set system prompt",
    "/read": "Print file (no context)",
    "/ls": "Print directory tree",
    "/sessions": "List saved sessions",
    "/save": "Save session to disk",
    "/load": "Load a saved session",
    "/new": "Start a new session",
    "/rename": "Rename current session",
    "/delete": "Delete a saved session",
    "/export": "Export session as Markdown",
    "/pwd": "Print workspace directory",
    "/cd": "Change workspace directory",
    "/reset": "Reset all session state",
    "/version": "Show Lumode version",
    "/clear": "Clear history & context",
    "/quit": "Exit Lumode",
}

# ── Optional enhanced TUI deps ────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.spinner import Spinner
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme

    _RICH = True
    _console = Console(
        highlight=False,
        theme=Theme({
            "markdown.code": "bold",
            "markdown.h1": "bold cyan",
            "markdown.h2": "bold blue",
            "markdown.h3": "bold",
            "markdown.item.bullet": "cyan",
            "markdown.link": "underline cyan",
        }),
    )
except ImportError:
    _RICH = False
    _console = None  # type: ignore[assignment]

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.patch_stdout import patch_stdout as pt_patch_stdout
    from prompt_toolkit.styles import Style as PTStyle

    _PT = True
except ImportError:
    _PT = False
    from contextlib import contextmanager as _cm

    @_cm
    def pt_patch_stdout(raw: bool = False):  # type: ignore[misc]
        yield


# ── System prompt ─────────────────────────────────────────────────────────────
LUMODE_SYSTEM_PROMPT = """You are Lumode, a pragmatic coding agent powered by Lumo.

You help with real codebases. Lumode provides local tools. Use them when you need
workspace state, file contents, command output, web search, or URL content.

Tool protocol:
- To use a tool, respond only with one or more XML-like tool blocks:
  <lumode_tool>{"name":"tool_name","arguments":{"key":"value"}}</lumode_tool>
- Do not wrap tool calls in markdown.
- After tool results are returned, continue working or give the final answer.
- Use tools proactively when the user asks you to inspect, modify, test, search,
  or verify something.

Available tools:
- read_file: {"path":"relative/or/absolute/path"}
- list_tree: {"path":"optional/path","depth":3}
- run_shell: {"command":"shell command","timeout":60}
- apply_patch: {"patch":"unified diff in diff --git format"}
- web_search: {"query":"search terms","max_results":5}
- fetch_url: {"url":"https://example.com"}

Work style:
- Be concise and direct.
- Prefer small, coherent changes over broad rewrites.
- When code changes are needed, prefer applying a unified diff with apply_patch,
  then run a relevant verification command.
- Do not claim a file was changed unless apply_patch succeeded.
- If more context is needed, call a tool for it.
- Avoid destructive operations and call out risky assumptions.
"""


# ── Prompt-toolkit completer ──────────────────────────────────────────────────
class _CmdCompleter(Completer):
    """Tab-complete slash commands, session names, and file/directory paths."""

    _CMDS = [
        "/help", "/context", "/apply", "/clear", "/quit",
        "/sessions", "/save ", "/load ", "/new ", "/delete ", "/rename ",
        "/export ", "/pwd", "/cd ",
        "/compact", "/auto-compact ", "/status", "/history ", "/last ",
        "/drop ", "/note ", "/prompt ", "/reset", "/read ", "/ls ", "/version",
        "/add ", "/tree ", "/run ", "/search ", "/fetch ",
    ]
    _PATH_PREFIXES = ("/add ", "/tree ", "/cd ", "/export ", "/last ", "/read ", "/ls ")
    _SESSION_PREFIXES = ("/load ", "/delete ", "/rename ")

    def __init__(self, get_sessions=None):
        self._get_sessions = get_sessions or (lambda: [])

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Only complete slash commands — skip normal chat input entirely
        if not text.startswith("/"):
            return

        # Complete bare command names (no space yet)
        if " " not in text:
            for cmd in self._CMDS:
                bare = cmd.strip()
                if bare.startswith(text) and bare != text.strip():
                    yield Completion(
                        bare[len(text):],
                        display=bare,
                        display_meta=_CMD_META.get(bare, ""),
                    )
            return

        # Complete session names after /load, /delete, /rename
        for prefix in self._SESSION_PREFIXES:
            if text.startswith(prefix):
                stem = text[len(prefix):]
                for name in self._get_sessions():
                    if name.startswith(stem):
                        yield Completion(name[len(stem):], display=name, display_meta="saved session")
                return

        # Complete file paths after path-taking commands
        for prefix in self._PATH_PREFIXES:
            if text.startswith(prefix):
                yield from self._path_completions(text[len(prefix):])
                return

    @staticmethod
    def _path_completions(path_str: str):
        try:
            if not path_str or path_str.endswith("/"):
                parent, stem = Path(path_str or "."), ""
            else:
                p = Path(path_str)
                parent, stem = p.parent, p.name

            if not parent.is_dir():
                return

            for item in sorted(parent.iterdir()):
                if item.name.startswith("."):
                    continue
                if stem and not item.name.startswith(stem):
                    continue
                suffix = "/" if item.is_dir() else ""
                yield Completion(
                    item.name[len(stem):] + suffix,
                    display=item.name + suffix,
                )
        except (PermissionError, OSError):
            pass


# ── Data ──────────────────────────────────────────────────────────────────────
@dataclass
class ContextItem:
    label: str
    content: str


# ── Agent core ────────────────────────────────────────────────────────────────
class LumodeAgent:
    """Local coding-agent shell backed by Lumo."""

    def __init__(self, client: LumoClient, cwd: Path, system_prompt: str):
        self.client = client
        self.cwd = cwd.resolve()
        self.system_prompt = system_prompt
        self.history: list[dict[str, str]] = []
        self.context: list[ContextItem] = []
        self.last_response = ""
        self.session_name: Optional[str] = None
        self.auto_compact = True
        self.auto_compact_chars = int(os.getenv("LUMODE_AUTO_COMPACT_CHARS", DEFAULT_AUTO_COMPACT_CHARS))
        self.compact_keep_messages = int(os.getenv("LUMODE_COMPACT_KEEP_MESSAGES", DEFAULT_COMPACT_KEEP_MESSAGES))

    # ── Public context helpers ────────────────────────────────────────────────

    def add_path(self, path_text: str, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> str:
        path = self._safe_path(path_text)
        if not path.exists():
            return f"File not found: {path_text}"
        if path.is_dir():
            return self.add_tree(path_text)
        if not path.is_file():
            return f"Not a regular file: {path_text}"

        data = path.read_bytes()
        truncated = len(data) > max_bytes
        text = data[:max_bytes].decode("utf-8", errors="replace")
        if truncated:
            text += f"\n\n[truncated at {max_bytes} bytes]"

        rel = self._display_path(path)
        self.context.append(ContextItem(f"file: {rel}", text))
        return f"Added {rel} ({len(text)} chars)"

    def add_tree(self, path_text: str = ".", max_depth: int = 3) -> str:
        path = self._safe_path(path_text)
        if not path.is_dir():
            return f"Not a directory: {path_text}"
        tree = self._tree(path, max_depth=max_depth)
        rel = self._display_path(path)
        self.context.append(ContextItem(f"tree: {rel}", tree))
        return f"Added tree for {rel}"

    def add_command_output(self, command: str) -> str:
        output = self.run_command(command)
        self.context.append(ContextItem(f"command: {command}", output))
        return "Added command output"

    def change_cwd(self, path_text: str) -> str:
        path = self._safe_path(path_text)
        if not path.is_dir():
            return f"Not a directory: {path_text}"
        self.cwd = path
        return f"Changed cwd to {self.cwd}"

    def run_command(self, command: str, timeout: int = 60) -> str:
        try:
            result = subprocess.run(
                command, shell=True, cwd=self.cwd,
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s: {command}"
        except Exception as exc:
            return f"Command failed to start: {exc}"

        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        output += f"\n[exit code: {result.returncode}]"
        if len(output) > DEFAULT_MAX_COMMAND_BYTES:
            output = output[:DEFAULT_MAX_COMMAND_BYTES] + "\n[truncated]"
        return output

    # ── Main ask loop ─────────────────────────────────────────────────────────

    def ask(self, message: str, debug: bool = False) -> str:
        full_message = self._build_message(message)
        self.history.append({"Role": "user", "Content": full_message})
        compact_msg = self.maybe_auto_compact()
        if compact_msg:
            _print_info(compact_msg)

        for round_num in range(DEFAULT_MAX_TOOL_ROUNDS):
            msg_text, native_calls = self._stream_and_capture(streaming=(round_num == 0))

            if debug:
                _dbg(
                    f"[round {round_num + 1}] msg={len(msg_text)}ch "
                    f"native_calls={[c.get('name') for c in native_calls]}\n"
                    + msg_text[:500]
                )

            # Legacy XML tool calls embedded in the message (kept for robustness)
            xml_calls = extract_tool_calls(msg_text)
            if xml_calls:
                self.history.append({"Role": "assistant", "Content": msg_text})
                results = [self._run_tool_with_display(tc, debug=debug) for tc in xml_calls]
                self.history.append({"Role": "user", "Content": format_tool_results(results)})
                continue

            # Lumo native tool calls — execute them locally and feed results back
            if native_calls:
                self.history.append({"Role": "assistant", "Content": msg_text})
                parts = ["Tool execution results (ran locally on the workspace machine):"]
                for call in native_calls:
                    result = self._run_tool_with_display(
                        {"name": call.get("name"), "arguments": call.get("arguments", {})},
                        debug=debug,
                    )
                    status = "success" if result.get("ok") else "error"
                    parts.append(
                        f"\n[Tool: {call.get('name')} | {status}]\n{result.get('result', '')}"
                    )
                self.history.append({"Role": "user", "Content": "\n".join(parts)})
                continue

            # No tool calls — this is the final answer
            self._render_response(msg_text)
            self.history.append({"Role": "assistant", "Content": msg_text})
            self.last_response = msg_text
            self.context = []
            if self.session_name:
                self.save_session(self.session_name)
            return msg_text

        raise RuntimeError(f"Tool loop exceeded {DEFAULT_MAX_TOOL_ROUNDS} rounds.")

    def _stream_and_capture(self, streaming: bool = True) -> tuple[str, list[dict]]:
        """Stream one model response turn; return (message_text, native_tool_calls).

        Captures Lumo's native tool_call/tool_result SSE events so we can execute
        them locally instead of relying on Lumo's server-side execution (which
        fails for our custom tools).  Display: live scrolling text on the first
        round, plain spinner on tool follow-up rounds.
        """
        message_text = ""
        native_calls: list[dict] = []
        current_call: dict = {}
        last_update = 0.0
        got_any = False

        def _iter():
            """Process events; yield True on each message token (for live update trigger)."""
            nonlocal message_text, native_calls, current_call, got_any
            for event in self.client.stream_events(self.history, system_prompt=self.system_prompt):
                etype = event.get("type")
                if etype == "done":
                    break
                if etype == "error":
                    raise RuntimeError(f"API error: {event.get('message', 'Unknown')}")
                if etype != "token_data":
                    continue

                target = event.get("target", "message")
                content = event.get("content", "")

                if target == "message" and content:
                    message_text += content
                    got_any = True
                    yield  # signal: time to update the live display

                elif target == "tool_call" and content:
                    try:
                        data = json.loads(content)
                        # Each tool_call event is an incremental JSON snapshot;
                        # the latest one with a "name" key has the full payload.
                        if isinstance(data, dict) and data.get("name"):
                            current_call = data
                    except json.JSONDecodeError:
                        pass

                elif target == "tool_result":
                    # Server tried (and failed) to run the tool — save it for local exec
                    if current_call.get("name"):
                        native_calls.append(dict(current_call))
                        got_any = True
                    current_call = {}

        in_bg = threading.current_thread() is not threading.main_thread()
        if in_bg:
            # Running in background queue thread — avoid cursor tricks that
            # would corrupt the prompt_toolkit queue input below.
            for _ in _iter():
                pass
        elif _RICH and streaming:
            with Live(
                Spinner("dots", " [dim]Thinking…[/dim]"),
                console=_console,
                refresh_per_second=12,
                transient=True,
            ) as live:
                for _ in _iter():
                    now = time.monotonic()
                    if now - last_update >= 0.08:
                        live.update(Text(message_text + "▌", style="dim"))
                        last_update = now
                live.update("")  # blank before transient clear
        elif _RICH:
            with _console.status("[dim]Thinking…[/dim]", spinner="dots"):
                for _ in _iter():
                    pass
        else:
            for _ in _iter():
                pass

        if not got_any:
            raise RuntimeError("No response from Lumo. Run with --debug to inspect SSE events.")

        return message_text.strip(), native_calls

    def _render_response(self, text: str) -> None:
        """Render the final model response; use Markdown when rich is available."""
        if _RICH:
            _console.print()
            _console.print(Markdown(text))
            _console.print()
        else:
            print(text)

    def _run_tool_with_display(self, tool_call: dict, debug: bool = False) -> dict:
        """Execute a tool call and show a styled status indicator."""
        name = tool_call.get("name", "unknown")
        if _RICH:
            with _console.status(
                f"[dim]⚙  [bold]{name}[/bold][/dim]", spinner="dots"
            ):
                result = self.execute_tool_call(tool_call)
            ok = result.get("ok")
            icon, style = ("✓", "green") if ok else ("✗", "red")
            _console.print(f"  [{style}]{icon}[/{style}] [dim]{name}[/dim]")
        else:
            result = self.execute_tool_call(tool_call)
            status = "ok" if result.get("ok") else "error"
            print(f"{Colors.DIM}[tool:{name} {status}]{Colors.RESET}", file=sys.stderr)
        if debug:
            _dbg(f"{name} result: {str(result.get('result', ''))[:500]}")
        return result

    # ── Tool implementations ──────────────────────────────────────────────────

    def execute_tool_call(self, tool_call: dict) -> dict:
        name = tool_call.get("name")
        args = tool_call.get("arguments") or {}
        if not isinstance(args, dict):
            return {"name": name, "ok": False, "result": "Tool arguments must be a JSON object."}
        try:
            if name == "read_file":
                result = self.read_file_tool(str(args.get("path", "")))
            elif name == "list_tree":
                result = self.list_tree_tool(str(args.get("path", ".")), int(args.get("depth", 3)))
            elif name == "run_shell":
                result = self.run_command(str(args.get("command", "")), int(args.get("timeout", 60)))
            elif name == "apply_patch":
                result = self.apply_patch_tool(str(args.get("patch", "")))
            elif name == "web_search":
                result = web_search(str(args.get("query", "")), int(args.get("max_results", 5)))
            elif name == "fetch_url":
                result = fetch_url(str(args.get("url", "")))
            else:
                return {"name": name, "ok": False, "result": f"Unknown tool: {name}"}
            return {"name": name, "ok": True, "result": result}
        except Exception as exc:
            return {"name": name, "ok": False, "result": str(exc)}

    def read_file_tool(self, path_text: str, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> str:
        path = self._safe_path(path_text)
        if not path.exists():
            return f"File not found: {path_text}"
        if not path.is_file():
            return f"Not a regular file: {path_text}"
        data = path.read_bytes()
        truncated = len(data) > max_bytes
        text = data[:max_bytes].decode("utf-8", errors="replace")
        if truncated:
            text += f"\n\n[truncated at {max_bytes} bytes]"
        return f"File: {self._display_path(path)}\n----- BEGIN FILE CONTENTS -----\n{text}\n----- END FILE CONTENTS -----"

    def list_tree_tool(self, path_text: str = ".", depth: int = 3) -> str:
        path = self._safe_path(path_text)
        if not path.is_dir():
            return f"Not a directory: {path_text}"
        return f"Tree: {self._display_path(path)}\n{self._tree(path, max_depth=depth)}"

    def apply_patch_tool(self, patch: str) -> str:
        patch = patch.strip() + "\n"
        if not patch.strip():
            return "No patch provided."
        check = subprocess.run(
            ["git", "apply", "--check", "-"], input=patch, text=True,
            cwd=self.cwd, capture_output=True,
        )
        if check.returncode != 0:
            return "Patch check failed:\n" + (check.stderr or check.stdout)
        apply = subprocess.run(
            ["git", "apply", "-"], input=patch, text=True,
            cwd=self.cwd, capture_output=True,
        )
        if apply.returncode != 0:
            return "Patch apply failed:\n" + (apply.stderr or apply.stdout)
        return "Patch applied."

    def apply_last_patch(self) -> str:
        if not self.last_response.strip():
            return "No Lumo response available to apply."
        patch = extract_unified_diff(self.last_response)
        if not patch:
            return "No unified diff found in the last response."
        check = subprocess.run(
            ["git", "apply", "--check", "-"], input=patch, text=True,
            cwd=self.cwd, capture_output=True,
        )
        if check.returncode != 0:
            return "Patch check failed:\n" + (check.stderr or check.stdout)
        apply = subprocess.run(
            ["git", "apply", "-"], input=patch, text=True,
            cwd=self.cwd, capture_output=True,
        )
        if apply.returncode != 0:
            return "Patch apply failed:\n" + (apply.stderr or apply.stdout)
        return "Patch applied."

    def clear(self) -> None:
        self.history = []
        self.context = []
        self.last_response = ""

    def reset_all(self) -> str:
        self.clear()
        self.session_name = None
        self.system_prompt = LUMODE_SYSTEM_PROMPT
        self.auto_compact = True
        self.auto_compact_chars = DEFAULT_AUTO_COMPACT_CHARS
        self.compact_keep_messages = DEFAULT_COMPACT_KEEP_MESSAGES
        return "Reset session, prompt, context, and compaction settings."

    def new_session(self, name: Optional[str] = None) -> str:
        self.clear()
        self.session_name = self._validate_session_name(name) if name else None
        if self.session_name:
            self.save_session(self.session_name)
            return f"Started session: {self.session_name}"
        return "Started a new unsaved session."

    def save_session(self, name: Optional[str] = None) -> str:
        session_name = self._validate_session_name(name or self.session_name)
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        path = self._session_path(session_name)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        created_at = now
        if path.exists():
            try:
                created_at = json.loads(path.read_text(encoding="utf-8")).get("created_at", now)
            except (OSError, json.JSONDecodeError):
                created_at = now
        payload = {
            "name": session_name,
            "created_at": created_at,
            "updated_at": now,
            "cwd": str(self.cwd),
            "history": self.history,
            "context": [item.__dict__ for item in self.context],
            "last_response": self.last_response,
            "system_prompt": self.system_prompt,
            "settings": {
                "auto_compact": self.auto_compact,
                "auto_compact_chars": self.auto_compact_chars,
                "compact_keep_messages": self.compact_keep_messages,
            },
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.session_name = session_name
        return f"Saved session: {session_name}"

    def load_session(self, name: str) -> str:
        session_name = self._validate_session_name(name)
        path = self._session_path(session_name)
        if not path.exists():
            return f"Session not found: {session_name}"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.session_name = session_name
        self.cwd = Path(data.get("cwd") or self.cwd).expanduser().resolve()
        self.history = [
            {"Role": str(item.get("Role", item.get("role", "user"))), "Content": str(item.get("Content", item.get("content", "")))}
            for item in data.get("history", [])
            if isinstance(item, dict)
        ]
        self.context = [
            ContextItem(str(item.get("label", "context")), str(item.get("content", "")))
            for item in data.get("context", [])
            if isinstance(item, dict)
        ]
        self.last_response = str(data.get("last_response", ""))
        self.system_prompt = str(data.get("system_prompt") or self.system_prompt)
        settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        self.auto_compact = bool(settings.get("auto_compact", self.auto_compact))
        self.auto_compact_chars = int(settings.get("auto_compact_chars", self.auto_compact_chars))
        self.compact_keep_messages = int(settings.get("compact_keep_messages", self.compact_keep_messages))
        return f"Loaded session: {session_name}"

    def delete_session(self, name: str) -> str:
        session_name = self._validate_session_name(name)
        path = self._session_path(session_name)
        if not path.exists():
            return f"Session not found: {session_name}"
        path.unlink()
        if self.session_name == session_name:
            self.session_name = None
        return f"Deleted session: {session_name}"

    def rename_session(self, new_name: str) -> str:
        if not self.session_name:
            return "No active saved session. Use /save <name> first."
        old_name = self.session_name
        new_session_name = self._validate_session_name(new_name)
        old_path = self._session_path(old_name)
        new_path = self._session_path(new_session_name)
        if new_path.exists():
            return f"Session already exists: {new_session_name}"
        if old_path.exists():
            old_path.rename(new_path)
        self.session_name = new_session_name
        self.save_session(new_session_name)
        return f"Renamed session: {old_name} -> {new_session_name}"

    def list_sessions(self) -> list[dict[str, str]]:
        if not SESSION_DIR.exists():
            return []
        sessions = []
        for path in sorted(SESSION_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            sessions.append({
                "name": str(data.get("name") or path.stem),
                "updated_at": str(data.get("updated_at") or ""),
                "cwd": str(data.get("cwd") or ""),
            })
        return sorted(sessions, key=lambda item: item["updated_at"], reverse=True)

    def export_session(self, path_text: Optional[str] = None) -> str:
        if path_text:
            path = self._safe_path(path_text)
        else:
            name = self.session_name or "lumode-session"
            path = self.cwd / f"{name}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._session_markdown(), encoding="utf-8")
        return f"Exported session to {path}"

    def context_status(self) -> str:
        if not self.context:
            return "No pending context."
        lines = ["Pending context:"]
        for index, item in enumerate(self.context, start=1):
            lines.append(f"  {index}. {item.label} ({len(item.content)} chars)")
        return "\n".join(lines)

    def status(self) -> str:
        session = self.session_name or "(unsaved)"
        return "\n".join([
            f"Session: {session}",
            f"cwd: {self.cwd}",
            f"History: {len(self.history)} messages, {self.history_chars()} chars",
            f"Pending context: {len(self.context)} items, {sum(len(i.content) for i in self.context)} chars",
            f"Last response: {len(self.last_response)} chars",
            (
                "Auto compact: "
                f"{'on' if self.auto_compact else 'off'} "
                f"(threshold {self.auto_compact_chars} chars, keep {self.compact_keep_messages} messages)"
            ),
        ])

    def history_status(self, limit: int = 20) -> str:
        if not self.history:
            return "No chat history."
        rows = []
        start = max(0, len(self.history) - limit)
        for index, item in enumerate(self.history[start:], start=start + 1):
            role = item.get("Role", item.get("role", "unknown"))
            content = str(item.get("Content", item.get("content", ""))).strip().replace("\n", " ")
            if len(content) > 100:
                content = content[:97] + "..."
            rows.append(f"{index:>3}. {role:<9} {len(str(item.get('Content', ''))):>6} chars  {content}")
        return "\n".join(rows)

    def drop_context(self, target: str) -> str:
        if target == "all":
            count = len(self.context)
            self.context = []
            return f"Dropped {count} context items."
        try:
            index = int(target) - 1
        except ValueError:
            return "Usage: /drop <index|all>"
        if index < 0 or index >= len(self.context):
            return f"Context item not found: {target}"
        item = self.context.pop(index)
        return f"Dropped context: {item.label}"

    def add_note(self, text: str) -> str:
        if not text.strip():
            return "Usage: /note <text>"
        self.context.append(ContextItem("note", text.strip()))
        return "Added note as context."

    def write_last_response(self, path_text: str) -> str:
        if not self.last_response:
            return "No last response to write."
        path = self._safe_path(path_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.last_response.rstrip() + "\n", encoding="utf-8")
        return f"Wrote last response to {path}"

    def set_system_prompt(self, prompt: str) -> str:
        if not prompt.strip():
            return self.system_prompt
        self.system_prompt = prompt.strip()
        return "Updated system prompt."

    def configure_auto_compact(self, command: str) -> str:
        parts = shlex.split(command)
        if not parts or parts[0] == "status":
            return (
                f"Auto compact is {'on' if self.auto_compact else 'off'}; "
                f"threshold={self.auto_compact_chars}; keep={self.compact_keep_messages}"
            )
        action = parts[0]
        if action in {"on", "off"}:
            self.auto_compact = action == "on"
            parts = parts[1:]
        if parts:
            self.auto_compact_chars = max(10_000, int(parts[0]))
        if len(parts) > 1:
            self.compact_keep_messages = max(2, int(parts[1]))
        return (
            f"Auto compact {'enabled' if self.auto_compact else 'disabled'} "
            f"(threshold {self.auto_compact_chars} chars, keep {self.compact_keep_messages} messages)."
        )

    def history_chars(self) -> int:
        return sum(len(str(item.get("Content", item.get("content", "")))) for item in self.history)

    def maybe_auto_compact(self) -> Optional[str]:
        if not self.auto_compact or self.history_chars() <= self.auto_compact_chars:
            return None
        return self.compact_history(
            keep_messages=self.compact_keep_messages,
            reason=f"auto compact at {self.history_chars()} chars",
        )

    def compact_history(
        self,
        keep_messages: Optional[int] = None,
        max_summary_chars: int = DEFAULT_COMPACT_SUMMARY_CHARS,
        reason: str = "manual compact",
    ) -> str:
        keep = max(2, keep_messages or self.compact_keep_messages)
        if len(self.history) <= keep:
            return "Nothing to compact."

        old = self.history[:-keep]
        recent = self.history[-keep:]
        before = self.history_chars()
        summary = self._summarize_history(old, max_summary_chars=max_summary_chars)
        self.history = [{
            "Role": "system",
            "Content": (
                f"Lumode conversation compacted ({reason}). "
                "Older turns are summarized below; preserve these facts when continuing.\n\n"
                + summary
            ),
        }] + recent
        after = self.history_chars()
        if self.session_name:
            self.save_session(self.session_name)
        return f"Compacted history: {before} -> {after} chars; kept {len(recent)} recent messages."

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_message(self, message: str) -> str:
        if not self.context:
            return message
        parts = ["Workspace context follows. Use it as current local context."]
        for item in self.context:
            parts.append(f"\n=== {item.label} ===\n```text\n{item.content}\n```")
        parts.append(f"\n=== user request ===\n{message}")
        return "\n".join(parts)

    def _safe_path(self, path_text: str) -> Path:
        path = Path(path_text).expanduser()
        if not path.is_absolute():
            path = self.cwd / path
        return path.resolve()

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.cwd))
        except ValueError:
            return str(path)

    @staticmethod
    def _validate_session_name(name: Optional[str]) -> str:
        if not name:
            raise ValueError("Session name required.")
        if not SESSION_NAME_RE.match(name):
            raise ValueError("Session names can use letters, numbers, dots, dashes, and underscores.")
        return name

    @staticmethod
    def _session_path(name: str) -> Path:
        return SESSION_DIR / f"{name}.json"

    def _session_markdown(self) -> str:
        title = self.session_name or "unsaved"
        lines = [
            f"# Lumode Session: {title}",
            "",
            f"- cwd: `{self.cwd}`",
            f"- exported: `{dt.datetime.now(dt.timezone.utc).isoformat()}`",
            "",
        ]
        for item in self.history:
            role = item.get("Role", item.get("role", "unknown"))
            content = item.get("Content", item.get("content", ""))
            lines.extend([f"## {role}", "", str(content).strip(), ""])
        if self.context:
            lines.extend(["## Pending Context", ""])
            for item in self.context:
                lines.extend([f"### {item.label}", "", "```text", item.content, "```", ""])
        return "\n".join(lines).rstrip() + "\n"

    def _summarize_history(self, items: list[dict[str, str]], max_summary_chars: int) -> str:
        lines = [
            f"Summary generated locally at {dt.datetime.now(dt.timezone.utc).isoformat()}.",
            f"Compacted {len(items)} older messages.",
            "",
        ]
        for index, item in enumerate(items, start=1):
            role = item.get("Role", item.get("role", "unknown"))
            content = str(item.get("Content", item.get("content", ""))).strip()
            content = re.sub(r"\n{3,}", "\n\n", content)
            if len(content) > 700:
                content = content[:700].rstrip() + "\n[message truncated in compacted summary]"
            lines.extend([f"Turn {index} ({role}, {len(content)} chars):", content, ""])
            if len("\n".join(lines)) >= max_summary_chars:
                lines.append("[summary truncated]")
                break
        return "\n".join(lines).strip()

    def _tree(self, path: Path, max_depth: int, depth: int = 0, prefix: str = "") -> str:
        if depth > max_depth:
            return ""
        ignored = {
            ".git", ".hg", ".svn", "__pycache__", ".pytest_cache",
            ".mypy_cache", "node_modules", "dist", "build", ".venv", "venv",
        }
        lines: list[str] = []
        try:
            items = sorted(path.iterdir(), key=lambda i: (not i.is_dir(), i.name.lower()))
        except PermissionError:
            return prefix + "[permission denied]"
        visible = [i for i in items if i.name not in ignored and not i.name.startswith(".")]
        for index, item in enumerate(visible):
            last = index == len(visible) - 1
            connector = "`-- " if last else "|-- "
            child_prefix = "    " if last else "|   "
            if item.is_dir():
                lines.append(f"{prefix}{connector}{item.name}/")
                if depth < max_depth:
                    child_tree = self._tree(item, max_depth, depth + 1, prefix + child_prefix)
                    if child_tree:
                        lines.append(child_tree)
            else:
                lines.append(f"{prefix}{connector}{item.name}")
        return "\n".join(lines)


# ── Utility functions ─────────────────────────────────────────────────────────

def extract_unified_diff(text: str) -> str:
    fenced_blocks = re.findall(r"```(?:diff|patch)?\n(.*?)```", text, flags=re.DOTALL)
    candidates = fenced_blocks if fenced_blocks else [text]
    patches: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if "diff --git " in candidate or re.search(r"^--- .+\n\+\+\+ .+", candidate, re.MULTILINE):
            start = candidate.find("diff --git ")
            patches.append(candidate[start:] if start >= 0 else candidate)
    return "\n".join(patches).strip() + ("\n" if patches else "")


def extract_tool_calls(text: str) -> list[dict]:
    calls = []
    for match in re.finditer(r"<lumode_tool>\s*(\{.*?\})\s*</lumode_tool>", text, flags=re.DOTALL):
        try:
            call = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(call, dict):
            calls.append(call)
    return calls


def format_tool_results(results: list[dict]) -> str:
    blocks = ["Lumode tool results:"]
    for index, result in enumerate(results, start=1):
        status = "ok" if result.get("ok") else "error"
        blocks.append(
            f"\n<lumode_tool_result index=\"{index}\" name=\"{result.get('name')}\" status=\"{status}\">\n"
            f"{result.get('result', '')}\n"
            "</lumode_tool_result>"
        )
    return "\n".join(blocks)


def web_search(query: str, max_results: int = 5) -> str:
    if not query.strip():
        return "No search query provided."
    max_results = max(1, min(max_results, 10))
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    response = requests.get(url, headers={"User-Agent": "Lumode/1.0"}, timeout=20)
    response.raise_for_status()
    results = []
    pattern = re.compile(
        r'<a rel="nofollow" class="result__a" href="(?P<href>.*?)".*?>(?P<title>.*?)</a>.*?'
        r'<a class="result__snippet".*?>(?P<snippet>.*?)</a>',
        flags=re.DOTALL,
    )
    for match in pattern.finditer(response.text):
        href = html.unescape(strip_tags(match.group("href")))
        title = html.unescape(strip_tags(match.group("title")))
        snippet = html.unescape(strip_tags(match.group("snippet")))
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            href = qs["uddg"][0]
        results.append(f"{len(results) + 1}. {title}\nURL: {href}\nSnippet: {snippet}")
        if len(results) >= max_results:
            break
    return "\n\n".join(results) if results else "No search results parsed."


def fetch_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "Only http:// and https:// URLs are supported."
    response = requests.get(url, headers={"User-Agent": "Lumode/1.0"}, timeout=20)
    response.raise_for_status()
    text = response.text
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", "", text)
    text = strip_tags(text)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    if len(text) > DEFAULT_MAX_SEARCH_BYTES:
        text = text[:DEFAULT_MAX_SEARCH_BYTES] + "\n[truncated]"
    return f"URL: {url}\n{text}"


def strip_tags(value: str) -> str:
    return re.sub(r"(?s)<.*?>", "", value)


# ── TUI helpers ───────────────────────────────────────────────────────────────

def print_help() -> None:
    if _RICH:
        table = Table(show_header=False, box=None, padding=(0, 2), show_edge=False)
        table.add_column("cmd", style="cyan bold", no_wrap=True)
        table.add_column("desc", style="")
        rows = [
            ("/help", "Show this help"),
            ("/add <path>", "Add file or directory tree as context"),
            ("/tree [path] [depth]", "Add directory tree context"),
            ("/run <command>", "Run shell command and add output as context"),
            ("/search <query>", "Web search — add results as context"),
            ("/fetch <url>", "Fetch URL text as context"),
            ("/context", "Show pending context items"),
            ("/apply", "Apply unified diff from last response"),
            ("/compact [keep]", "Compact older chat history into a summary"),
            ("/auto-compact [on|off|status] [chars] [keep]", "Configure automatic history compaction"),
            ("/status", "Show session, context, and compaction status"),
            ("/history [n]", "Show recent chat history metadata"),
            ("/last [path]", "Show or write the last response"),
            ("/drop <index|all>", "Drop pending context"),
            ("/note <text>", "Add a note as context"),
            ("/prompt [text]", "Show or replace the system prompt"),
            ("/read <path>", "Print a file without adding context"),
            ("/ls [path] [depth]", "Print a directory tree without adding context"),
            ("/sessions", "List saved sessions"),
            ("/save [name]", "Save the current chat session"),
            ("/load <name>", "Load a saved chat session"),
            ("/new [name]", "Start a blank session"),
            ("/rename <name>", "Rename the active saved session"),
            ("/delete <name>", "Delete a saved session"),
            ("/export [path]", "Export the session transcript as Markdown"),
            ("/pwd", "Show current workspace directory"),
            ("/cd <path>", "Change workspace directory"),
            ("/reset", "Reset active session state and settings"),
            ("/version", "Show Lumode version"),
            ("/clear", "Clear chat history and pending context"),
            ("/quit", "Exit"),
        ]
        for cmd, desc in rows:
            table.add_row(cmd, desc)
        _console.print(Panel(table, title="[bold]Commands[/bold]", border_style="dim", padding=(1, 2)))
    else:
        print("""Commands:
  /help                 Show this help
  /add <path>           Add a file or directory tree as context
  /tree [path] [depth]  Add directory tree context
  /run <command>        Run command and add output as context
  /search <query>       Search the web and add results as context
  /fetch <url>          Fetch URL text and add it as context
  /context              Show pending context
  /apply                Apply unified diff from the last Lumo response
  /compact [keep]       Compact older chat history into a summary
  /auto-compact ...     Configure automatic compaction
  /status               Show session, context, and compaction status
  /history [n]          Show recent chat history metadata
  /last [path]          Show or write the last response
  /drop <index|all>     Drop pending context
  /note <text>          Add a note as context
  /prompt [text]        Show or replace the system prompt
  /read <path>          Print a file without adding context
  /ls [path] [depth]    Print a directory tree without adding context
  /sessions             List saved sessions
  /save [name]          Save the current chat session
  /load <name>          Load a saved chat session
  /new [name]           Start a blank session
  /rename <name>        Rename the active saved session
  /delete <name>        Delete a saved session
  /export [path]        Export the session transcript as Markdown
  /pwd                  Show current workspace directory
  /cd <path>            Change workspace directory
  /reset                Reset active session state and settings
  /version              Show Lumode version
  /clear                Clear chat history and pending context
  /quit                 Exit

Examples:
  /tree . 2
  /add src/app.py
  /run pytest -q
  /status
  /compact 8
  /auto-compact on 120000 8
  /save bugfix-notes
  /load bugfix-notes
  /search latest Python release
  Fix the failing test and return a diff.
  /apply
""")


def _dbg(msg: str) -> None:
    """Print a debug line (always to stderr so it doesn't corrupt piped output)."""
    if _RICH:
        _console.print(f"[dim magenta][debug] {msg}[/dim magenta]", highlight=False)
    else:
        print(f"[debug] {msg}", file=sys.stderr)


def _print_info(msg: str) -> None:
    if _RICH:
        _console.print(f"[dim]{msg}[/dim]")
    else:
        print(msg)


def _print_ok(msg: str) -> None:
    if _RICH:
        _console.print(f"[green]✓[/green] [dim]{msg}[/dim]")
    else:
        print(msg)


def _print_error(msg: str) -> None:
    if _RICH:
        _console.print(Panel(msg, title="[bold red]Error[/bold red]", border_style="red"))
    else:
        print(f"{Colors.RED}Error: {msg}{Colors.RESET}")


def _print_sessions(agent: LumodeAgent) -> None:
    sessions = agent.list_sessions()
    if not sessions:
        _print_info("No saved sessions.")
        return
    if _RICH:
        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
        table.add_column("Name", no_wrap=True)
        table.add_column("Updated", no_wrap=True)
        table.add_column("Workspace")
        for item in sessions:
            marker = " *" if item["name"] == agent.session_name else ""
            table.add_row(item["name"] + marker, item["updated_at"], item["cwd"])
        _console.print(Panel(table, title="[bold]Sessions[/bold]", border_style="dim", padding=(1, 2)))
    else:
        print("Sessions:")
        for item in sessions:
            marker = " *" if item["name"] == agent.session_name else ""
            print(f"  {item['name']}{marker}\t{item['updated_at']}\t{item['cwd']}")


def _get_git_branch(cwd: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            return branch if branch and branch != "HEAD" else None
    except Exception:
        pass
    return None


def _print_status(agent: LumodeAgent) -> None:
    if not _RICH:
        _print_info(agent.status())
        return
    table = Table(show_header=False, box=None, padding=(0, 2), show_edge=False)
    table.add_column("key", style="dim", no_wrap=True)
    table.add_column("val", style="bold")
    chars = agent.history_chars()
    ctx_chars = sum(len(i.content) for i in agent.context)
    table.add_row("Session", agent.session_name or "[dim](unsaved)[/dim]")
    table.add_row("Directory", str(agent.cwd))
    branch = _get_git_branch(agent.cwd)
    if branch:
        table.add_row("Git branch", f"[cyan]{branch}[/cyan]")
    table.add_row("History", f"{len(agent.history)} messages · {chars:,} chars")
    table.add_row("Context", f"{len(agent.context)} pending items · {ctx_chars:,} chars")
    table.add_row("Last response", f"{len(agent.last_response):,} chars")
    ac = "on" if agent.auto_compact else "off"
    table.add_row(
        "Auto-compact",
        f"[green]{ac}[/green] · threshold {agent.auto_compact_chars:,} · keep {agent.compact_keep_messages}",
    )
    _console.print(Panel(table, title="[bold]Status[/bold]", border_style="dim", padding=(1, 2)))


def _print_welcome(agent: LumodeAgent) -> None:
    if not _RICH:
        print(f"Lumode v{LUMODE_VERSION}  Lumo-powered coding agent")
        print(f"cwd: {agent.cwd}")
        print("Type /help for commands.\n")
        return

    # ── Lumo cat ASCII art ────────────────────────────────────────────────────
    # Based on the Lumo mascot reference: seated purple cat, tall ears, huge
    # white eyes, small collar badge, compact front legs, and curled tail.
    P  = "#7c3aed"   # Lumo purple
    LP = "#8b5cf6"   # highlight purple
    DP = "#4c1d95"   # darker purple (outline / shadow)
    B  = "#f59e0b"   # orange coin

    left = Text()

    def la(s, st=P):
        left.append(s, style=st)

    la("      /\\_/\\\n", LP)
    la("   __/     \\__\n", LP)
    la("  /  ")
    la("◉", "white bold")
    la("   ")
    la("◉", "white bold")
    la("  \\\n", LP)
    la(" |     ")
    la("▾", "#d8b4fe")
    la("     |\n", LP)
    la("  \\    ")
    la("●", B)
    la("    /\n", P)
    la("   /|       |\\\n", P)
    la("  / |       | \\___\n", P)
    la(" |  |       |     `\\\n", P)
    la(" |  |       |  /\\   |\n", P)
    la(" |  |_______| |  |  |\n", DP)
    la("  \\_________/ /  / /\n", DP)
    la("    ||   ||  /__/ /\n", DP)
    la("    ()   ()  `---'\n", DP)

    # ── Identity ──────────────────────────────────────────────────────────────
    cwd_str = str(agent.cwd)
    if len(cwd_str) > 32:
        cwd_str = "…" + cwd_str[-31:]
    branch = _get_git_branch(agent.cwd)
    session_name = agent.session_name or "(unsaved)"

    la("\n")
    la("  Lumo-powered coding agent\n", "dim")
    la(f"  v{LUMODE_VERSION}\n\n", "bold")
    la(f"  {cwd_str}\n", "dim")
    if branch:
        la(f"  branch: {branch}\n", f"{P} dim")
    la(f"  session: {session_name}\n", "dim")

    # ── Right column: commands + keys ─────────────────────────────────────────
    right = Table.grid(padding=(0, 2))
    right.add_column(style="cyan", no_wrap=True, width=14)
    right.add_column(style="dim")

    right.add_row(Text("Commands", style="bold"), Text(""))
    right.add_row(Text("─" * 13, style="dim"), Text("─" * 24, style="dim"))
    for cmd, desc in [
        ("/add <path>", "Add file/dir as context"),
        ("/tree", "Add directory tree"),
        ("/run <cmd>", "Run shell → context"),
        ("/search <q>", "Web search → context"),
        ("/compact", "Compact history"),
        ("/help", "All commands"),
    ]:
        right.add_row(cmd, desc)

    right.add_row("", "")
    right.add_row(Text("Keys", style="bold"), Text(""))
    right.add_row(Text("─" * 13, style="dim"), Text("─" * 24, style="dim"))
    for key, desc in [
        ("Tab", "Complete slash commands"),
        ("Alt+Enter", "Insert newline"),
        ("↑↓", "Browse history"),
        ("Ctrl-D", "Exit"),
    ]:
        right.add_row(Text(key, style="cyan"), Text(desc, style="dim"))

    # ── Two-column panel ──────────────────────────────────────────────────────
    grid = Table.grid(padding=(0, 4))
    grid.add_column(width=34)
    grid.add_column()
    grid.add_row(left, right)

    _console.print()
    _console.print(Panel(
        grid,
        title=f"[bold #8b5cf6]Lumode[/bold #8b5cf6] [dim]v{LUMODE_VERSION}[/dim]",
        border_style="#8b5cf6",
        padding=(1, 2),
    ))
    _console.print()


# ── Interactive REPL ──────────────────────────────────────────────────────────

def _make_session(
    agent: "LumodeAgent",
    ai_thinking: "Optional[threading.Event]" = None,
) -> "Optional[PromptSession]":
    """Build a prompt_toolkit PromptSession with history, completion, and status toolbar."""
    if not _PT:
        return None
    history_dir = Path.home() / ".config" / "lumode"
    history_dir.mkdir(parents=True, exist_ok=True)

    kb = KeyBindings()

    @kb.add("c-d")
    def _exit(event):
        event.app.exit(exception=EOFError)

    @kb.add("escape", "enter")
    def _insert_newline(event):
        event.current_buffer.insert_text("\n")

    def _toolbar():
        try:
            name = agent.session_name or "unsaved"
            ctx = len(agent.context)
            hist = len(agent.history)
            chars = agent.history_chars()
            chars_str = f"{chars // 1000}k" if chars >= 1000 else str(chars)
            ctx_part = f"  ctx:<b>{ctx}</b>" if ctx else ""
            if ai_thinking and ai_thinking.is_set():
                state = "  <ansiyellow><b>⟳ thinking…</b></ansiyellow>"
            else:
                state = f"  <b>Tab</b>:complete  <b>↑↓</b>:history  <b>Alt+↵</b>:newline"
            return HTML(
                f"  <b>{name}</b>"
                f"  hist:<b>{hist}</b>/{chars_str}c"
                f"{ctx_part}"
                f"{state}"
            )
        except Exception:
            return ""

    return PromptSession(
        history=FileHistory(str(history_dir / "history")),
        auto_suggest=AutoSuggestFromHistory(),
        completer=_CmdCompleter(
            get_sessions=lambda: [s["name"] for s in agent.list_sessions()]
        ),
        complete_while_typing=True,
        bottom_toolbar=_toolbar,
        style=PTStyle.from_dict({
            "bottom-toolbar": "bg:#1c1c2e fg:#888888",
        }),
        key_bindings=kb,
    )


def interactive(agent: LumodeAgent, debug: bool = False) -> None:
    # ── Welcome panel ─────────────────────────────────────────────────────────
    _print_welcome(agent)

    # ── Input setup ───────────────────────────────────────────────────────────
    ai_thinking = threading.Event()
    session = _make_session(agent, ai_thinking)

    def get_input(queue_mode: bool = False) -> str:
        if session is not None:
            session_label = f" [{agent.session_name}]" if agent.session_name else ""
            ctx_hint = f"<ansicyan><b>+{len(agent.context)}</b></ansicyan> " if agent.context else ""
            if queue_mode:
                prompt_str = HTML('<ansiyellow><b>↳</b></ansiyellow> <dim>queue</dim> <ansiblue>❯</ansiblue> ')
            else:
                prompt_str = HTML(
                    f'<ansigreen><b>lumode{session_label}</b></ansigreen> {ctx_hint}<ansiblue>❯</ansiblue> '
                )
            return session.prompt(prompt_str).strip()
        session_label = f" [{agent.session_name}]" if agent.session_name else ""
        return input(f"{Colors.GREEN}lumode{session_label}>{Colors.RESET} ").strip()

    # ── Main loop ─────────────────────────────────────────────────────────────
    pending_msg: Optional[str] = None
    while True:
        if pending_msg is not None:
            raw, pending_msg = pending_msg, None
        else:
            try:
                raw = get_input()
            except (EOFError, KeyboardInterrupt):
                print()
                return

        if not raw:
            continue
        if raw in {"/quit", "/exit", "/q"}:
            return
        if raw == "/help":
            print_help()
            continue
        if raw == "/context":
            _print_info(agent.context_status())
            continue
        if raw == "/status":
            _print_status(agent)
            continue
        if raw == "/version":
            _print_info(f"Lumode {LUMODE_VERSION}")
            continue
        if raw.startswith("/history"):
            parts = shlex.split(raw)
            try:
                limit = int(parts[1]) if len(parts) > 1 else 20
                _print_info(agent.history_status(limit))
            except ValueError as exc:
                _print_error(str(exc))
            continue
        if raw.startswith("/compact"):
            parts = shlex.split(raw)
            try:
                keep = int(parts[1]) if len(parts) > 1 else None
                _print_ok(agent.compact_history(keep_messages=keep))
            except ValueError as exc:
                _print_error(str(exc))
            continue
        if raw.startswith("/auto-compact"):
            try:
                _print_info(agent.configure_auto_compact(raw[len("/auto-compact"):].strip()))
            except ValueError as exc:
                _print_error(str(exc))
            continue
        if raw.startswith("/last"):
            parts = shlex.split(raw)
            if len(parts) > 1:
                try:
                    _print_ok(agent.write_last_response(parts[1]))
                except OSError as exc:
                    _print_error(str(exc))
            elif agent.last_response:
                agent._render_response(agent.last_response)
            else:
                _print_info("No last response.")
            continue
        if raw.startswith("/drop "):
            _print_info(agent.drop_context(raw[6:].strip()))
            continue
        if raw.startswith("/note "):
            _print_ok(agent.add_note(raw[6:].strip()))
            continue
        if raw.startswith("/prompt"):
            msg = agent.set_system_prompt(raw[len("/prompt"):].strip())
            (_print_ok if msg == "Updated system prompt." else _print_info)(msg)
            continue
        if raw.startswith("/read "):
            _print_info(agent.read_file_tool(raw[6:].strip()))
            continue
        if raw.startswith("/ls"):
            try:
                parts = shlex.split(raw)
                path = parts[1] if len(parts) > 1 else "."
                depth = int(parts[2]) if len(parts) > 2 else 2
                _print_info(agent.list_tree_tool(path, depth))
            except ValueError as exc:
                _print_error(str(exc))
            continue
        if raw == "/sessions":
            _print_sessions(agent)
            continue
        if raw == "/pwd":
            _print_info(str(agent.cwd))
            continue
        if raw == "/reset":
            _print_ok(agent.reset_all())
            continue
        if raw == "/clear":
            agent.clear()
            if agent.session_name:
                agent.save_session(agent.session_name)
            _print_ok("Cleared history and context.")
            continue
        if raw == "/apply":
            result = agent.apply_last_patch()
            (_print_ok if "applied" in result.lower() else _print_info)(result)
            continue
        if raw.startswith("/new"):
            parts = shlex.split(raw)
            try:
                _print_ok(agent.new_session(parts[1] if len(parts) > 1 else None))
            except ValueError as exc:
                _print_error(str(exc))
            continue
        if raw.startswith("/save"):
            parts = shlex.split(raw)
            try:
                _print_ok(agent.save_session(parts[1] if len(parts) > 1 else None))
            except (OSError, ValueError) as exc:
                _print_error(str(exc))
            continue
        if raw.startswith("/load "):
            parts = shlex.split(raw)
            if len(parts) < 2:
                _print_error("Usage: /load <name>")
                continue
            try:
                msg = agent.load_session(parts[1])
                (_print_ok if msg.startswith("Loaded") else _print_info)(msg)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                _print_error(str(exc))
            continue
        if raw.startswith("/delete "):
            parts = shlex.split(raw)
            if len(parts) < 2:
                _print_error("Usage: /delete <name>")
                continue
            try:
                msg = agent.delete_session(parts[1])
                (_print_ok if msg.startswith("Deleted") else _print_info)(msg)
            except (OSError, ValueError) as exc:
                _print_error(str(exc))
            continue
        if raw.startswith("/rename "):
            parts = shlex.split(raw)
            if len(parts) < 2:
                _print_error("Usage: /rename <name>")
                continue
            try:
                msg = agent.rename_session(parts[1])
                (_print_ok if msg.startswith("Renamed") else _print_info)(msg)
            except (OSError, ValueError) as exc:
                _print_error(str(exc))
            continue
        if raw.startswith("/export"):
            parts = shlex.split(raw)
            try:
                _print_ok(agent.export_session(parts[1] if len(parts) > 1 else None))
            except OSError as exc:
                _print_error(str(exc))
            continue
        if raw.startswith("/cd "):
            msg = agent.change_cwd(raw[4:].strip())
            (_print_ok if msg.startswith("Changed") else _print_info)(msg)
            continue
        if raw.startswith("/add "):
            msg = agent.add_path(raw[5:].strip())
            (_print_ok if "Added" in msg else _print_info)(msg)
            continue
        if raw.startswith("/tree"):
            parts = shlex.split(raw)
            path = parts[1] if len(parts) > 1 else "."
            depth = int(parts[2]) if len(parts) > 2 else 3
            _print_ok(agent.add_tree(path, depth))
            continue
        if raw.startswith("/run "):
            _print_ok(agent.add_command_output(raw[5:].strip()))
            continue
        if raw.startswith("/search "):
            query = raw[8:].strip()
            if _RICH:
                with _console.status(f"[dim]Searching: {query}…[/dim]", spinner="dots"):
                    agent.context.append(ContextItem(f"web_search: {query}", web_search(query)))
            else:
                agent.context.append(ContextItem(f"web_search: {query}", web_search(query)))
            _print_ok("Added web search results.")
            continue
        if raw.startswith("/fetch "):
            url = raw[7:].strip()
            if _RICH:
                with _console.status(f"[dim]Fetching {url}…[/dim]", spinner="dots"):
                    agent.context.append(ContextItem(f"fetch_url: {url}", fetch_url(url)))
            else:
                agent.context.append(ContextItem(f"fetch_url: {url}", fetch_url(url)))
            _print_ok("Added URL content.")
            continue
        if raw.startswith("/"):
            _print_info("Unknown command. Type /help for commands.")
            continue

        # ── Send to AI — run in background so user can queue the next message ──
        ai_thinking.set()
        done = threading.Event()
        errors: list = []

        def _do_ask(_raw=raw):
            try:
                agent.ask(_raw, debug=debug)
            except RuntimeError as exc:
                errors.append(exc)
            finally:
                ai_thinking.clear()
                done.set()

        threading.Thread(target=_do_ask, daemon=True).start()

        # patch_stdout(raw=True): AI's ANSI colour codes pass through unescaped
        # and appear correctly above the queue prompt line.
        with pt_patch_stdout(raw=True):
            try:
                nxt = get_input(queue_mode=True)
                if nxt:
                    pending_msg = nxt
            except (EOFError, KeyboardInterrupt):
                done.wait()
                print()
                return
            done.wait()

        if errors:
            _print_error(str(errors[0]))
            if agent.history and agent.history[-1].get("Role") == "user":
                agent.history.pop()


# ── CLI entry point ───────────────────────────────────────────────────────────

def build_agent(args: argparse.Namespace) -> LumodeAgent:
    if _RICH:
        with _console.status("[dim]Loading Lumo authentication…[/dim]", spinner="dots"):
            auth_data = extract_firefox_cookies()
        _console.print("[green]✓[/green] [dim]Authenticated[/dim]")
    else:
        print(f"{Colors.DIM}Loading Lumo authentication...{Colors.RESET}")
        auth_data = extract_firefox_cookies()
        print(f"{Colors.GREEN}Authenticated{Colors.RESET}\n")

    prompt = args.prompt or LUMODE_SYSTEM_PROMPT
    return LumodeAgent(LumoClient(auth_data), Path(args.cwd), prompt)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lumode - Lumo-powered coding agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  lumode
  lumode --file app.py "Review this file and return a patch"
  lumode --tree . --run "pytest -q" "Fix the failing tests"
  lumode --search "latest Python release" "Summarize this"
  lumode --apply --file bug.py "Return a unified diff for the bug"
  lumode --session bugfix "Continue where we left off"
  lumode --compact --session bugfix "Continue with compacted history"
""",
    )
    parser.add_argument("message", nargs="?", help="Message to send")
    parser.add_argument("--cwd", default=os.getcwd(), help="Workspace directory")
    parser.add_argument("-p", "--prompt", help="Custom system prompt")
    parser.add_argument("--file", action="append", help="Add file context")
    parser.add_argument("--tree", nargs="?", const=".", help="Add directory tree context")
    parser.add_argument("--depth", type=int, default=3, help="Directory tree depth")
    parser.add_argument("--run", action="append", help="Run command and add output context")
    parser.add_argument("--search", action="append", help="Search the web and add results as context")
    parser.add_argument("--fetch", action="append", help="Fetch URL text and add it as context")
    parser.add_argument("--apply", action="store_true", help="Apply unified diff from response")
    parser.add_argument("--session", help="Load a saved session before running")
    parser.add_argument("--save-session", help="Save the conversation under this session name")
    parser.add_argument("--compact", action="store_true", help="Compact loaded history before sending")
    parser.add_argument("--compact-keep", type=int, help="Recent message count to keep when compacting")
    parser.add_argument("--no-auto-compact", action="store_true", help="Disable automatic history compaction")
    parser.add_argument("--auto-compact-chars", type=int, help="History char threshold for automatic compaction")
    parser.add_argument("--debug", action="store_true", help="Print raw responses and tool results")

    args = parser.parse_args()

    if args.debug:
        os.environ["LUMO_DEBUG"] = "1"

    try:
        agent = build_agent(args)
        if args.session:
            msg = agent.load_session(args.session)
            (_print_ok if msg.startswith("Loaded") else _print_info)(msg)
        if args.save_session:
            agent.session_name = LumodeAgent._validate_session_name(args.save_session)
        if args.no_auto_compact:
            agent.auto_compact = False
        if args.auto_compact_chars:
            agent.auto_compact_chars = args.auto_compact_chars
        if args.compact_keep:
            agent.compact_keep_messages = args.compact_keep
        if args.compact:
            _print_ok(agent.compact_history(keep_messages=args.compact_keep))
        if args.file:
            for file_path in args.file:
                _print_ok(agent.add_path(file_path))
        if args.tree:
            _print_ok(agent.add_tree(args.tree, args.depth))
        if args.run:
            for command in args.run:
                _print_ok(agent.add_command_output(command))
        if args.search:
            for query in args.search:
                agent.context.append(ContextItem(f"web_search: {query}", web_search(query)))
                _print_ok(f"Added web search: {query}")
        if args.fetch:
            for url in args.fetch:
                agent.context.append(ContextItem(f"fetch_url: {url}", fetch_url(url)))
                _print_ok(f"Added URL: {url}")

        if args.message:
            agent.ask(args.message, debug=args.debug)
            if args.apply:
                result = agent.apply_last_patch()
                _print_ok(result)
            if args.save_session:
                _print_ok(agent.save_session(args.save_session))
        elif not sys.stdin.isatty():
            message = sys.stdin.read().strip()
            if message:
                agent.ask(message, debug=args.debug)
                if args.apply:
                    _print_ok(agent.apply_last_patch())
                if args.save_session:
                    _print_ok(agent.save_session(args.save_session))
        else:
            interactive(agent, debug=args.debug)

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted.{Colors.RESET}")
        sys.exit(0)
    except Exception as exc:
        _print_error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
