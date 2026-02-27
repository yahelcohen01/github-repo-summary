import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import configure_logging, ENDPOINT_TIMEOUT, MAX_FILES_TO_FETCH
from app.schemas import SummarizeRequest, SummarizeResponse
from app.github_client import (
    parse_github_url,
    get_default_branch,
    get_repo_tree,
    get_file_content,
    create_client,
    RepoNotFoundError,
    RateLimitError,
    GitHubAPIError,
)
from app.file_scorer import filter_and_rank
from app.context_builder import build_context, needs_map_reduce, split_into_chunks, build_tree_and_readme
from app.llm_client import (
    create_openai_client,
    summarize_single,
    summarize_map_reduce,
    LLMError,
)

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GitHub Repo Summarizer starting up")
    yield
    logger.info("GitHub Repo Summarizer shutting down")


app = FastAPI(
    title="GitHub Repository Summarizer",
    description="Summarizes GitHub repositories using LLM analysis",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "status" in detail and "message" in detail:
        content = detail
    else:
        content = {"status": "error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    msg = "; ".join(f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in errors)
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": msg},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"},
    )


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(request: SummarizeRequest) -> SummarizeResponse:
    logger.info(f"Summarize request: {request.github_url}")

    async def _run() -> SummarizeResponse:
        start_time = time.monotonic()
        # 1. Parse GitHub URL
        try:
            owner, repo = parse_github_url(request.github_url)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": str(exc)},
            )

        logger.info(f"Parsed repo: {owner}/{repo}")

        async with create_client() as github_client:
            # 2. Get default branch (also validates repo exists)
            try:
                branch = await get_default_branch(owner, repo, github_client)
            except RepoNotFoundError:
                raise HTTPException(
                    status_code=404,
                    detail={"status": "error", "message": f"Repository {owner}/{repo} not found or is private"},
                )
            except RateLimitError:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "status": "error",
                        "message": "GitHub API rate limit exceeded. Set GITHUB_TOKEN env var for higher limits.",
                    },
                )

            logger.info(f"Default branch: {branch}")

            # 3. Get repo tree
            try:
                tree = await get_repo_tree(owner, repo, branch, github_client)
            except GitHubAPIError as exc:
                raise HTTPException(
                    status_code=502,
                    detail={"status": "error", "message": f"GitHub API error: {exc}"},
                )

            logger.info(f"Tree has {len(tree)} entries")

            # 4. Handle empty repo
            blobs = [e for e in tree if e.get("type") == "blob"]
            if not blobs:
                logger.info("Repo is empty or has no files")
                return SummarizeResponse(
                    summary=f"**{repo}** appears to be an empty repository with no files.",
                    technologies=[],
                    structure="No files found in the repository.",
                )

            # 5. Score and rank files
            ranked_files = filter_and_rank(tree)
            logger.info(f"Ranked {len(ranked_files)} files after filtering")
            for path, score in [(f["path"], f["score"]) for f in ranked_files[:10]]:
                logger.debug(f"  Top file: score={score:3d} — {path}")

            # 6. Handle repos with only unscoreable files
            if not ranked_files:
                logger.info("All files scored 0 — summarizing from tree listing only")
                file_contents: dict[str, str] = {}
            else:
                # 7. Fetch top-N file contents in parallel
                top_files = ranked_files[:MAX_FILES_TO_FETCH]
                logger.info(f"Fetching content for {len(top_files)} files")

                contents = await asyncio.gather(
                    *[get_file_content(owner, repo, f["path"], github_client) for f in top_files],
                    return_exceptions=True,
                )

                file_contents = {}
                for file_entry, content in zip(top_files, contents):
                    if isinstance(content, Exception):
                        logger.warning(f"Failed to fetch {file_entry['path']}: {content}")
                        continue
                    file_contents[file_entry["path"]] = content

                logger.info(f"Successfully fetched {len(file_contents)} file contents")

        # 8. Build context
        context = build_context(ranked_files, file_contents, tree)
        logger.info(f"Context size: ~{len(context) // 3} tokens")

        # 9. LLM call
        llm_client = create_openai_client()
        try:
            if not needs_map_reduce(context):
                logger.info("Using single LLM call")
                result = await summarize_single(context, llm_client)
            else:
                logger.info("Using map-reduce (context exceeds token budget)")
                chunks = split_into_chunks(ranked_files, file_contents)
                tree_and_readme = build_tree_and_readme(tree, file_contents)
                result = await summarize_map_reduce(chunks, tree_and_readme, llm_client)
        except LLMError as exc:
            raise HTTPException(
                status_code=502,
                detail={"status": "error", "message": f"LLM response error: {exc}"},
            )

        # 10. Validate result fields
        missing = [f for f in ("summary", "technologies", "structure") if f not in result]
        if missing:
            logger.warning(f"LLM response missing required fields: {missing}")
            raise HTTPException(
                status_code=502,
                detail={"status": "error", "message": f"LLM response missing fields: {missing}"},
            )

        elapsed = time.monotonic() - start_time
        logger.info(f"Summary complete for {owner}/{repo} in {elapsed:.1f}s")
        return SummarizeResponse(
            summary=result["summary"],
            technologies=result["technologies"],
            structure=result["structure"],
        )

    try:
        return await asyncio.wait_for(_run(), timeout=ENDPOINT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"Request timed out after {ENDPOINT_TIMEOUT}s: {request.github_url}")
        raise HTTPException(
            status_code=504,
            detail={"status": "error", "message": "Request timed out"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Unexpected error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": "Internal server error"},
        )
