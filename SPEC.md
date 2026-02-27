# GitHub Repository Summarizer — Technical Specification

## Project Overview

Build a FastAPI service with a single endpoint `POST /summarize` that takes a GitHub repository URL and returns an LLM-generated summary including: what the project does, technologies used, and project structure.

## Architecture Decision (Already Made)

**Approach B: GitHub REST API (Tree + Selective Blob Fetch)**

1. Fetch the full file tree via GitHub's Git Trees API (one call)
2. Score and rank files by informativeness
3. Fetch only the top-N most relevant files
4. Send assembled context to LLM
5. If context exceeds token budget → map-reduce fallback

## LLM Provider: Nebius Token Factory

- **API Base URL:** `https://api.tokenfactory.nebius.com/v1/`
- **OpenAI-compatible** — use the `openai` Python SDK
- **API Key env var:** `NEBIUS_API_KEY`

### Model Selection

- **Primary model:** `Qwen/Qwen3-235B-A22B-Instruct-2507`
  - 131k context window, $0.20/M input, $0.60/M output
  - Excellent structured output / JSON support
  - Used in Nebius's own documentation examples
  - Why: Best quality-to-cost ratio on Nebius. 131k context means most repos fit in a single call. Supports `response_format: { "type": "json_schema" }` for reliable structured output.
- **Map model (for map-reduce fallback):** `meta-llama/Meta-Llama-3.1-8B-Instruct`
  - $0.02/M input, $0.06/M output (10x cheaper)
  - Used only for extraction in map-reduce chunks
  - Why: Map step is simple extraction work — list technologies, describe what files do. Doesn't need a large model. Keeps costs low.

### Budget Note

With $1 free credit: the primary model costs ~$0.20 per 1M input tokens. A typical single-call summarization uses ~50k tokens input → ~$0.01 per request. That's ~100 requests on $1. More than enough for development + testing.

## File Structure

```
github-repo-summarizer/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, endpoint, request handling
│   ├── github_client.py     # GitHub API: tree fetch, file content fetch
│   ├── file_scorer.py       # File scoring/ranking, filtering logic
│   ├── context_builder.py   # Assemble LLM context, token counting, truncation
│   ├── llm_client.py        # LLM calls: single call + map-reduce
│   ├── prompts.py           # All prompt templates (system + user)
│   ├── schemas.py           # Pydantic request/response models
│   └── config.py            # Settings (env vars, constants, model config)
├── requirements.txt
├── README.md
├── PROGRESS.md              # Claude Code tracking file
├── .env.example
└── .gitignore
```

## Implementation Phases

### Phase 1: Scaffold
- Initialize project structure (all files above)
- Set up FastAPI app with health check `GET /health`
- Create `config.py` with all settings from env vars
- Create `schemas.py` with Pydantic models
- Create `requirements.txt`
- Create `.env.example` and `.gitignore`
- **Verify:** `uvicorn app.main:app` starts and `/health` returns 200

### Phase 2: GitHub Integration (`github_client.py`)
- Implement `parse_github_url(url: str) -> tuple[str, str]` 
  - Extract owner/repo from various GitHub URL formats
  - Handle edge cases: trailing slashes, `.git` suffix, URLs with branch/tree paths
- Implement `get_default_branch(owner: str, repo: str) -> str`
  - `GET /repos/{owner}/{repo}` → extract `default_branch`
  - This also validates the repo exists and is accessible
- Implement `get_repo_tree(owner: str, repo: str, branch: str) -> list[dict]`
  - `GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1`
  - Returns list of `{path, type, size, sha}` for every file
- Implement `get_file_content(owner: str, repo: str, path: str) -> str`
  - `GET /repos/{owner}/{repo}/contents/{path}`
  - Decode base64 content
  - Handle binary files gracefully (return empty or skip)
- Use `httpx.AsyncClient` for all HTTP calls
- Support optional `GITHUB_TOKEN` env var for authenticated requests (higher rate limits)
- **Error handling:**
  - 404 → raise custom `RepoNotFoundError`
  - 403 (rate limit) → raise custom `RateLimitError`
  - Network errors → raise custom `GitHubAPIError`
- **Verify:** Can fetch tree and files from `psf/requests`

### Phase 3: File Scoring (`file_scorer.py`)
- Implement `score_file(path: str, size: int) -> int` (returns 0-100)
- Implement `filter_and_rank(tree: list[dict]) -> list[dict]`

#### Scoring Rules (return 0 to skip entirely):

**Score 0 — Always skip:**
- Binary files: `.png`, `.jpg`, `.jpeg`, `.gif`, `.ico`, `.svg`, `.woff`, `.woff2`, `.ttf`, `.eot`, `.mp3`, `.mp4`, `.zip`, `.tar`, `.gz`, `.pdf`, `.exe`, `.dll`, `.so`, `.dylib`, `.pyc`, `.class`, `.o`, `.wasm`
- Lock files: `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Pipfile.lock`, `poetry.lock`, `composer.lock`, `Gemfile.lock`, `Cargo.lock`, `go.sum`
- Generated/vendored dirs: any path containing `node_modules/`, `vendor/`, `dist/`, `build/`, `.next/`, `__pycache__/`, `.git/`, `.idea/`, `.vscode/`, `venv/`, `.env/`, `env/`, `.tox/`, `coverage/`, `.nyc_output/`
- Generated files: `.min.js`, `.min.css`, `.map`, `.d.ts` (declaration files)
- Large files: size > 100KB (likely data or generated)
- Files deeper than 8 directories (likely nested vendored code)

**Score 100 — README:**
- `README.md`, `README.rst`, `README.txt`, `README` (case-insensitive, any depth)

**Score 95 — Project root README takes priority over nested READMEs:**
- Root-level README gets 100, nested READMEs get 80

**Score 90 — Manifest/config files (dependency + project metadata):**
- `package.json`, `pyproject.toml`, `setup.py`, `setup.cfg`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `Gemfile`, `composer.json`, `CMakeLists.txt`, `Makefile`, `meson.build`

**Score 85 — C/C++ header files in include dirs:**
- `*.h` files where path contains `include/`

**Score 80 — Infrastructure/ops configs:**
- `Dockerfile`, `docker-compose.yml`, `docker-compose.yaml`
- `.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`
- `terraform/*.tf`, `k8s/*.yaml`

**Score 75 — App configuration:**
- `.env.example`, `config.yaml`, `config.json`, `settings.py`, `tsconfig.json`, `webpack.config.js`, `vite.config.ts`, `next.config.js`, `tailwind.config.js`

**Score 70 — Entry points and important source files:**
- `main.py`, `app.py`, `index.ts`, `index.js`, `main.go`, `main.rs`, `Main.java`, `Program.cs`
- `__init__.py` files in top-level packages (1 level deep under src/)

**Score 60 — Regular source files:**
- `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.go`, `.rs`, `.java`, `.c`, `.cpp`, `.h`, `.rb`, `.php`, `.swift`, `.kt`, `.scala`, `.ex`, `.clj`, `.hs`
- Penalize by size: `score = 60 - min(size / 5000, 20)` → larger files score lower

**Score 50 — Documentation files:**
- `CONTRIBUTING.md`, `CHANGELOG.md`, `LICENSE`, `ARCHITECTURE.md`, `docs/*.md`

**Score 30 — Test files:**
- Paths containing `test/`, `tests/`, `spec/`, `__tests__/`
- Files named `*_test.py`, `test_*.py`, `*.test.js`, `*.spec.ts`

**Score 10 — Config noise:**
- `.eslintrc`, `.prettierrc`, `.editorconfig`, `.babelrc`, `.browserslistrc`

#### Output of `filter_and_rank`:
- Remove all files with score 0
- Sort by score descending, then by path length ascending (prefer shallower files)
- Return the sorted list with scores

### Phase 4: Context Builder (`context_builder.py`)
- Implement `build_context(tree: list[dict], ranked_files: list[dict], file_contents: dict[str, str]) -> str`
- Implement `estimate_tokens(text: str) -> int` → `len(text) // 3` (conservative ratio — 3 chars per token instead of 4, to leave safety margin)
- Implement `needs_map_reduce(context: str) -> bool`

#### Context Assembly Strategy:
1. **Always include:** The full directory tree (just paths, no content) — this is cheap in tokens (~1 token per file path)
2. **Always include:** README content (if exists) — highest signal
3. **Always include:** Manifest files content — dependency info
4. **Iterate through ranked files** by score, adding file content until token budget reached

#### Token Budget:
- Model context: 131,072 tokens
- Reserve for system prompt: ~2,000 tokens
- Reserve for response: ~4,000 tokens
- **Usable budget: 100,000 tokens** (conservative, leaves ~25k margin)
- If total context < 100,000 tokens → single LLM call
- If total context > 100,000 tokens → map-reduce

#### Context Format (what the LLM sees):
```
## Repository Directory Tree
<full tree listing, indented>

## File: README.md
<content>

## File: package.json
<content>

## File: src/main.py
<content>

... (more files until budget)
```

### Phase 5: LLM Integration (`llm_client.py` + `prompts.py`)

#### `prompts.py` — All prompt templates:

**System prompt (single call):**
```
You are a code repository analyst. You will receive the directory tree and key files from a GitHub repository. Your job is to produce a structured analysis.

Respond with a JSON object containing exactly these fields:
- "summary": A clear, human-readable description of what this project does. 2-4 sentences. Start with the project name in bold markdown.
- "technologies": An array of strings listing the main languages, frameworks, libraries, and tools used. Be specific (e.g., "FastAPI" not just "Python"). Include only technologies actually used, not tangential tools.
- "structure": A brief description of how the project is organized. Mention key directories and their purposes. 1-3 sentences.

Respond ONLY with the JSON object, no markdown fences, no extra text.
```

**User prompt (single call):**
```
Analyze this GitHub repository:

{context}
```

**System prompt (map step):**
```
You are analyzing a portion of a GitHub repository's source code. Extract key information from these files.

Respond with a JSON object:
- "purpose": What does the code in these files do? 1-2 sentences.
- "technologies": Array of specific technologies, libraries, frameworks seen in these files.
- "structure_notes": Any notable structural patterns. 1 sentence.

Respond ONLY with the JSON object, no markdown fences, no extra text.
```

**System prompt (reduce step):**
```
You are a code repository analyst. You will receive the directory tree of a GitHub repository, its README (if available), and partial analyses from different sections of the codebase.

Synthesize all information into a single coherent analysis.

Respond with a JSON object containing exactly these fields:
- "summary": A clear, human-readable description of what this project does. 2-4 sentences. Start with the project name in bold markdown.
- "technologies": An array of strings listing ALL main languages, frameworks, libraries, and tools identified across all partial analyses. Deduplicate. Be specific.
- "structure": A brief description of how the project is organized. Mention key directories and their purposes. 1-3 sentences.

Respond ONLY with the JSON object, no markdown fences, no extra text.
```

#### `llm_client.py` — LLM call logic:

- Use `openai.AsyncOpenAI` with `base_url` from config
- Implement `call_llm(prompt: str, system_prompt: str, model: str) -> dict`
  - Call chat completions API
  - Parse JSON from response
  - Retry once on JSON parse failure (ask LLM to fix)
  - Use `response_format={"type": "json_object"}` for reliable JSON
- Implement `summarize_single(context: str) -> dict` — one LLM call path
- Implement `summarize_map_reduce(chunks: list[str], tree_and_readme: str) -> dict`
  - Map: call cheap model on each chunk in parallel using `asyncio.gather`
  - Reduce: call primary model with tree + readme + all partial summaries
- Temperature: 0.2 (we want consistent, factual output)
- Max tokens for response: 2000

### Phase 6: Wire It All Together (`main.py`)

The `POST /summarize` endpoint flow:
```
1. Validate request (Pydantic handles this)
2. Parse GitHub URL → owner, repo
3. Get default branch
4. Get repo tree
5. Score and rank files
6. Fetch top-N file contents (parallel with asyncio.gather)
7. Build context
8. If fits budget → single LLM call
   Else → map-reduce
9. Validate LLM response matches schema
10. Return response
```

**Error handling at endpoint level:**
- `RepoNotFoundError` → 404
- `RateLimitError` → 429 with retry-after hint
- `GitHubAPIError` → 502
- LLM errors → 502 with message
- Invalid URL format → 400
- Timeout → 504 (set 120s timeout for the full operation)

### Phase 7: Error Handling & Edge Cases
- **Invalid URL:** Not a GitHub URL, missing owner/repo → 400
- **Private repo:** 404 from GitHub → 404 with clear message
- **Empty repo:** Tree has 0 files → return summary saying repo is empty
- **Repo with only binary files:** No scoreable files → return summary based on tree only
- **GitHub rate limit:** 403 with rate limit headers → 429
- **LLM returns invalid JSON:** Retry once, then return 502
- **Very large repos (100k+ files):** Tree API returns truncated flag → handle gracefully, work with what we have
- **Timeout:** Set httpx timeouts (30s per request), overall endpoint timeout (120s)

### Phase 8: Documentation (`README.md`)
Must include:
1. Project title and one-line description
2. Setup instructions:
   ```
   git clone <repo>
   cd github-repo-summarizer
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   cp .env.example .env
   # Edit .env with your NEBIUS_API_KEY
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
3. Test with curl command
4. Model choice explanation (1-2 sentences referencing Qwen3-235B quality/cost/JSON support)
5. Approach explanation:
   - Uses GitHub REST API to get file tree without downloading the repo
   - Scores files by informativeness (README > manifests > source > tests)
   - Fetches only top files within token budget
   - Falls back to map-reduce for very large repos
6. Environment variables table

### Phase 9: Final Polish & Testing
- Test with these repos:
  - `https://github.com/psf/requests` (medium Python project)
  - `https://github.com/expressjs/express` (medium JS project)
  - `https://github.com/torvalds/linux` (massive C project — tests map-reduce)
  - `https://github.com/kelseyhightower/nocode` (minimal/empty repo — edge case)
- Verify error responses for invalid URLs, private repos
- Check that API key is not hardcoded anywhere
- Verify requirements.txt has all dependencies

## API Contract

### Request
```
POST /summarize
Content-Type: application/json

{
  "github_url": "https://github.com/psf/requests"
}
```

### Success Response (200)
```json
{
  "summary": "**Requests** is a popular Python library for making HTTP requests...",
  "technologies": ["Python", "urllib3", "certifi"],
  "structure": "The project follows a standard Python package layout with the main source code in `src/requests/`, tests in `tests/`, and documentation in `docs/`."
}
```

### Error Response (4xx/5xx)
```json
{
  "status": "error",
  "message": "Description of what went wrong"
}
```

## Dependencies (`requirements.txt`)
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
httpx>=0.25.0
openai>=1.12.0
pydantic>=2.5.0
python-dotenv>=1.0.0
```

## Environment Variables
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEBIUS_API_KEY` | Yes | — | Nebius Token Factory API key |
| `GITHUB_TOKEN` | No | — | GitHub personal access token (raises rate limit from 60/hr to 5000/hr) |
| `PRIMARY_MODEL` | No | `Qwen/Qwen3-235B-A22B-Instruct-2507` | Model for single calls and reduce step |
| `MAP_MODEL` | No | `meta-llama/Meta-Llama-3.1-8B-Instruct` | Model for map step (cheap extraction) |
| `PORT` | No | `8000` | Server port |
| `LOG_LEVEL` | No | `info` | Logging level |

## Constants (in `config.py`)
```python
TOKEN_BUDGET = 100_000          # Max tokens to send to LLM
CHARS_PER_TOKEN = 3             # Conservative estimate
MAX_FILE_SIZE = 100_000         # Skip files larger than 100KB
MAX_FILES_TO_FETCH = 50         # Don't fetch more than 50 files
MAP_CHUNK_SIZE = 30_000         # Tokens per map-reduce chunk
REQUEST_TIMEOUT = 30.0          # Timeout per HTTP request (seconds)
ENDPOINT_TIMEOUT = 120.0        # Total endpoint timeout (seconds)
MAX_TREE_DEPTH = 8              # Skip files deeper than this
LLM_TEMPERATURE = 0.2           # Low temperature for factual output
LLM_MAX_TOKENS = 2000           # Max response tokens
```

## Key Design Decisions Log

1. **GitHub API over clone/tarball** — No disk I/O, no security risk, selective fetching, async-friendly
2. **Qwen3-235B as primary model** — Best quality-to-cost on Nebius, 131k context handles most repos in one call, native JSON schema support
3. **Llama-3.1-8B for map steps** — 10x cheaper, extraction is simple work
4. **Character-based token counting (÷3)** — Conservative to avoid context overflow, no extra dependency
5. **Score-based file ranking** — README first, then manifests, then source. Mimics how a human would understand a project
6. **Map-reduce only as fallback** — 95% of repos fit in a single call with 131k context. Don't add complexity unless needed
