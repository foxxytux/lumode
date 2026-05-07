# Lumode - Privacy-First Lumo Coding Agent

Command-line tools for Proton's Lumo AI assistant, including `lumode`, a local coding-agent shell that works with the existing Lumo chat client.

## Features

- **Lumode coding agent** with local tool calls for files, shell commands, patches, and web context
- **Interactive chat** with streaming responses
- **Coding-focused prompts** optimized for development tasks
- **Multi-turn conversations** with conversation history
- **Named sessions** saved locally under `~/.config/lumode/sessions`
- **Polished slash commands** for context, tools, workspace navigation, and transcript export
- **Firefox authentication** - uses your existing Lumo session
- **Custom system prompts** for different use cases
- **Pipe-friendly** - works with stdin/stdout

## Installation

### Requirements

- Python 3.8+
- Firefox browser with Lumo session (logged in at https://lumo.proton.me)

### Setup

```bash
# Make executable
chmod +x lumode lumo_cli.py

# Install commands into ~/.local/bin
./install.sh
```

## Usage

### Lumode Coding Agent

Start the coding-agent shell:

```bash
./lumode
```

Useful interactive commands:

```text
/tree . 2             Add a directory tree as context
/add src/app.py       Add a file as context
/run pytest -q        Run a command and add output as context
/search query         Search the web and add results as context
/fetch https://...    Fetch URL text and add it as context
/apply                Apply a unified diff from the last Lumo response
/sessions             List saved sessions
/save bugfix          Save the current session
/load bugfix          Load a saved session
/new scratch          Start a blank session
/rename bugfix-v2     Rename the active saved session
/delete scratch       Delete a saved session
/export notes.md      Export transcript as Markdown
/pwd                  Show the active workspace directory
/cd ../other-repo      Change workspace directory
/clear                Clear chat history and pending context
/quit                 Exit
```

Lumode also exposes these tools to Lumo automatically. When Lumo needs local context it can call `read_file`, `list_tree`, `run_shell`, `apply_patch`, `web_search`, or `fetch_url`; Lumode executes the tool and feeds the result back into the conversation.

Single-turn examples:

```bash
./lumode --file app.py "Review this file and return a unified diff"
./lumode --tree . --run "pytest -q" "Fix the failing tests"
./lumode --search "latest Python release" "Summarize the current release"
./lumode --apply --file bug.py "Return and apply a patch for this bug"
./lumode --session bugfix "Continue the previous fix"
./lumode --save-session review --file app.py "Review this file"
```

Saved sessions contain chat history, pending context, last response, and the active workspace directory. They do not contain Lumo auth tokens.

### Interactive Mode

Start the basic chat client:

```bash
./lumo_cli.py
```

Use `/clear` to clear conversation history, `/quit` to exit.

### Coding Assistant Mode

```bash
./lumo_cli.py -c "Write a Python function that reverses a string"
```

Or with a custom system prompt:

```bash
./lumo_cli.py -p "You are an expert Rust programmer" "Explain ownership in Rust"
```

### Pipe Mode

```bash
echo "Fix this code: for i in range(10) print(i)" | ./lumo_cli.py -c

# Or use with other CLI tools
cat debug.log | ./lumo_cli.py "What's wrong with this?"
```

## Authentication

### Option 1: Firefox Session (Default)

1. Log in to Lumo at https://lumo.proton.me
2. Run the CLI - it will automatically extract your session from Firefox

### Option 2: Manual Token

If Firefox auth doesn't work, you can provide credentials manually:

```bash
# Get your UID and token from Firefox DevTools (Network tab, look for x-pm-uid header)
export LUMO_UID="your-uid-here"
export LUMO_TOKEN="your-token-here"
export LUMO_REFRESH_TOKEN="optional-refresh-token"

./lumo_cli.py
```

## Troubleshooting

### "Authentication failed - token may be expired"

1. Open https://lumo.proton.me in Firefox to refresh your session
2. Run the CLI again

### "No AUTH cookie found"

Make sure you're logged into Lumo in Firefox:
1. Visit https://lumo.proton.me in your default Firefox profile
2. Log in if needed
3. Run the CLI again

### API Access Issues

The Lumo API is currently in beta testing. If you see permission errors:
- Make sure you have API access enabled in your Lumo account
- Contact Proton support if you believe you should have access

## Examples

### Quick Code Review

```bash
./lumo_cli.py -c << 'EOF'
Review this function:

def calculate_total(items):
    total = 0
    for i in range(len(items)):
        total = total + items[i]
    return total

What could be improved?
EOF
```

### Debugging

```bash
cat error_output.txt | ./lumo_cli.py -c "Why is this error happening?"
```

### Learning

```bash
./lumo_cli.py -p "Explain concepts simply, provide working examples"
"How do async/await work in JavaScript?"
```

## Keyboard Shortcuts (Interactive Mode)

- `Ctrl+C` or `/quit` - Exit chat
- `/clear` - Clear conversation history
- `/q` - Quick exit
- `/help` - Show the complete slash command list

## Environment Variables

- `LUMO_UID` - Your Proton user ID (from auth cookie)
- `LUMO_TOKEN` - Your access token (from auth cookie)
- `LUMO_REFRESH_TOKEN` - Your refresh token (optional)

## API Details

- **Base URL**: `https://lumo.proton.me/api`
- **Endpoint**: POST `/ai/v1/chat`
- **Auth**: Bearer token via `Authorization` header + `x-pm-uid` header
- **Streaming**: Server-Sent Events (SSE)

## License

MIT - Use responsibly and in accordance with Proton's terms of service.

## Disclaimer

This is an unofficial Lumo client. Lumo is developed by Proton and protected by their privacy policies. By using this tool, you agree to Proton's terms of service and understand that this is a reverse-engineered implementation that may break with API changes.
