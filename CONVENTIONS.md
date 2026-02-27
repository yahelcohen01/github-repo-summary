# Coding Conventions

## Python Style

- **Python 3.10+** — use modern syntax (type unions with `|`, match statements if useful)
- **Type hints everywhere** — all function signatures, return types, class attributes
- **Async by default** — use `async def` for anything involving I/O
- **f-strings** for string formatting
- **Snake_case** for functions and variables, **PascalCase** for classes
- **UPPER_CASE** for constants

## Imports

Order: stdlib → third-party → local, separated by blank lines.

```python
import os
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException

from app.config import settings
from app.schemas import SummarizeRequest
```

## Error Handling

- Define custom exceptions in the module where they originate
- Use `HTTPException` only in `main.py` (the endpoint layer)
- All other modules raise custom exceptions; `main.py` catches and converts to HTTP responses
- Always log errors with context before raising
- Never silently swallow exceptions

```python
# In github_client.py
class RepoNotFoundError(Exception):
    pass

# In main.py
try:
    tree = await get_repo_tree(owner, repo, branch)
except RepoNotFoundError:
    raise HTTPException(status_code=404, detail={"status": "error", "message": f"Repository {owner}/{repo} not found"})
```

## Logging

- Use Python's `logging` module, not `print()`
- Logger per module: `logger = logging.getLogger(__name__)`
- Levels: DEBUG for verbose internals, INFO for flow milestones, WARNING for recoverable issues, ERROR for failures
- Log at INFO level: start of request, number of files scored, context size, LLM model used, response time
- Log at DEBUG level: individual file scores, file contents fetched

## Configuration

- All env vars loaded in `config.py` via a Pydantic `BaseSettings` class or plain `os.getenv`
- Never import `os.getenv` in other modules — always import from `config`
- Use `python-dotenv` to load `.env` file for local development

## Pydantic Models

- Use Pydantic v2 syntax
- Request and response models in `schemas.py`
- Use `model_validator` for complex validation (e.g., URL format)

## HTTP Client

- Use `httpx.AsyncClient` with explicit timeouts
- Create client as a module-level variable or use dependency injection
- Set `User-Agent` header on all GitHub API requests
- Close client properly (use lifespan context manager in FastAPI)

## Constants

- All magic numbers go in `config.py` with descriptive names
- No magic numbers or strings in business logic

## Testing Approach

- This project uses manual testing via curl (per assignment spec)
- No automated test framework needed
- But write code that IS testable: pure functions where possible, dependency injection for clients

## File Organization Principles

- Each file has a single responsibility
- No circular imports
- `main.py` is the only file that knows about FastAPI specifics (HTTPException, Request, etc.)
- Other modules are framework-agnostic and could be reused
