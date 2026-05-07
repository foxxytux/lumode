# Lumo CLI - Project Structure

## Overview

This is a complete command-line interface for Proton's Lumo AI assistant, with a focus on developer workflows and coding tasks.

## File Structure

```
lumode/
├── README.md                 # Main documentation & examples
├── GETTING_STARTED.md        # Quick start guide (start here!)
├── SETUP.md                  # Detailed setup instructions
├── API.md                    # Technical API reference
├── PROJECT_STRUCTURE.md      # This file
│
├── lumo_cli.py              # Basic CLI implementation
├── lumo_advanced.py         # Advanced CLI with file context
│
├── test_setup.py            # Setup verification script
├── install.sh               # Installation helper (optional)
│
├── requirements.txt         # Python dependencies
├── .gitignore              # Git ignore rules
│
└── [You create these]
    ├── conversations/      # (Optional) Save conversations here
    └── scripts/            # (Optional) Custom shell scripts
```

## Core Files

### 1. **lumo_cli.py** (450 lines)
**What:** Basic Lumo CLI with streaming chat
**Features:**
- Interactive chat mode
- Single message mode
- Pipe input support
- Custom system prompts
- Firefox auth integration

**Usage:**
```bash
./lumo_cli.py -c "Your question"
./lumo_cli.py -p "Custom prompt" "Question"
echo "question" | ./lumo_cli.py
```

**Key Classes:**
- `LumoClient` - API communication
- `Colors` - Terminal formatting
- `extract_firefox_cookies()` - Auth extraction
- `create_session()` - HTTP session setup

### 2. **lumo_advanced.py** (350 lines)
**What:** Extended CLI with advanced coding features
**Features:**
- All of lumo_cli.py
- Add file context (`/file`)
- Directory structure (`/dir`)
- Command execution (`/exec`)
- Context management

**Usage:**
```bash
./lumo_advanced.py -c
# Then in interactive mode:
/file debug.py
/dir src
/exec "npm test"
```

**Key Classes:**
- `AdvancedLumoClient` - Extended functionality
- File context management
- Command execution with output capture

### 3. **test_setup.py** (200 lines)
**What:** Setup verification utility
**Checks:**
- Python version (3.8+)
- Dependencies installed
- Firefox profiles exist
- Cookies database accessible
- Lumo session in Firefox
- CLI scripts executable

**Usage:**
```bash
python3 test_setup.py
```

**Exit Codes:**
- 0 = All checks passed
- 1 = Some checks failed

## Documentation Files

### **README.md** (Main Guide)
- Feature overview
- Installation instructions
- Basic usage examples
- Troubleshooting
- Environment variables
- Advanced examples

**When to read:** First-time setup, looking for examples

### **GETTING_STARTED.md** (Quick Start)
- 5-minute setup guide
- First queries
- Examples by use case
- Tips and tricks
- Common questions
- Next steps

**When to read:** First time, want quick results

### **SETUP.md** (Detailed Setup)
- Prerequisites
- Step-by-step installation
- File overview
- Basic usage
- Advanced usage
- Development info

**When to read:** Setting up for first time, troubleshooting

### **API.md** (Technical Reference)
- Authentication details
- API endpoints
- Request/response formats
- Error codes
- Rate limiting
- Examples
- Encryption support

**When to read:** Integrating with other tools, developing custom clients

### **PROJECT_STRUCTURE.md** (This File)
- File descriptions
- Component overview
- Architecture notes
- Development guide

**When to read:** Understanding the codebase

## Configuration Files

### **requirements.txt**
Python package dependencies:
- `requests>=2.28.0` - HTTP requests
- `urllib3>=1.26.0` - Connection pooling

**Status:** Dependencies already available in most Python installations

### **.gitignore**
Standard Python ignores:
- `__pycache__/`, `*.pyc`
- Virtual environments
- IDE files (`.vscode/`, `.idea/`)
- Test coverage
- Local config files

### **install.sh**
Optional installation helper:
- Creates symlinks in `~/.local/bin/`
- Sets up `lumo` and `lumo-adv` commands
- Checks PATH configuration

**Usage:** `bash install.sh`

## Architecture

### Authentication Flow
```
User runs CLI
    ↓
CLI extracts auth from Firefox cookies.sqlite
    ↓
Creates requests.Session with auth headers
    ↓
Sends POST to /ai/v1/chat
    ↓
Receives SSE stream
    ↓
Parses JSON lines and outputs tokens
```

### Key Components

**1. Cookie Extraction**
- Reads Firefox's SQLite database
- Copies to temp file (Firefox locks original)
- Extracts UID and access token
- Falls back to env vars if available

**2. API Communication**
- Uses `requests` library with retry strategy
- HTTP/2 with Server-Sent Events
- Streaming responses parsed line-by-line
- Automatic error handling

**3. SSE Parsing**
- Reads stream buffered (lines end with `\n`)
- Filters for lines starting with `data: `
- Parses JSON payload
- Yields individual tokens
- Stops on `"type": "done"`

**4. User Interface**
- Interactive mode with command prompt
- Single message batch mode
- Pipe/stdin support
- Terminal colors (ANSI)
- Help system

## Data Flow

### Request
```json
{
  "Prompt": [
    {"Role": "system", "Content": "optional prompt"},
    {"Role": "user", "Content": "user message"}
  ]
}
```

### Response (SSE Stream)
```
data: {"type": "token_data", "value": "token"}
data: {"type": "token_data", "value": " text"}
data: {"type": "done"}
```

## Extension Points

### Adding New Commands (Advanced CLI)

```python
elif cmd == "/mycommand":
    result = self.my_function()
    print(f"Result: {result}")
```

### Custom System Prompts

```bash
./lumo_cli.py -p "Your custom system message" "question"
```

### Integration with Other Tools

```python
from lumo_cli import LumoClient, extract_firefox_cookies

auth = extract_firefox_cookies()
client = LumoClient(auth)

for token in client.chat([{"Role": "user", "Content": "hello"}]):
    print(token, end="", flush=True)
```

## Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| First run | 2-3s | Auth extraction, initial connection |
| Subsequent runs | 1s | Connection pooling |
| Single query | 5-15s | Response time varies |
| Stream parsing | Real-time | Tokens printed as received |
| Large files | 2-5s | Context preparation |

## Known Limitations

1. **No conversation storage** - History kept in memory only
2. **Token expiration** - Tokens last ~30 days (browser session)
3. **No token refresh automation** - Uses Firefox's session management
4. **No API rate docs** - Beta API, limits not documented
5. **SSE only** - No alternative response formats
6. **Single threaded** - Requests processed sequentially

## Development Notes

### Code Style
- Python 3.8+ syntax
- Type hints in function signatures
- Docstrings for public methods
- ANSI color codes for UI
- No external dependencies beyond requests/urllib3

### Testing
```bash
python3 test_setup.py          # Verify setup
./lumo_cli.py -c "test"        # Manual test
```

### Debugging
```bash
# Check Firefox cookies
python3 << 'EOF'
from lumo_cli import extract_firefox_cookies
auth = extract_firefox_cookies()
print(auth)
EOF

# Check API connectivity
curl -H "Authorization: Bearer <token>" \
  https://lumo.proton.me/api/ai/v1/chat
```

## Dependencies

**Runtime:**
- Python 3.8+
- `requests` - HTTP library
- `urllib3` - Connection pooling
- Firefox - For authentication

**Optional:**
- `bash` - For install.sh script

## Files Generated at Runtime

- Temp cookies database (auto-cleaned)
- Chat history (memory only, not persisted)
- No log files

## Security Considerations

1. **Token Security**
   - Tokens extracted from Firefox's encrypted store
   - Not stored by CLI
   - Only in memory during session

2. **Firefox Access**
   - Requires read access to cookies.sqlite
   - Standard user permissions sufficient

3. **API Communication**
   - HTTPS only
   - Certificate validation enabled
   - No proxy bypasses

4. **Input Validation**
   - User messages passed as-is to API
   - File content read and passed as-is
   - No sanitization (API handles it)

## Future Enhancements

**Potential additions:**
- Conversation persistence (SQLite)
- Multiple model selection
- Streaming to file
- Batch processing (multiple files)
- Config file support
- Shell integration (completion)
- Custom encoding/decryption
- Rate limiting config

## Contributing

To contribute:
1. Maintain current code style
2. Add type hints
3. Test with `test_setup.py`
4. Update relevant docs
5. Keep dependencies minimal

## License

MIT - See individual files for headers

## Support

**For setup issues:** Run `python3 test_setup.py`

**For usage questions:** See README.md and GETTING_STARTED.md

**For bugs:** Check error messages, they're quite detailed

**For API issues:** See API.md for technical details
