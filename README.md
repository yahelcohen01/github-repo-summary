# GitHub Repository Summarizer

A FastAPI service that takes a GitHub repository URL and returns an LLM-generated summary including what the project does, technologies used, and project structure.

## Setup

```bash
git clone <repo-url>
cd github-repo-summarizer

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your NEBIUS_API_KEY

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Usage

```bash
# Health check
curl http://localhost:8000/health

# Summarize a repository
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

### Success response

```json
{
  "summary": "**Requests** is a popular Python library...",
  "technologies": ["Python", "urllib3", "certifi"],
  "structure": "The project follows a standard Python package layout..."
}
```

### Error response

```json
{
  "status": "error",
  "message": "Repository not found or is private"
}
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEBIUS_API_KEY` | Yes | — | Nebius Token Factory API key |
| `GITHUB_TOKEN` | No | — | GitHub personal access token (raises rate limit from 60/hr to 5000/hr) |
| `PRIMARY_MODEL` | No | `Qwen/Qwen3-235B-A22B-Instruct-2507` | Model for single calls and reduce step |
| `MAP_MODEL` | No | `meta-llama/Meta-Llama-3.1-8B-Instruct` | Model for map step (cheap extraction) |
| `PORT` | No | `8000` | Server port |
| `LOG_LEVEL` | No | `info` | Logging level (`debug`, `info`, `warning`, `error`) |

## Model Choice

**Primary model:** `Qwen/Qwen3-235B-A22B-Instruct-2507` — chosen for its 131k context window (most repos fit in a single call), native JSON schema support, and best quality-to-cost ratio on Nebius at $0.20/M input tokens (~$0.01 per request).

**Map model:** `meta-llama/Meta-Llama-3.1-8B-Instruct` — 10x cheaper, used only for the extraction step in map-reduce fallback where the task is simple enumeration, not synthesis.

## Approach

1. **No repo cloning** — uses GitHub's Git Trees API to fetch the full file tree in one request, then selectively fetches only relevant files. No disk I/O, no security risk.

2. **File scoring** — files are ranked by informativeness (0–100): README > manifests > source files > tests. Binary files, lock files, and vendored directories are skipped entirely.

3. **Token budget** — fetches the top 50 files, fills a 100k-token context window in score order. Leaves a safety margin for the model's 131k context limit.

4. **Map-reduce fallback** — for very large repos where context exceeds 100k tokens, the service splits files into ~30k-token chunks, extracts partial analyses in parallel using the cheap model, then synthesizes them with the primary model.
