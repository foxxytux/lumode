#!/usr/bin/env python3
"""Lumo CLI with U2L Encryption - Secure end-to-end encrypted chat with Proton's Lumo."""

import sys
import os
import json
import sqlite3
import argparse
import re
import uuid
import base64
import configparser
import platform
from pathlib import Path
from typing import Optional, Generator
import urllib.parse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    import gnupg
except ImportError:
    print("Error: Missing cryptography dependencies.", file=sys.stderr)
    print("Install with: pip install cryptography python-gnupg", file=sys.stderr)
    sys.exit(1)

# Lumo's public GPG key for U2L encryption
LUMO_GPG_PUB_KEY = """-----BEGIN PGP PUBLIC KEY BLOCK-----

mI0EZkKpnwEEALNVvfZEYXGqx2LSVCaKfGcVwHAVKqqaJJz3gMZPXWpKQh3dJiVP
iILe5aLnCi0aeFx8gLoRvt5jIBHKkA+4YV5LZ3KRVT0w8eYKpfDuq0nPqe5m7RKg
n2ijJJ1qDGH4eRfLXGNtBRNmswVqqF3FNsw6tEuRnr1q7LsEVqVBBYj9ABEBAAG0
F0x1bW8gUmVzcG9uc2VzIDxtQGwuY29t4jADAwMLLFj9aZgkLT3w2BwpFaXXn7mA
cjCU2AIfGqY2RnSwzBCfhqkVLhCb7Wqy6LvWYa1WFKXqc3mDDAIQKqr1JJQNAwN0
jkrLxGSKGmCAWjU5uQkCBwAAAAAAQI2wTZEZbSEjCaGKrFgb8C/4jfmBKwhCfAVp
vqRjR+SAAJX0pPNiEhO5ER0nLV9XbKNbRY9C5wM4lC2Y5Xj5pZ0AKQM=
=uVJN
-----END PGP PUBLIC KEY BLOCK-----"""

# ANSI color codes
class Colors:
    BOLD = '\033[1m'
    DIM = '\033[2m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    RESET = '\033[0m'


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
    if os.getenv("LUMO_UID") and os.getenv("LUMO_TOKEN"):
        return {
            "uid": os.getenv("LUMO_UID"),
            "access_token": os.getenv("LUMO_TOKEN"),
        }

    firefox_dir = get_firefox_dir()
    if not firefox_dir.exists():
        raise RuntimeError(f"Firefox profile directory not found at {firefox_dir}")

    profiles = find_firefox_profiles(firefox_dir)
    if not profiles:
        raise RuntimeError(f"No Firefox profiles found in {firefox_dir}")

    cookies_db = profiles[-1] / "cookies.sqlite"
    if not cookies_db.exists():
        raise RuntimeError("Cookies database not found")

    import tempfile
    import shutil
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite").name
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

    uid_match = None
    for name in cookies:
        if name.startswith("AUTH-"):
            uid_match = name[5:]
            break

    if not uid_match:
        raise RuntimeError("No AUTH cookie found for lumo.proton.me")

    auth_token = cookies.get(f"AUTH-{uid_match}")
    if not auth_token:
        raise RuntimeError("AUTH token not found in cookies")

    return {
        "uid": uid_match,
        "access_token": auth_token,
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


class AesGcmEncryption:
    """AES-GCM encryption utilities for U2L."""

    @staticmethod
    def generate_key() -> bytes:
        """Generate a random 256-bit AES key."""
        return os.urandom(32)

    @staticmethod
    def encrypt(plaintext: str, key: bytes, ad: str) -> str:
        """Encrypt plaintext with AES-GCM and return base64-encoded ciphertext."""
        nonce = os.urandom(12)
        cipher = AESGCM(key)
        ciphertext = cipher.encrypt(nonce, plaintext.encode('utf-8'), ad.encode('utf-8'))
        # Return nonce + ciphertext as base64
        return base64.b64encode(nonce + ciphertext).decode('ascii')

    @staticmethod
    def decrypt(encrypted_b64: str, key: bytes, ad: str) -> str:
        """Decrypt base64-encoded ciphertext with AES-GCM."""
        encrypted = base64.b64decode(encrypted_b64)
        nonce = encrypted[:12]
        ciphertext = encrypted[12:]
        cipher = AESGCM(key)
        plaintext = cipher.decrypt(nonce, ciphertext, ad.encode('utf-8'))
        return plaintext.decode('utf-8')


class LumoEncryptionClient:
    """Lumo client with U2L end-to-end encryption."""

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
        try:
            self.gpg = gnupg.GPG()
            # Test import
            test = self.gpg.import_keys(LUMO_GPG_PUB_KEY)
            self.gpg_available = test.ok and len(test.fingerprints) > 0
        except Exception as e:
            print(f"{Colors.YELLOW}Warning: GPG not available, encryption disabled: {e}{Colors.RESET}", file=sys.stderr)
            self.gpg = None
            self.gpg_available = False

    def _encrypt_request_key(self, aes_key: bytes) -> Optional[str]:
        """Encrypt AES key with Lumo's GPG public key and return base64."""
        if not self.gpg_available or not self.gpg:
            return None

        try:
            # Get Lumo's key ID
            key_list = self.gpg.list_keys()
            if not key_list:
                return None

            key_id = key_list[0]['keyid']

            # Encrypt the AES key
            encrypted = self.gpg.encrypt(
                aes_key,
                key_id,
                always_trust=True,
                armor=False,
            )
            if not encrypted.ok:
                return None

            return base64.b64encode(bytes(encrypted)).decode('ascii')
        except Exception:
            return None

    def chat(self, messages: list[dict], system_prompt: Optional[str] = None, encrypt: bool = True) -> Generator[str, None, None]:
        """Send encrypted messages and stream response."""

        # Build turns
        turns = []
        if system_prompt:
            turns.append({"role": "system", "content": system_prompt})

        # Generate encryption parameters if enabled
        aes_key = None
        request_id = None
        request_key_enc = None

        if encrypt and self.gpg_available:
            aes_key = AesGcmEncryption.generate_key()
            request_id = str(uuid.uuid4())
            request_key_enc = self._encrypt_request_key(aes_key)
            # If GPG encryption failed, fall back to unencrypted
            if not request_key_enc:
                aes_key = None
                request_id = None
        elif encrypt and not self.gpg_available:
            print(f"{Colors.YELLOW}Note: Encryption disabled due to missing GPG setup{Colors.RESET}")

        # Encrypt turns if needed
        for msg in messages:
            turn = {
                "role": msg.get("Role", "user"),
                "content": msg.get("Content", msg.get("content", ""))
            }

            if encrypt and aes_key:
                ad = f"lumo.request.{request_id}.turn"
                turn["content"] = AesGcmEncryption.encrypt(turn["content"], aes_key, ad)

            turns.append(turn)

        # Build request
        request_body = {
            "type": "generation_request",
            "turns": turns,
            "options": {"tools": ["proton_info"]},
            "targets": ["message"],
        }

        if encrypt and request_key_enc and request_id:
            request_body["request_key"] = request_key_enc
            request_body["request_id"] = request_id

        payload = {"Prompt": request_body}

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
                raise RuntimeError("Authentication failed - visit https://lumo.proton.me to refresh session")
            elif e.response.status_code == 403:
                raise RuntimeError("Access denied - Lumo API access may not be enabled")
            elif e.response.status_code == 500:
                body = e.response.text.strip()
                if len(body) > 500:
                    body = body[:500] + "..."
                raise RuntimeError(f"Server error (500) from Lumo. Response body: {body or '(empty)'}")
            else:
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
                        content = extract_token_text(data)

                        # Decrypt if needed
                        if encrypt and aes_key and request_id and data.get("encrypted"):
                            ad = f"lumo.response.{request_id}.chunk"
                            try:
                                content = AesGcmEncryption.decrypt(content, aes_key, ad)
                            except Exception as e:
                                print(f"Decryption error: {e}", file=sys.stderr)
                                content = "[decryption failed]"

                        if content:
                            emitted_text = True
                            yield content
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
                        content = extract_token_text(data)
                        if content:
                            emitted_text = True
                            yield content

        # Process final buffer
        if debug_stream and buffer.strip():
            print(f"[lumo sse] {buffer}", file=sys.stderr)
        data = parse_sse_data(buffer)
        if data:
            content = extract_token_text(data)
            if content and data.get("type") != "done" and data.get("target", "message") == "message":
                emitted_text = True
                yield content
        if not emitted_text:
            raise RuntimeError(
                "Lumo response contained no text tokens. "
                "Run with LUMO_DEBUG=1 to inspect the raw SSE events."
            )


def interactive_chat(client: LumoEncryptionClient, system_prompt: Optional[str] = None, encrypt: bool = True):
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
                for token in client.chat(history, system_prompt=system_prompt, encrypt=encrypt):
                    print(token, end="", flush=True)
                    full_response += token
                print()
            except RuntimeError as e:
                print(f"\n{Colors.RED}Error: {e}{Colors.RESET}")
                history.pop()
                continue

            history.append({"Role": "assistant", "Content": full_response})
            print()

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Chat ended.{Colors.RESET}")
    except EOFError:
        print(f"\n{Colors.YELLOW}Chat ended.{Colors.RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="Lumo CLI with U2L End-to-End Encryption",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("-p", "--prompt", help="System prompt")
    parser.add_argument("-c", "--code", action="store_true", help="Coding assistant mode")
    parser.add_argument("--no-encryption", action="store_true", help="Disable U2L encryption (not recommended)")
    parser.add_argument("message", nargs="?", help="Message to send")

    args = parser.parse_args()

    try:
        print(f"{Colors.DIM}Loading authentication...{Colors.RESET}")
        auth_data = extract_firefox_cookies()
        print(f"{Colors.GREEN}✓ Authenticated{Colors.RESET}\n")

        client = LumoEncryptionClient(auth_data)

        system_prompt = args.prompt
        if args.code and not system_prompt:
            system_prompt = """You are an expert coding assistant. Help with:
- Writing clean, efficient code
- Debugging and fixing issues
- Explaining code and concepts
- Code review and refactoring
- Learning programming best practices

Always provide practical, working solutions with explanations."""

        encrypt = not args.no_encryption

        if args.message:
            history = [{"Role": "user", "Content": args.message}]
            for token in client.chat(history, system_prompt=system_prompt, encrypt=encrypt):
                print(token, end="", flush=True)
            print()
        elif not sys.stdin.isatty():
            message = sys.stdin.read().strip()
            if message:
                history = [{"Role": "user", "Content": message}]
                for token in client.chat(history, system_prompt=system_prompt, encrypt=encrypt):
                    print(token, end="", flush=True)
                print()
        else:
            interactive_chat(client, system_prompt=system_prompt, encrypt=encrypt)

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted.{Colors.RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
