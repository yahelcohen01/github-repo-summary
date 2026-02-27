# Progress Tracker

## Status Legend
- ⬜ Not started
- 🔄 In progress
- ✅ Complete
- ❌ Blocked
- 🐛 Has known issues

---

## Phase Checklist

### Phase 1: Scaffold
- ✅ Create project directory structure
- ✅ `app/__init__.py`
- ✅ `app/config.py` — env vars, constants
- ✅ `app/schemas.py` — Pydantic models
- ✅ `app/main.py` — FastAPI app + health check
- ✅ `requirements.txt`
- ✅ `.env.example`
- ✅ `.gitignore`
- ⬜ **Verify:** `uvicorn app.main:app` starts, `/health` returns 200

### Phase 2: GitHub Integration
- ✅ `parse_github_url()` — extract owner/repo
- ✅ `get_default_branch()` — repo metadata
- ✅ `get_repo_tree()` — recursive tree fetch
- ✅ `get_file_content()` — single file fetch with base64 decode
- ✅ `fetch_files_parallel()` — batch fetch with asyncio.gather (in main.py)
- ✅ Error handling: 404, 403, network errors
- ✅ Optional GITHUB_TOKEN support
- ⬜ **Verify:** Can fetch tree + files from `psf/requests`

### Phase 3: File Scoring
- ✅ `score_file()` — scoring logic per spec
- ✅ `filter_and_rank()` — sort and filter
- ✅ Skip rules: binary, lock, generated, vendored
- ⬜ **Verify:** Running against `psf/requests` tree gives sensible ranking

### Phase 4: Context Builder
- ✅ `estimate_tokens()` — character-based
- ✅ `build_context()` — assemble tree + file contents
- ✅ `needs_map_reduce()` — check against budget
- ✅ Token budget enforcement (stop adding files when full)
- ⬜ **Verify:** Context string is well-formatted, under budget

### Phase 5: LLM Integration
- ✅ `prompts.py` — all prompt templates
- ✅ `call_llm()` — base LLM call with JSON parsing
- ✅ `summarize_single()` — single-call path
- ✅ `summarize_map_reduce()` — parallel map + reduce
- ✅ JSON response validation
- ✅ Retry on parse failure
- ⬜ **Verify:** Returns valid structured response for a test prompt

### Phase 6: Wire Together
- ✅ `POST /summarize` endpoint — full flow
- ✅ Error response formatting
- ✅ Timeout handling
- ⬜ **Verify:** Full curl test returns valid summary

### Phase 7: Error Handling & Edge Cases
- ✅ Invalid URL → 400
- ✅ Private repo → 404
- ✅ Empty repo → graceful response
- ✅ GitHub rate limit → 429
- ✅ LLM failure → 502
- ✅ Timeout → 504
- ✅ Truncated tree (very large repo) → handle gracefully

### Phase 8: Documentation
- ✅ README.md with setup instructions
- ✅ Model choice explanation
- ✅ Approach explanation
- ✅ Environment variables table

### Phase 9: Final Testing
- ⬜ Test: `psf/requests` (medium Python) — requires NEBIUS_API_KEY
- ⬜ Test: `expressjs/express` (medium JS) — requires NEBIUS_API_KEY
- ⬜ Test: `torvalds/linux` (massive — map-reduce) — requires NEBIUS_API_KEY
- ⬜ Test: `kelseyhightower/nocode` (minimal) — requires NEBIUS_API_KEY
- ✅ Test: invalid URL → 400 `{"status": "error", "message": "..."}`
- ✅ Test: private/non-existent repo URL → 404 `{"status": "error", "message": "..."}`
- ✅ Verify no hardcoded API keys
- ✅ Verify requirements.txt complete

---

## Decisions Log

| # | Decision | Reasoning | Date |
|---|----------|-----------|------|
| 1 | `create_client()` uses `@asynccontextmanager` instead of returning bare client | Ensures proper async cleanup of httpx connection pool | 2026-02-27 |
| 2 | Parallel file fetching via `asyncio.gather` in `main.py` rather than a separate function | Keeps `main.py` as the orchestration layer; `github_client.py` stays single-responsibility | 2026-02-27 |
| 3 | `build_tree_and_readme()` added to `context_builder.py` | Needed for the reduce step of map-reduce; not in original spec but required by the flow | 2026-02-27 |
| 4 | Score 0 lock files use case-insensitive filename comparison | `Gemfile.lock` vs `gemfile.lock` — normalizing to lowercase prevents misses | 2026-02-27 |

---

## Issues Encountered

| # | Issue | Status | Resolution |
|---|-------|--------|------------|
| 1 | | | |

---

## Notes

- Read SPEC.md before starting each phase
- Update this file after completing each checkbox
- Log any decision that deviates from the spec in the Decisions Log
- If blocked, document the issue and try an alternative approach
