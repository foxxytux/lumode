#!/usr/bin/env python3
"""Lumo CLI - A command-line interface for Proton's Lumo AI assistant with coding focus."""

import sys
import os
import json
import sqlite3
import argparse
import re
import configparser
import platform
from pathlib import Path
from typing import Optional, Generator
import urllib.parse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Color codes for terminal output
class Colors:
    BOLD = '\033[1m'
    DIM = '\033[2m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    CYAN = '\033[96m'

def get_firefox_dir() -> Path:
    """Return the Firefox profile root for the current OS."""
    system = platform.system().lower()
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "Firefox"
    if system == "linux":
        return Path.home() / ".mozilla" / "firefox"
    raise RuntimeError(f"Unsupported OS for Firefox profile lookup: {platform.system()}")

def find_firefox_profiles(firefox_dir: Optional[Path] = None) -> list[Path]:
    """Find Firefox profiles, preferring profiles.ini default entries."""
    firefox_dir = firefox_dir or get_firefox_dir()
    profiles_ini = firefox_dir / "profiles.ini"
    profiles: list[Path] = []

    if profiles_ini.exists():
        config = configparser.ConfigParser()
        config.read(profiles_ini)
        sections = [section for section in config.sections() if section.startswith("Profile")]
        sections.sort(key=lambda section: config.get(section, "Default", fallback="0") != "1")

        for section in sections:
            path_value = config.get(section, "Path", fallback=None)
            if not path_value:
                continue

            is_relative = config.get(section, "IsRelative", fallback="1") == "1"
            profile_path = firefox_dir / path_value if is_relative else Path(path_value)
            if profile_path.exists():
                profiles.append(profile_path)

    if profiles:
        return profiles

    return [path for path in firefox_dir.iterdir() if path.is_dir() and (path / "cookies.sqlite").exists()]

def extract_firefox_cookies(domain: str = "lumo.proton.me") -> dict:
    """Extract auth cookies from Firefox profile."""
    # Check for environment variable override
    if os.getenv("LUMO_TOKEN") and os.getenv("LUMO_UID"):
        return {
            "uid": os.getenv("LUMO_UID"),
            "access_token": os.getenv("LUMO_TOKEN"),
            "refresh_token": os.getenv("LUMO_REFRESH_TOKEN"),
            "cookies": {}
        }

    firefox_dir = get_firefox_dir()
    if not firefox_dir.exists():
        raise RuntimeError(
            f"Firefox profile directory not found at {firefox_dir}.\n"
            "Alternative: Set LUMO_UID and LUMO_TOKEN environment variables"
        )

    profiles = find_firefox_profiles(firefox_dir)
    if not profiles:
        raise RuntimeError(
            f"No Firefox profiles found in {firefox_dir}.\n"
            "Alternative: Set LUMO_UID and LUMO_TOKEN environment variables"
        )

    cookies_db = profiles[-1] / "cookies.sqlite"
    if not cookies_db.exists():
        raise RuntimeError(f"Cookies database not found at {cookies_db}")

    # Copy DB to temp location (Firefox may lock it)
    import tempfile
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite").name
    import shutil
    shutil.copy(str(cookies_db), temp_db)

    try:
        conn = sqlite3.connect(temp_db)
        cur = conn.cursor()
        cur.execute(
            "SELECT name, value FROM moz_cookies WHERE host LIKE ? ORDER BY expiry DESC",
            (f"%{domain}%",)
        )
        cookies = {name: value for name, value in cur.fetchall()}
        conn.close()
    finally:
        os.unlink(temp_db)

    # Extract UID from AUTH cookie
    uid_match = None
    for name in cookies:
        if name.startswith("AUTH-"):
            uid_match = name[5:]
            break

    if not uid_match:
        raise RuntimeError(
            f"No AUTH cookie found for {domain}.\n"
            "Make sure you're logged into Lumo in Firefox.\n"
            "Alternative: Set LUMO_UID and LUMO_TOKEN environment variables"
        )

    # Get auth and refresh tokens
    auth_token = cookies.get(f"AUTH-{uid_match}")
    refresh_cookie = cookies.get(f"REFRESH-{uid_match}")

    if not auth_token:
        raise RuntimeError("AUTH token not found in cookies")

    # Parse refresh cookie if present
    refresh_token = None
    if refresh_cookie:
        try:
            decoded = urllib.parse.unquote(refresh_cookie)
            refresh_data = json.loads(decoded)
            refresh_token = refresh_data.get("RefreshToken")
        except:
            pass

    return {
        "uid": uid_match,
        "access_token": auth_token,
        "refresh_token": refresh_token,
        "cookies": cookies
    }

def create_session() -> requests.Session:
    """Create requests session with retry strategy."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def extract_token_text(data: dict) -> str:
    """Extract text from known Lumo SSE token shapes."""
    for key in ("content", "value", "text", "delta", "message"):
        value = data.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            nested = extract_token_text(value)
            if nested:
                return nested
    return ""

def parse_sse_data(line: str) -> Optional[dict]:
    """Parse an SSE data line that may be formatted as 'data: {...}' or 'data:{...}'."""
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None

class LumoClient:
    """Client for interacting with Lumo API."""

    BASE_URL = "https://lumo.proton.me/api"
    API_VERSION = "web-lumo@1.4.0.5"

    def __init__(self, auth_data: dict):
        self.auth_data = auth_data
        self.session = create_session()
        self.headers = {
            "x-pm-uid": auth_data["uid"],
            "Authorization": f"Bearer {auth_data['access_token']}",
            "x-pm-appversion": self.API_VERSION,
            "Content-Type": "application/json",
        }
        # Add cookies to session for fallback auth
        for name, value in auth_data.get("cookies", {}).items():
            self.session.cookies.set(name, value, domain="lumo.proton.me")

    def chat(self, messages: list[dict], system_prompt: Optional[str] = None) -> Generator[str, None, None]:
        """Send messages and stream response using SSE."""

        turns = []
        if system_prompt:
            turns.append({"role": "system", "content": system_prompt})

        for msg in messages:
            turns.append({
                "role": msg.get("Role", msg.get("role", "user")).lower(),
                "content": msg.get("Content", msg.get("content", "")),
            })

        payload = {
            "Prompt": {
                "type": "generation_request",
                "turns": turns,
                "options": {"tools": ["proton_info"]},
                "targets": ["message"],
            }
        }

        try:
            response = self.session.post(
                f"{self.BASE_URL}/ai/v1/chat",
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=120
            )
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                raise RuntimeError(
                    "Authentication failed - token may be expired.\n"
                    "Try: Opening Lumo in Firefox to refresh the session.\n"
                    "Or: Set LUMO_UID and LUMO_TOKEN environment variables"
                )
            elif e.response.status_code == 403:
                raise RuntimeError(
                    "Access denied - you may not have API access.\n"
                    "The Lumo API is currently in beta testing."
                )
            elif e.response.status_code == 500:
                body = e.response.text.strip()
                if len(body) > 500:
                    body = body[:500] + "..."
                raise RuntimeError(
                    "Server error (500) from Lumo. This often means the API rejected the request shape.\n"
                    f"Response body: {body or '(empty)'}"
                )
            elif e.response.status_code == 503:
                raise RuntimeError("Service unavailable (503) - API is under maintenance")
            else:
                try:
                    error_json = e.response.json()
                    error_msg = error_json.get("Error", error_json.get("error", str(error_json)))
                    raise RuntimeError(f"API error {e.response.status_code}: {error_msg}")
                except:
                    raise RuntimeError(f"API error {e.response.status_code}: {e.response.text}")

        except requests.RequestException as e:
            raise RuntimeError(f"Network/API request failed: {e}")

        # Parse SSE stream
        buffer = ""
        emitted_text = False
        debug_stream = os.getenv("LUMO_DEBUG") == "1"
        for chunk in response.iter_content(decode_unicode=True):
            if chunk:
                buffer += chunk
                lines = buffer.split('\n')

                # Keep the last incomplete line in buffer
                buffer = lines[-1]

                for line in lines[:-1]:
                    if debug_stream and line.strip():
                        print(f"[lumo sse] {line}", file=sys.stderr)
                    data = parse_sse_data(line)
                    if not data:
                        continue
                    if data.get("type") == "token_data":
                        if data.get("target", "message") != "message":
                            continue
                        token = extract_token_text(data)
                        if token:
                            emitted_text = True
                            yield token
                    elif data.get("type") == "done":
                        if not emitted_text:
                            raise RuntimeError(
                                "Lumo returned a completed stream with no text tokens. "
                                "Run with LUMO_DEBUG=1 to inspect the raw SSE events."
                            )
                        return
                    elif data.get("type") == "error":
                        raise RuntimeError(f"API error: {data.get('message', 'Unknown')}")
                    else:
                        if data.get("target") not in (None, "message"):
                            continue
                        token = extract_token_text(data)
                        if token:
                            emitted_text = True
                            yield token

        # Process final buffer if any
        if debug_stream and buffer.strip():
            print(f"[lumo sse] {buffer}", file=sys.stderr)
        data = parse_sse_data(buffer)
        if data:
            token = extract_token_text(data)
            if token and data.get("type") != "done" and data.get("target", "message") == "message":
                emitted_text = True
                yield token
        if not emitted_text:
            raise RuntimeError(
                "Lumo response contained no text tokens. "
                "Run with LUMO_DEBUG=1 to inspect the raw SSE events."
            )

    def stream_events(self, messages: list[dict], system_prompt: Optional[str] = None) -> Generator[dict, None, None]:
        """Yield all raw parsed SSE event dicts, including tool_call and tool_result events."""
        turns = []
        if system_prompt:
            turns.append({"role": "system", "content": system_prompt})
        for msg in messages:
            turns.append({
                "role": msg.get("Role", msg.get("role", "user")).lower(),
                "content": msg.get("Content", msg.get("content", "")),
            })

        payload = {
            "Prompt": {
                "type": "generation_request",
                "turns": turns,
                "options": {"tools": ["proton_info"]},
                "targets": ["message"],
            }
        }

        try:
            response = self.session.post(
                f"{self.BASE_URL}/ai/v1/chat",
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=120,
            )
            response.raise_for_status()
        except requests.HTTPError as e:
            sc = e.response.status_code
            if sc == 401:
                raise RuntimeError(
                    "Authentication failed - token may be expired.\n"
                    "Try: Opening Lumo in Firefox to refresh the session."
                )
            elif sc == 403:
                raise RuntimeError("Access denied - you may not have API access.")
            else:
                raise RuntimeError(f"API error {sc}: {e.response.text[:200]}")
        except requests.RequestException as e:
            raise RuntimeError(f"Network/API request failed: {e}")

        debug = os.getenv("LUMO_DEBUG") == "1"
        buffer = ""
        for chunk in response.iter_content(decode_unicode=True):
            if chunk:
                buffer += chunk
                lines = buffer.split("\n")
                buffer = lines[-1]
                for line in lines[:-1]:
                    if debug and line.strip():
                        print(f"[lumo sse] {line}", file=sys.stderr)
                    data = parse_sse_data(line)
                    if data:
                        yield data
        if buffer.strip():
            if debug:
                print(f"[lumo sse] {buffer}", file=sys.stderr)
            data = parse_sse_data(buffer)
            if data:
                yield data


def interactive_chat(client: LumoClient, system_prompt: Optional[str] = None):
    """Run interactive chat session."""
    history = []

    if system_prompt:
        print(f"{Colors.BLUE}System prompt:{Colors.RESET} {system_prompt}\n")

    try:
        while True:
            user_input = input(f"{Colors.GREEN}You:{Colors.RESET} ").strip()

            if not user_input:
                continue
            if user_input.lower() in ["/quit", "/exit", "/q"]:
                break
            if user_input.lower() == "/clear":
                history = []
                print("Chat history cleared.\n")
                continue

            history.append({"Role": "user", "Content": user_input})

            print(f"{Colors.CYAN}Lumo:{Colors.RESET} ", end="", flush=True)

            full_response = ""
            try:
                for token in client.chat(history, system_prompt=system_prompt):
                    print(token, end="", flush=True)
                    full_response += token
                print()
            except RuntimeError as e:
                print(f"\n{Colors.RED}Error: {e}{Colors.RESET}")
                history.pop()  # Remove user message on error
                continue

            history.append({"Role": "assistant", "Content": full_response})
            print()

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Chat ended.{Colors.RESET}")
    except EOFError:
        print(f"\n{Colors.YELLOW}Chat ended.{Colors.RESET}")

def main():
    parser = argparse.ArgumentParser(
        description="Lumo CLI - Privacy-first AI assistant from Proton",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  lumo-cli                                # Interactive chat
  lumo-cli -p "You are a coding assistant" # With system prompt
  echo "Write a Python function" | lumo-cli # Pipe mode
        """
    )

    parser.add_argument(
        "-p", "--prompt",
        help="System prompt for the conversation"
    )
    parser.add_argument(
        "-c", "--code",
        action="store_true",
        help="Use a coding assistant system prompt"
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="Message to send (if not provided, enters interactive mode)"
    )

    args = parser.parse_args()

    try:
        # Extract auth from Firefox
        print(f"{Colors.DIM}Extracting auth from Firefox...{Colors.RESET}")
        auth_data = extract_firefox_cookies()
        print(f"{Colors.GREEN}✓ Authentication loaded{Colors.RESET}\n")

        client = LumoClient(auth_data)

        # Determine system prompt
        system_prompt = args.prompt
        if args.code and not system_prompt:
            system_prompt = """You are a expert coding assistant. Help with:
- Writing clean, efficient code
- Debugging and fixing issues
- Explaining code and concepts
- Code review and refactoring
- Learning programming best practices

Always provide practical, working solutions with explanations."""

        # Single message mode (stdin or arg)
        if args.message:
            history = [{"Role": "user", "Content": args.message}]
            for token in client.chat(history, system_prompt=system_prompt):
                print(token, end="", flush=True)
            print()
        elif not sys.stdin.isatty():
            # Read from pipe
            message = sys.stdin.read().strip()
            if message:
                history = [{"Role": "user", "Content": message}]
                for token in client.chat(history, system_prompt=system_prompt):
                    print(token, end="", flush=True)
                print()
        else:
            # Interactive mode
            interactive_chat(client, system_prompt=system_prompt)

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted.{Colors.RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
