import logging

from app.config import TOKEN_BUDGET, CHARS_PER_TOKEN, MAP_CHUNK_SIZE

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Conservative token count: 3 chars per token."""
    return len(text) // CHARS_PER_TOKEN


def build_tree_listing(tree: list[dict]) -> str:
    """Format the full file tree as an indented path listing."""
    lines = ["## Repository Directory Tree", ""]
    for entry in tree:
        path = entry["path"]
        depth = path.count("/")
        indent = "  " * depth
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        lines.append(f"{indent}{name}")
    return "\n".join(lines)


def _format_file(path: str, content: str) -> str:
    return f"## File: {path}\n{content}\n\n"


def build_context(
    ranked_files: list[dict],
    file_contents: dict[str, str],
    tree: list[dict],
) -> str:
    """Assemble LLM context string respecting TOKEN_BUDGET."""
    parts: list[str] = []

    # Always include: full tree listing
    tree_listing = build_tree_listing(tree)
    parts.append(tree_listing + "\n\n")

    added_paths: set[str] = set()

    # Always include: README (score 100 or 80)
    for entry in ranked_files:
        if entry["score"] >= 80 and entry["path"].lower().split("/")[-1].startswith("readme"):
            path = entry["path"]
            if path in file_contents and file_contents[path]:
                parts.append(_format_file(path, file_contents[path]))
                added_paths.add(path)
                break

    # Always include: manifest files (score >= 90)
    for entry in ranked_files:
        if entry["score"] >= 90:
            path = entry["path"]
            if path in added_paths:
                continue
            if path in file_contents and file_contents[path]:
                parts.append(_format_file(path, file_contents[path]))
                added_paths.add(path)

    # Fill remaining budget with ranked files
    current_tokens = estimate_tokens("".join(parts))

    for entry in ranked_files:
        path = entry["path"]
        if path in added_paths:
            continue
        content = file_contents.get(path, "")
        if not content:
            continue
        chunk = _format_file(path, content)
        new_tokens = estimate_tokens(chunk)
        if current_tokens + new_tokens >= TOKEN_BUDGET:
            logger.debug(f"Token budget reached at {current_tokens} tokens, skipping remaining files")
            break
        parts.append(chunk)
        added_paths.add(path)
        current_tokens += new_tokens

    context = "".join(parts)
    logger.debug(f"Built context: ~{estimate_tokens(context)} tokens, {len(added_paths)} files")
    return context


def needs_map_reduce(context: str) -> bool:
    """Return True if context exceeds the token budget."""
    return estimate_tokens(context) > TOKEN_BUDGET


def split_into_chunks(
    ranked_files: list[dict],
    file_contents: dict[str, str],
) -> list[str]:
    """Split file contents into MAP_CHUNK_SIZE-token chunks for map-reduce."""
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for entry in ranked_files:
        path = entry["path"]
        content = file_contents.get(path, "")
        if not content:
            continue
        chunk_text = _format_file(path, content)
        chunk_tokens = estimate_tokens(chunk_text)

        if current_tokens + chunk_tokens > MAP_CHUNK_SIZE and current_parts:
            chunks.append("".join(current_parts))
            current_parts = []
            current_tokens = 0

        current_parts.append(chunk_text)
        current_tokens += chunk_tokens

    if current_parts:
        chunks.append("".join(current_parts))

    logger.debug(f"Split into {len(chunks)} map-reduce chunks")
    return chunks


def build_tree_and_readme(
    tree: list[dict],
    file_contents: dict[str, str],
) -> str:
    """Build tree listing + README content for the reduce step."""
    parts = [build_tree_listing(tree), "\n\n"]

    for path, content in file_contents.items():
        name = path.lower().rsplit("/", 1)[-1]
        if name.startswith("readme") and content:
            parts.append(_format_file(path, content))
            break

    return "".join(parts)
