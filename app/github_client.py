import base64
import logging
import re
from typing import AsyncGenerator
from contextlib import asynccontextmanager

import httpx

from app.config import GITHUB_TOKEN, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class RepoNotFoundError(Exception):
    pass


class RateLimitError(Exception):
    pass


class GitHubAPIError(Exception):
    pass


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from various GitHub URL formats."""
    url = url.strip().rstrip("/")

    # Remove .git suffix
    if url.endswith(".git"):
        url = url[:-4]

    # Normalize: remove protocol prefix
    url = re.sub(r"^https?://", "", url)

    # Remove www. prefix if present
    url = re.sub(r"^www\.", "", url)

    # Must start with github.com
    if not url.startswith("github.com/"):
        raise ValueError(f"Not a GitHub URL: {url!r}")

    # Strip github.com/
    path = url[len("github.com/"):]

    # Split into parts — we only want owner/repo (first two segments)
    parts = [p for p in path.split("/") if p]

    if len(parts) < 2:
        raise ValueError(f"GitHub URL must include owner and repo: {url!r}")

    owner = parts[0]
    repo = parts[1]

    # Reject if owner or repo look invalid
    if not re.match(r"^[\w.\-]+$", owner) or not re.match(r"^[\w.\-]+$", repo):
        raise ValueError(f"Invalid owner or repo name in URL: {url!r}")

    return owner, repo


def _build_headers() -> dict[str, str]:
    headers = {"User-Agent": "github-repo-summarizer/1.0"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


@asynccontextmanager
async def create_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an httpx async client configured for GitHub API."""
    async with httpx.AsyncClient(
        base_url=GITHUB_API_BASE,
        headers=_build_headers(),
        timeout=REQUEST_TIMEOUT,
    ) as client:
        yield client


async def get_default_branch(
    owner: str, repo: str, client: httpx.AsyncClient
) -> str:
    """Fetch repo metadata and return the default branch name."""
    url = f"/repos/{owner}/{repo}"
    logger.debug(f"GET {url}")

    try:
        response = await client.get(url)
    except httpx.RequestError as exc:
        raise GitHubAPIError(f"Network error fetching repo info: {exc}") from exc

    if response.status_code == 404:
        raise RepoNotFoundError(f"Repository {owner}/{repo} not found")
    if response.status_code == 403:
        raise RateLimitError("GitHub API rate limit exceeded")
    if response.status_code != 200:
        raise GitHubAPIError(f"Unexpected status {response.status_code} for {url}")

    return response.json()["default_branch"]


async def get_repo_tree(
    owner: str, repo: str, branch: str, client: httpx.AsyncClient
) -> list[dict]:
    """Fetch the full recursive file tree for a repo."""
    url = f"/repos/{owner}/{repo}/git/trees/{branch}"
    logger.debug(f"GET {url}?recursive=1")

    try:
        response = await client.get(url, params={"recursive": "1"})
    except httpx.RequestError as exc:
        raise GitHubAPIError(f"Network error fetching tree: {exc}") from exc

    if response.status_code == 404:
        raise RepoNotFoundError(f"Branch {branch} not found in {owner}/{repo}")
    if response.status_code == 403:
        raise RateLimitError("GitHub API rate limit exceeded")
    if response.status_code != 200:
        raise GitHubAPIError(f"Unexpected status {response.status_code} fetching tree")

    data = response.json()

    if data.get("truncated"):
        logger.warning(
            f"Tree is truncated for {owner}/{repo} — very large repo, "
            "working with available files only"
        )

    tree = data.get("tree", [])
    return [
        {
            "path": entry["path"],
            "type": entry["type"],
            "size": entry.get("size", 0),
            "sha": entry["sha"],
        }
        for entry in tree
    ]


async def get_file_content(
    owner: str, repo: str, path: str, client: httpx.AsyncClient
) -> str:
    """Fetch and decode the content of a single file."""
    url = f"/repos/{owner}/{repo}/contents/{path}"
    logger.debug(f"GET {url}")

    try:
        response = await client.get(url)
    except httpx.RequestError as exc:
        raise GitHubAPIError(f"Network error fetching {path}: {exc}") from exc

    if response.status_code == 404:
        logger.warning(f"File not found: {path}")
        return ""
    if response.status_code == 403:
        raise RateLimitError("GitHub API rate limit exceeded")
    if response.status_code != 200:
        logger.warning(f"Unexpected status {response.status_code} for {path}")
        return ""

    data = response.json()
    encoded = data.get("content", "")

    # Remove newlines from base64 string (GitHub includes them)
    encoded = encoded.replace("\n", "")

    try:
        raw_bytes = base64.b64decode(encoded)
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        logger.debug(f"Binary file (skipping): {path}")
        return ""
    except Exception as exc:
        logger.warning(f"Failed to decode {path}: {exc}")
        return ""
