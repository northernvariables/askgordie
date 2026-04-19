"""CanadaGPT Voice Testing MCP Server.

Test harness for the Gordie Voice appliance:
- Run acceptance test suites with representative Canadian queries
- Compare response quality across providers
- Benchmark end-to-end latency
"""

from __future__ import annotations

import json
import os
import time

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("canadagpt-voice-testing")

GORDIE_PERSONA_URL = os.environ.get("GORDIE_PERSONA_URL", "http://127.0.0.1:8080")

# Representative test queries covering key CanadaGPT domains
TEST_SUITES = {
    "mp_lookup": [
        "Who is the member of parliament for Ottawa Centre?",
        "Who is the MP for Vancouver Granville?",
        "Who represents London West?",
    ],
    "bill_search": [
        "What is Bill C-21 about?",
        "What bills are currently before the Senate?",
        "Has Bill C-11 received royal assent?",
    ],
    "hansard": [
        "What was discussed in the House of Commons yesterday?",
        "What did the Prime Minister say about housing last week?",
    ],
    "general_knowledge": [
        "Who is the current Prime Minister of Canada?",
        "How many provinces and territories does Canada have?",
        "When is the next federal election?",
        "What is the capital of Canada?",
    ],
    "statistics": [
        "What is Canada's population?",
        "What is the current unemployment rate in Canada?",
        "What is Canada's GDP?",
    ],
    "stress_test": [
        "Give me a detailed summary of the last five bills introduced in Parliament",
        "Compare the voting records of the top three parties on environmental legislation",
        "What are the key differences between the federal and provincial healthcare systems?",
    ],
}


@server.tool()
async def list_test_suites() -> list[TextContent]:
    """List available test suites and their queries."""
    summary = {}
    for name, queries in TEST_SUITES.items():
        summary[name] = {"query_count": len(queries), "queries": queries}
    return [TextContent(type="text", text=json.dumps(summary, indent=2))]


@server.tool()
async def run_test_suite(suite_name: str) -> list[TextContent]:
    """Run a named test suite against the CanadaGPT API via Gordie's endpoint.

    Returns response text, latency, and character count for each query.
    """
    if suite_name not in TEST_SUITES:
        return [TextContent(type="text", text=f"Unknown suite '{suite_name}'. Available: {list(TEST_SUITES.keys())}")]

    queries = TEST_SUITES[suite_name]
    results = []

    api_url = os.environ.get("CANADAGPT_API_URL", "https://api.canadagpt.ca/v1/chat")
    api_key = os.environ.get("CANADAGPT_API_KEY", "")

    client = httpx.Client(
        timeout=30.0,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )

    for query in queries:
        start = time.monotonic()
        try:
            resp = client.post(api_url, json={"query": query})
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("response", data.get("answer", str(data)))
            elapsed_ms = (time.monotonic() - start) * 1000

            results.append({
                "query": query,
                "status": "pass",
                "latency_ms": round(elapsed_ms),
                "response_length": len(answer),
                "response_preview": answer[:200],
                "has_content": len(answer) > 20,
            })
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            results.append({
                "query": query,
                "status": "fail",
                "latency_ms": round(elapsed_ms),
                "error": str(e),
            })

    passed = sum(1 for r in results if r["status"] == "pass")
    avg_latency = sum(r["latency_ms"] for r in results) / len(results) if results else 0

    return [TextContent(type="text", text=json.dumps({
        "suite": suite_name,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "avg_latency_ms": round(avg_latency),
        "results": results,
    }, indent=2))]


@server.tool()
async def benchmark_latency(n_queries: int = 10) -> list[TextContent]:
    """Benchmark CanadaGPT API latency with n repeated simple queries."""
    n_queries = min(n_queries, 50)
    query = "Who is the current Prime Minister of Canada?"

    api_url = os.environ.get("CANADAGPT_API_URL", "https://api.canadagpt.ca/v1/chat")
    api_key = os.environ.get("CANADAGPT_API_KEY", "")

    client = httpx.Client(
        timeout=30.0,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )

    latencies = []
    errors = 0
    for i in range(n_queries):
        start = time.monotonic()
        try:
            resp = client.post(api_url, json={"query": query})
            resp.raise_for_status()
            elapsed = (time.monotonic() - start) * 1000
            latencies.append(elapsed)
        except Exception:
            errors += 1

    latencies.sort()
    n = len(latencies)

    return [TextContent(type="text", text=json.dumps({
        "query": query,
        "total_requests": n_queries,
        "successful": n,
        "errors": errors,
        "latency_ms": {
            "min": round(latencies[0], 1) if latencies else 0,
            "p50": round(latencies[n // 2], 1) if latencies else 0,
            "p95": round(latencies[int(n * 0.95)], 1) if latencies else 0,
            "p99": round(latencies[int(n * 0.99)], 1) if latencies else 0,
            "max": round(latencies[-1], 1) if latencies else 0,
        },
    }, indent=2))]


@server.tool()
async def test_shaper_with_sample(markdown_text: str) -> list[TextContent]:
    """Test the ResponseShaper with a sample markdown string — shows what would be spoken."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent.parent / "src"))

    from gordie_voice.canadagpt.shaper import ResponseShaper
    from gordie_voice.config import ShaperConfig

    shaper = ResponseShaper(ShaperConfig())
    sentences = shaper.shape(markdown_text)

    return [TextContent(type="text", text=json.dumps({
        "input_length": len(markdown_text),
        "output_sentences": len(sentences),
        "sentences": sentences,
    }, indent=2))]


def main():
    import asyncio
    asyncio.run(stdio_server(server))


if __name__ == "__main__":
    main()
