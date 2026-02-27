# CLAUDE.md — Instructions for Claude Code

## Project

GitHub Repository Summarizer — A FastAPI service that takes a GitHub repo URL and returns an LLM-generated summary.

## Key Files to Read First

1. **SPEC.md** — Full technical specification. Read this BEFORE writing any code.
2. **PROGRESS.md** — Track your progress here. Update checkboxes as you complete tasks.
3. **CONVENTIONS.md** — Coding standards. Follow these consistently.
4. **TASK.md** — The original assignment from the course. Reference this for evaluation criteria and blocking requirements.

## Workflow

1. Read SPEC.md completely before starting
2. Work through phases in order (Phase 1 → 9)
3. After completing each phase's tasks, update PROGRESS.md checkboxes
4. If you make a design decision not covered in the spec, log it in PROGRESS.md Decisions Log
5. If you hit a blocker, log it in PROGRESS.md Issues Encountered
6. Verify each phase works before moving to the next

## Quick Reference

- **LLM Provider:** Nebius Token Factory (OpenAI-compatible API)
- **Base URL:** `https://api.tokenfactory.nebius.com/v1/`
- **Primary Model:** `Qwen/Qwen3-235B-A22B-Instruct-2507`
- **Map Model:** `meta-llama/Meta-Llama-3.1-8B-Instruct`
- **Framework:** FastAPI (async)
- **HTTP Client:** httpx (async)
- **API Key env var:** `NEBIUS_API_KEY`
- **Optional:** `GITHUB_TOKEN` for higher rate limits

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Test the endpoint
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'

# Health check
curl http://localhost:8000/health
```

## Important Constraints

- Never hardcode API keys
- All I/O operations must be async
- Use type hints on all functions
- Log at INFO level for request flow, DEBUG for details
- Handle all error cases with proper HTTP status codes
- The response JSON must have exactly: summary, technologies, structure
- Error responses must have exactly: status, message
