---
name: connexxia-python-project
description: Connexxia Python project conventions — uv, ruff, pytest, pydantic settings, structlog, pyproject.toml
---

# Connexxia Python Project Standards

## Package Manager
- **uv** for dependency management and venv creation
- `uv venv`, `uv pip install`, `uv run`

## Project Structure
```
project-name/
├── pyproject.toml          # Single source of truth for metadata + deps
├── .env.example            # Template for environment variables
├── config/default.yaml     # Runtime config (Pydantic loads YAML + env)
├── src/package_name/       # Source layout under src/
│   ├── __init__.py
│   ├── __main__.py         # Entry point
│   ├── config.py           # Pydantic BaseSettings + nested BaseModel configs
│   └── ...
├── tests/
├── systemd/                # If it's a service
└── scripts/                # Setup, install, deploy helpers
```

## pyproject.toml
- Build backend: `hatchling`
- `[tool.hatch.build.targets.wheel] packages = ["src/package_name"]` with `sources = ["src"]`
- Ruff for linting: `target-version = "py311"`, `line-length = 100`
- Pytest: `testpaths = ["tests"]`

## Configuration
- **Pydantic Settings** for env vars → config mapping
- **YAML** for complex nested config (audio, providers, etc.)
- `load_settings()` loads YAML first, env vars override
- No env_prefix unless all vars are genuinely prefixed

## Logging
- **structlog** everywhere, never `print()`
- JSON output in production, colored console in dev (detect via `sys.stderr.isatty()`)
- Key events: `{module}_{action}` naming (e.g., `canadagpt_response`, `wake_detected`)

## Error Handling
- Log with `log.exception()` for full tracebacks
- Surface user-facing errors via TTS/display, not raw exceptions
- Retry with exponential backoff for external APIs (1 retry default)

## Type Hints
- `from __future__ import annotations` in every file
- `TYPE_CHECKING` guard for import-heavy type hints
- ABCs for swappable providers with factory functions

## Testing
- pytest with mocks for hardware-dependent code
- Test the response shaper thoroughly (most edge cases live there)
- Mock all external services (Deepgram, ElevenLabs, CanadaGPT, Supabase)
