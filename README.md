# GitHub Repository Summarizer

A FastAPI service that accepts a GitHub repository URL and returns an LLM-generated summary: what the project does, technologies used, and how it's organized.

## Setup

```bash
git clone <repo-url>
cd github-repo-summary

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and set NEBIUS_API_KEY
```

Start the server:

```bash
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

**Success (200)**

```json
{
  "summary": "**Requests** is a simple, elegant HTTP library for Python...",
  "technologies": ["Python", "urllib3", "certifi", "chardet"],
  "structure": "Source lives in src/requests/, tests in tests/, docs in docs/."
}
```

**Error (4xx / 5xx)**

```json
{
  "status": "error",
  "message": "Repository not found or is private"
}
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEBIUS_API_KEY` | Yes | — | Nebius Token Factory API key |
| `GITHUB_TOKEN` | No | — | GitHub PAT — raises rate limit from 60 to 5,000 req/hr |
| `PRIMARY_MODEL` | No | `Qwen/Qwen3-235B-A22B-Instruct-2507` | Model for single calls and reduce step |
| `MAP_MODEL` | No | `meta-llama/Meta-Llama-3.1-8B-Instruct` | Model for map step (cheap extraction) |
| `PORT` | No | `8000` | Server port |
| `LOG_LEVEL` | No | `info` | Logging level (`debug`, `info`, `warning`, `error`) |

Set `LOG_LEVEL=debug` to see per-file scores, token usage, and GitHub rate-limit headers.

## How It Works

**1. Tree fetch, not clone.** The service calls GitHub's Git Trees API to get the full file tree in a single request, then fetches only the files it actually needs. No disk I/O, no cloning, no security risk from arbitrary repo content.

**2. Score-based file selection.** Every file is scored 0–100 by informativeness. READMEs and manifests score highest; test files, config noise, lock files, and binaries are filtered out. The top 50 files by score fill the LLM context window.

**3. Single call by default.** The primary model has a 131k context window. Most repos fit comfortably, so the common path is one LLM call with up to 100k tokens of context.

**4. Map-reduce for large repos.** When context exceeds 100k tokens, files are split into ~30k-token chunks. The cheap map model extracts partial analyses from each chunk in parallel; the primary model then synthesizes everything into a single coherent summary.

## Model Choice

**Primary — `Qwen/Qwen3-235B-A22B-Instruct-2507`:** Best quality-to-cost ratio on Nebius ($0.20/M input). The 131k context window means most repos require only one call. Strong structured-output / JSON support keeps response parsing reliable. Typical cost: ~$0.01 per request.

**Map — `meta-llama/Meta-Llama-3.1-8B-Instruct`:** 10× cheaper ($0.02/M input). Used only for the extraction pass in map-reduce, where the task is straightforward enumeration rather than synthesis.
