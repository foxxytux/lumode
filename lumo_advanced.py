#!/usr/bin/env python3
"""Lumo Advanced - Extended CLI with coding features (file context, execution, etc)."""

import sys
import os
import json
import subprocess
from pathlib import Path
from typing import Optional
from lumo_cli import LumoClient, extract_firefox_cookies, Colors

class AdvancedLumoClient:
    """Extended Lumo client with coding features."""

    def __init__(self, client: LumoClient):
        self.client = client
        self.context_files = []
        self.working_dir = Path.cwd()

    def add_file_context(self, file_path: str, limit_lines: Optional[int] = None) -> str:
        """Add file context to next query."""
        path = Path(file_path).resolve()

        if not path.exists():
            return f"Error: File not found: {file_path}"

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            if limit_lines and limit_lines > 0:
                lines = content.split('\n')[:limit_lines]
                content = '\n'.join(lines) + '\n...(truncated)'

            self.context_files.append({
                "path": str(path.relative_to(self.working_dir)),
                "content": content
            })
            return f"Added {path.name} ({len(content)} chars)"
        except Exception as e:
            return f"Error reading file: {e}"

    def add_dir_structure(self, dir_path: str = ".", max_depth: int = 3) -> str:
        """Add directory structure as context."""
        path = Path(dir_path).resolve()

        if not path.is_dir():
            return f"Error: Not a directory: {dir_path}"

        def get_tree(p: Path, prefix: str = "", depth: int = 0) -> str:
            if depth > max_depth:
                return ""

            items = []
            try:
                for item in sorted(p.iterdir()):
                    if item.name.startswith('.'):
                        continue
                    if item.is_dir():
                        items.append(f"{prefix}├── {item.name}/")
                        items.append(get_tree(item, prefix + "│   ", depth + 1))
                    else:
                        items.append(f"{prefix}├── {item.name}")
            except PermissionError:
                pass

            return "\n".join(filter(None, items))

        tree = get_tree(path)
        self.context_files.append({
            "path": "directory_structure",
            "content": f"Directory: {path.relative_to(self.working_dir)}\n\n{tree}"
        })
        return f"Added directory structure (depth={max_depth})"

    def run_command(self, cmd: str, timeout: int = 30) -> str:
        """Execute a command and capture output for context."""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.working_dir
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[STDERR]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[Exit code: {result.returncode}]"
            return output[:5000]  # Limit output
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s"
        except Exception as e:
            return f"Error running command: {e}"

    def build_context_prompt(self, user_message: str) -> str:
        """Build message with file context."""
        if not self.context_files:
            return user_message

        context = "=== FILE CONTEXT ===\n\n"
        for file_info in self.context_files:
            context += f"### {file_info['path']}\n"
            context += f"```\n{file_info['content']}\n```\n\n"

        context += "=== USER MESSAGE ===\n" + user_message

        self.context_files = []  # Clear after use
        return context

    def chat_with_context(self, message: str, history: list, system_prompt: str) -> str:
        """Chat with file context included."""
        full_message = self.build_context_prompt(message)
        history.append({"Role": "user", "Content": full_message})

        response = ""
        for token in self.client.chat(history, system_prompt=system_prompt):
            print(token, end="", flush=True)
            response += token

        history.append({"Role": "assistant", "Content": response})
        return response

    def interactive_with_commands(self, system_prompt: Optional[str] = None):
        """Interactive mode with special commands for advanced features."""
        history = []
        commands = {
            "/file": "Add file: /file <path> [max_lines]",
            "/dir": "Add directory structure: /dir [path] [max_depth]",
            "/exec": "Run command and add output: /exec <command>",
            "/context": "Show current context",
            "/clear": "Clear chat history",
            "/quit": "Exit",
            "/help": "Show this help"
        }

        print(f"{Colors.BLUE}Lumo Advanced CLI{Colors.RESET}")
        print(f"{Colors.DIM}Type /help for commands{Colors.RESET}\n")

        if system_prompt:
            print(f"{Colors.BLUE}System prompt:{Colors.RESET} {system_prompt}\n")

        try:
            while True:
                user_input = input(f"{Colors.GREEN}You:{Colors.RESET} ").strip()

                if not user_input:
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    parts = user_input.split(maxsplit=2)
                    cmd = parts[0]

                    if cmd == "/help":
                        for command, help_text in commands.items():
                            print(f"  {Colors.CYAN}{command}{Colors.RESET} - {help_text}")
                        print()
                    elif cmd == "/file" and len(parts) > 1:
                        max_lines = int(parts[2]) if len(parts) > 2 else None
                        result = self.add_file_context(parts[1], max_lines)
                        print(f"{Colors.GREEN}✓{Colors.RESET} {result}\n")
                    elif cmd == "/dir":
                        dir_path = parts[1] if len(parts) > 1 else "."
                        max_depth = int(parts[2]) if len(parts) > 2 else 3
                        result = self.add_dir_structure(dir_path, max_depth)
                        print(f"{Colors.GREEN}✓{Colors.RESET} {result}\n")
                    elif cmd == "/exec" and len(parts) > 1:
                        cmd_to_run = user_input[6:].strip()  # Get everything after /exec
                        output = self.run_command(cmd_to_run)
                        self.context_files.append({
                            "path": f"command_output: {cmd_to_run}",
                            "content": output
                        })
                        print(f"{Colors.GREEN}✓{Colors.RESET} Command output added\n")
                    elif cmd == "/context":
                        if self.context_files:
                            for f in self.context_files:
                                print(f"  - {f['path']} ({len(f['content'])} chars)")
                        else:
                            print("  (no context added)")
                        print()
                    elif cmd == "/clear":
                        history = []
                        self.context_files = []
                        print(f"{Colors.YELLOW}Chat history and context cleared{Colors.RESET}\n")
                    elif cmd == "/quit":
                        break
                    else:
                        print(f"{Colors.RED}Unknown command: {cmd}{Colors.RESET}")
                        print(f"Type /help for available commands\n")
                    continue

                # Regular message
                print(f"{Colors.CYAN}Lumo:{Colors.RESET} ", end="", flush=True)
                try:
                    self.chat_with_context(user_input, history, system_prompt)
                    print("\n")
                except RuntimeError as e:
                    print(f"\n{Colors.RED}Error: {e}{Colors.RESET}\n")
                    history.pop()  # Remove user message on error
                    continue

        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Session ended.{Colors.RESET}")
        except EOFError:
            print(f"\n{Colors.YELLOW}Session ended.{Colors.RESET}")

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Lumo Advanced CLI - Privacy-first AI with coding context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Advanced examples:
  lumo-advanced -c                                # Interactive with code assist
  lumo-advanced -c --file bug.py "Why doesn't this work?"  # With file context
  lumo-advanced --exec "npm test" --file test.js "Debug these failures"
    """
    )

    parser.add_argument("-p", "--prompt", help="Custom system prompt")
    parser.add_argument("-c", "--code", action="store_true", help="Coding assistant mode")
    parser.add_argument("--file", action="append", help="Add file as context (can use multiple times)")
    parser.add_argument("--dir", help="Add directory structure as context")
    parser.add_argument("--exec", help="Run command and add output as context")
    parser.add_argument("message", nargs="?", help="Message to send")

    args = parser.parse_args()

    try:
        # Initialize client
        auth_data = extract_firefox_cookies()
        client = LumoClient(auth_data)
        adv_client = AdvancedLumoClient(client)

        # Set system prompt
        system_prompt = args.prompt
        if args.code and not system_prompt:
            system_prompt = """You are an expert coding assistant. Help with:
- Writing clean, efficient code
- Debugging and fixing issues
- Explaining code and concepts
- Code review and refactoring
- Learning programming best practices

Always provide practical, working solutions with explanations."""

        # Add context
        if args.file:
            for file_path in args.file:
                print(f"{Colors.DIM}Adding file: {file_path}...{Colors.RESET}")
                result = adv_client.add_file_context(file_path)
                print(f"{Colors.GREEN}✓{Colors.RESET} {result}")

        if args.dir:
            print(f"{Colors.DIM}Adding directory structure...{Colors.RESET}")
            result = adv_client.add_dir_structure(args.dir)
            print(f"{Colors.GREEN}✓{Colors.RESET} {result}")

        if args.exec:
            print(f"{Colors.DIM}Running: {args.exec}...{Colors.RESET}")
            output = adv_client.run_command(args.exec)
            adv_client.context_files.append({
                "path": f"command: {args.exec}",
                "content": output
            })
            print(f"{Colors.GREEN}✓{Colors.RESET} Command output added")

        if args.message:
            # Single message mode
            history = []
            adv_client.chat_with_context(args.message, history, system_prompt)
            print()
        elif not sys.stdin.isatty():
            # Pipe mode
            message = sys.stdin.read().strip()
            if message:
                history = []
                adv_client.chat_with_context(message, history, system_prompt)
                print()
        else:
            # Interactive mode
            print()
            adv_client.interactive_with_commands(system_prompt)

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted.{Colors.RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
