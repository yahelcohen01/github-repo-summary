import os
import logging

from dotenv import load_dotenv

load_dotenv()

# --- API keys ---
NEBIUS_API_KEY: str = os.getenv("NEBIUS_API_KEY", "")
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

# --- Models ---
PRIMARY_MODEL: str = os.getenv(
    "PRIMARY_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507"
)
MAP_MODEL: str = os.getenv(
    "MAP_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct"
)

# --- Server ---
PORT: int = int(os.getenv("PORT", "8000"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info").upper()

# --- LLM parameters ---
LLM_TEMPERATURE: float = 0.2
LLM_MAX_TOKENS: int = 2000

# --- Token budget ---
TOKEN_BUDGET: int = 100_000
CHARS_PER_TOKEN: int = 3
MAP_CHUNK_SIZE: int = 30_000  # tokens per map-reduce chunk

# --- File fetching ---
MAX_FILE_SIZE: int = 100_000   # bytes — skip files larger than 100KB
MAX_FILES_TO_FETCH: int = 50   # max files to fetch content for
MAX_TREE_DEPTH: int = 8        # skip files deeper than this

# --- Timeouts ---
REQUEST_TIMEOUT: float = 30.0    # per HTTP request (seconds)
ENDPOINT_TIMEOUT: float = 120.0  # total endpoint timeout (seconds)

# --- LLM API ---
NEBIUS_BASE_URL: str = "https://api.tokenfactory.nebius.com/v1/"


def configure_logging() -> None:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
