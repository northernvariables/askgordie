---
name: gordie-voice-testing
description: Acceptance test harness for Gordie Voice — representative queries, latency SLOs, response validation
---

# Gordie Voice Testing

## Test Suites
Use the `canadagpt-voice-testing` MCP server or run manually.

### MP Lookup (3 queries)
- "Who is the member of parliament for Ottawa Centre?"
- "Who is the MP for Vancouver Granville?"
- "Who represents London West?"
- **Expected**: Response names the correct MP, includes riding name
- **SLO**: < 3s end-to-end (wake to first audio)

### Bill Search (3 queries)
- "What is Bill C-21 about?"
- "What bills are currently before the Senate?"
- "Has Bill C-11 received royal assent?"
- **Expected**: Correct bill details, status, sponsor

### General Knowledge (4 queries)
- "Who is the current Prime Minister of Canada?"
- "How many provinces and territories does Canada have?"
- "When is the next federal election?"
- **Expected**: Factually correct, concise

### Stress Test (3 queries)
- Complex multi-part questions testing streaming, long responses, truncation
- **Expected**: Response shaped correctly for voice, truncated at max_response_words with "I'll send the full details to your screen"

## Latency SLOs
| Stage | Target | Acceptable |
|-------|--------|------------|
| Wake detection | < 500ms | < 1s |
| STT (Deepgram) | < 1.2s | < 2s |
| STT (whisper_cpp) | < 3s | < 5s |
| CanadaGPT first token | < 2s | < 4s |
| TTS first audio | < 2.5s | < 4s |
| End-to-end | < 4s | < 8s |

## Response Shaper Tests
Run `pytest tests/test_shaper.py` — covers:
- Markdown stripping (headers, bold, italic, code, links)
- Citation handling (strip vs. spoken)
- URL handling
- List-to-ordinal conversion
- Truncation
- Sentence chunking

## Manual Demo Script
1. Say "Hey Gordie" → should respond within 500ms
2. "Who is the current Prime Minister?" → spoken answer within 4s
3. Wait for follow-up prompt → say "Who is the MP for my riding?"
4. Say "record my opinion" → recording flow starts
5. Test barge-in: say "Hey Gordie" while Gordie is speaking → should interrupt
