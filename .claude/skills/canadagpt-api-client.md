---
name: canadagpt-api-client
description: CanadaGPT API patterns — auth, streaming, error handling, response shapes. Reusable across Connexxia projects.
---

# CanadaGPT API Client Patterns

## Authentication
```
Authorization: Bearer {CANADAGPT_API_KEY}
Content-Type: application/json
```

## Request Shape (TBD — Matthew to confirm)
```json
POST {CANADAGPT_API_URL}
{
    "query": "Who is the current Prime Minister?",
    "stream": true  // optional, for SSE streaming
}
```

## Response Shape (TBD)
```json
{
    "response": "Mark Carney is the current Prime Minister...",
    "sources": [{"title": "...", "url": "..."}]
}
```

## Streaming (SSE)
When `stream: true`, response is Server-Sent Events:
```
data: {"token": "Mark"}
data: {"token": " Carney"}
data: {"token": " is"}
...
data: [DONE]
```

Client should buffer tokens and yield at sentence boundaries for TTS.

## Error Handling
- **Timeout** (30s default): Single retry with exponential backoff
- **5xx**: Retry once, then surface to user via TTS: "I couldn't reach CanadaGPT, please try again"
- **401**: API key invalid — log error, don't retry
- **429**: Rate limited — back off, don't hammer

## Fact-Check Mode
Send claim extraction and verification prompts through the same API:
- Prompt engineering handles the JSON response format
- Parse JSON from response, falling back to regex extraction if markdown-wrapped

## Integration Points
- `src/gordie_voice/canadagpt/client.py` — the main client
- `src/gordie_voice/canadagpt/shaper.py` — markdown-to-voice transformation
- `src/gordie_voice/factcheck/checker.py` — fact-check prompts via the same API
