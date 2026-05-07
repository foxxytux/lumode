# Lumo API Technical Reference

## Overview

This document describes the Lumo API endpoints and protocols used by the CLI.

**Status**: Beta/Internal API - Subject to change

## Authentication

### Methods

1. **Bearer Token (Primary)**
   - Header: `Authorization: Bearer <access_token>`
   - Extracted from Firefox cookies (`AUTH-<uid>`)

2. **Session Cookies (Fallback)**
   - Firefox maintains session cookies
   - Automatically included if Bearer auth fails

### Headers Required

```
x-pm-uid: <user-id>
Authorization: Bearer <access-token>
x-pm-appversion: web-lumo@1.4.0.5
Content-Type: application/json
```

### Token Extraction

Tokens are extracted from Firefox profile:
- **Location**: `~/.mozilla/firefox/*/cookies.sqlite`
- **UID**: Extracted from cookie name `AUTH-<uid>`
- **Token**: Value of `AUTH-<uid>` cookie
- **Refresh Token**: Parsed from `REFRESH-<uid>` cookie (JSON encoded)

## API Endpoints

### Base URL

```
https://lumo.proton.me/api
```

### Chat Endpoint

```
POST /ai/v1/chat
```

**Request Format:**

```json
{
  "Prompt": [
    {
      "Role": "system",
      "Content": "Optional system message"
    },
    {
      "Role": "user",
      "Content": "User message"
    }
  ]
}
```

**Request Field Details:**

- **Prompt** (array, required): Array of message objects
  - **Role** (string): One of `system`, `user`, `assistant`
  - **Content** (string): Message text

**Response Format:**

Server-Sent Events (SSE) stream with JSON lines:

```
data: {"type": "token_data", "value": "Hello", "target": "message"}
data: {"type": "token_data", "value": " world", "target": "message"}
data: {"type": "done"}
```

**Response Message Types:**

| Type | Description |
|------|-------------|
| `token_data` | Streaming text token |
| `done` | Conversation complete |
| `error` | Error message |
| `queued` | Request queued |
| `ingesting` | Processing |
| `harmful` | Content filtered |
| `rejected` | Request rejected |
| `timeout` | Request timed out |

**Response Fields:**

- **type** (string): Message type
- **value** (string): Token text (for `token_data`)
- **target** (string): Usually `"message"`
- **message** (string): Error message (for `error` type)

## Error Handling

### HTTP Status Codes

| Code | Meaning | Solution |
|------|---------|----------|
| 200 | Success | Normal response with SSE stream |
| 400 | Bad Request | Invalid JSON/parameters |
| 401 | Unauthorized | Token expired - refresh or re-login |
| 403 | Forbidden | No API access - contact support |
| 429 | Rate Limited | Too many requests - wait and retry |
| 500 | Server Error | API issue - retry after delay |
| 503 | Unavailable | Maintenance - check back later |

### Error Response Format

```json
{
  "Code": 2001,
  "Error": "Error message",
  "Details": {}
}
```

## Encryption (Optional)

Lumo supports end-to-end encryption (U2L - User to Lumo):

- **Type**: GPG encryption
- **Default Key**: Proton's public encryption key
- **Implementation**: Optional - not required for API access

## Rate Limiting

- **Limit**: Not officially documented (API is beta)
- **Headers**: `x-ratelimit-*` headers may be present
- **Recommended**: 1-5 second delays between requests

## Session Management

### Token Refresh

Tokens are valid for a session duration. To refresh:

1. Extract `REFRESH-<uid>` cookie from Firefox
2. Parse as JSON-encoded value:
   ```json
   {
     "GrantType": "refresh_token",
     "RefreshToken": "...",
     "ClientID": "WebLumo",
     "UID": "...",
     "ResponseType": "token"
   }
   ```
3. POST to `/auth/v4/refresh` with refresh cookie

**Note**: The CLI handles token expiration automatically by using Firefox's session management.

## Example Requests

### Basic Chat

```bash
curl -X POST https://lumo.proton.me/api/ai/v1/chat \
  -H "x-pm-uid: your-uid" \
  -H "Authorization: Bearer your-token" \
  -H "x-pm-appversion: web-lumo@1.4.0.5" \
  -H "Content-Type: application/json" \
  -d '{
    "Prompt": [
      {"Role": "user", "Content": "Hello"}
    ]
  }' \
  -N  # No buffer for SSE
```

### With System Prompt

```bash
curl -X POST https://lumo.proton.me/api/ai/v1/chat \
  -H "x-pm-uid: your-uid" \
  -H "Authorization: Bearer your-token" \
  -H "x-pm-appversion: web-lumo@1.4.0.5" \
  -H "Content-Type: application/json" \
  -d '{
    "Prompt": [
      {"Role": "system", "Content": "You are a helpful assistant"},
      {"Role": "user", "Content": "What is Python?"}
    ]
  }' \
  -N
```

### Multi-turn Conversation

```bash
# Request 1
curl ... -d '{
  "Prompt": [
    {"Role": "user", "Content": "What is Python?"}
  ]
}'

# Response: "Python is a programming language..."

# Request 2 (with history)
curl ... -d '{
  "Prompt": [
    {"Role": "user", "Content": "What is Python?"},
    {"Role": "assistant", "Content": "Python is a programming language..."},
    {"Role": "user", "Content": "Give me an example"}
  ]
}'
```

## Implementation Details

### Streaming

- **Protocol**: HTTP/2 with Server-Sent Events
- **Buffering**: Full buffering disabled (`-N` flag in curl)
- **Parsing**: Lines prefixed with `data: ` contain JSON

### Connection Pooling

The CLI uses connection pooling with retry logic:
- **Retries**: 3 attempts for transient failures
- **Backoff**: Exponential backoff (0.5s, 1s, 2s)
- **Timeout**: 120 seconds for streaming requests

### Headers

All requests include:
```
Accept-Encoding: gzip, deflate
User-Agent: Python-Requests/...
Connection: keep-alive
```

## Limitations (Beta API)

1. **No documented rate limits** - use conservative request rates
2. **API may change** - no backwards compatibility guarantees
3. **Access may be restricted** - beta testing phase
4. **SSE streaming only** - no chunked/partial responses
5. **No conversation storage** - responses not persisted server-side

## Security Considerations

1. **Token Storage**: Tokens live in Firefox's encrypted cookie store
2. **No Local Logging**: CLI doesn't cache tokens or conversations
3. **HTTPS Only**: All communication is encrypted in transit
4. **Zero-Knowledge**: Proton uses end-to-end encryption (default)
5. **No Tracking**: Lumo doesn't track conversations

## Related Specifications

- **HTTP/2**: RFC 7540
- **Server-Sent Events**: WHATWG standard
- **JSON**: RFC 8259
- **Proton API Standards**: Documented in Proton WebClients repo

## Debugging

Enable verbose logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Then use client normally
```

Check actual requests in Firefox DevTools:
1. Press F12
2. Go to Network tab
3. Filter to `api.proton.me` or `lumo.proton.me`
4. Watch POST requests to `/ai/v1/chat`
5. Check headers and response stream

## References

- **Lumo Web App**: https://github.com/ProtonMail/WebClients
- **Lumo Android**: https://github.com/ProtonLumo/android-lumo
- **Proton API Docs**: https://proton.me/api
- **Community Reverse-Engineering**: https://github.com/carlostkd/Lumo-Api
