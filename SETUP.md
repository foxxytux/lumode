# Lumo CLI Setup Guide

## Quick Start

### 1. Prerequisites

- Python 3.8 or later
- Firefox browser with Lumo session
- Active Lumo account at https://lumo.proton.me

### 2. Installation

```bash
# Navigate to the lumode directory
cd ~/workspace/lumode

# Verify Python is available
python3 --version

# (Optional) Create an alias for convenience
alias lumo='python3 ~/workspace/lumode/lumo_cli.py'
alias lumo-adv='python3 ~/workspace/lumode/lumo_advanced.py'
```

### 3. Authentication

The CLI automatically uses your Firefox session. Make sure:

1. Open https://lumo.proton.me in Firefox
2. Log in with your Proton account
3. The CLI will extract your auth tokens from Firefox cookies

## Files Overview

### Core Files

- **`lumo_cli.py`** - Basic CLI with streaming chat
  - Interactive mode
  - Single message mode
  - Pipe mode
  - Custom system prompts

- **`lumo_advanced.py`** - Advanced features
  - Add file context (`/file`)
  - Directory structure (`/dir`)
  - Command execution output (`/exec`)
  - Better for coding workflows

### Documentation

- **`README.md`** - User guide and examples
- **`SETUP.md`** - This file, installation instructions
- **`API.md`** - Technical details about Lumo API

### Configuration

- **`requirements.txt`** - Python dependencies (pre-installed)
- **`install.sh`** - Installation helper script

## Basic Usage

### Interactive Chat

```bash
./lumo_cli.py
```

Commands in interactive mode:
- `/clear` - Clear conversation history
- `/quit` - Exit
- Ctrl+C - Interrupt

### Coding Assistant

```bash
./lumo_cli.py -c "Write a Python function that..."
```

### With Custom Prompt

```bash
./lumo_cli.py -p "You are a Rust expert" "Explain ownership"
```

### Advanced Mode with File Context

```bash
./lumo_advanced.py -c

# Inside interactive mode, use:
/file debug.py           # Add a file
/dir src                 # Add directory structure
/exec "npm test"         # Add command output
/context                 # Show current context
```

## Environment Variables (Optional)

If Firefox auth doesn't work, manually provide credentials:

```bash
export LUMO_UID="your-uid-from-firefox"
export LUMO_TOKEN="your-token-from-firefox"
export LUMO_REFRESH_TOKEN="optional-refresh-token"

./lumo_cli.py
```

### How to Get These Values

1. Open Firefox Developer Tools (F12)
2. Go to Network tab
3. Open https://lumo.proton.me
4. Look for any API request
5. Find these headers:
   - `x-pm-uid` → Use as LUMO_UID
   - `Authorization: Bearer ...` → Use the token as LUMO_TOKEN

## Troubleshooting

### Issue: "No AUTH cookie found"

**Solution:**
1. Close this terminal
2. Open https://lumo.proton.me in Firefox
3. Log in if needed
4. Come back to terminal and try again

### Issue: "Authentication failed - token may be expired"

**Solution:**
1. Visit https://lumo.proton.me in Firefox to refresh the session
2. Run the CLI again

### Issue: "API error 403: Access denied"

**Solution:**
- The Lumo API is in beta. You may not have API access.
- Contact Proton support if you believe you should have access
- The CLI works best when Lumo is available in your browser first

### Issue: "Connection refused or SSL error"

**Solution:**
- Check your internet connection
- Try again - servers may be temporarily unavailable
- Verify firewall/VPN settings allow access to lumo.proton.me

## Advanced Usage

### Pipe Example

```bash
# Code review
cat myfile.py | ./lumo_cli.py -c "Review this code"

# Debug logs
cat error.log | ./lumo_cli.py -c "What's wrong?"

# Chain with other tools
git diff | ./lumo_cli.py -c "Explain these changes"
```

### Multiple Files

```bash
./lumo_advanced.py -c --file server.py --file client.py \
  "Why aren't these communicating properly?"
```

### With Build Output

```bash
./lumo_advanced.py --exec "cargo build 2>&1" \
  "Why is my Rust project failing?"
```

### Learning Mode

```bash
./lumo_cli.py -p "You are a patient teacher. Use examples and explain step-by-step" \
  "How does Docker work?"
```

## Performance Tips

- **First request slower**: Auth cookie extraction takes a moment
- **Long conversations**: Keep history under 20 turns for best performance
- **File context**: Large files (>50KB) may slow down responses
- **Streaming**: Responses stream in real-time, press Ctrl+C to stop

## Privacy & Security

- **Auth tokens**: Extracted from your local Firefox browser
- **Conversations**: Sent to Proton's Lumo API (zero-knowledge encryption applied by Lumo)
- **No logging**: This CLI doesn't log or store your conversations
- **Local-first**: Everything is processed locally before being sent to API

## Development

To extend or modify the CLI:

```python
# Import the client
from lumo_cli import LumoClient, extract_firefox_cookies

# Use in your code
auth = extract_firefox_cookies()
client = LumoClient(auth)

# Stream chat
for token in client.chat([{"Role": "user", "Content": "Hello"}]):
    print(token, end="", flush=True)
```

## Getting Help

1. Check `README.md` for examples
2. Run with `--help`: `./lumo_cli.py --help`
3. Use `/help` in interactive mode (advanced version)
4. Check error messages - they provide guidance

## What's Next?

- Try basic mode first: `./lumo_cli.py -c`
- Explore advanced mode: `./lumo_advanced.py -c`
- Create an alias for frequent use
- Check README.md for more examples
