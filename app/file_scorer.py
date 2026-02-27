import logging
import os

from app.config import MAX_FILE_SIZE, MAX_TREE_DEPTH

logger = logging.getLogger(__name__)

# --- Skip rules (score 0) ---

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".mp3", ".mp4",
    ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".pdf", ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".class", ".o", ".wasm",
    ".bin", ".dat", ".db", ".sqlite",
}

LOCK_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "pipfile.lock", "poetry.lock", "composer.lock",
    "gemfile.lock", "cargo.lock", "go.sum",
}

SKIP_DIRS = {
    "node_modules/", "vendor/", "dist/", "build/",
    ".next/", "__pycache__/", ".git/", ".idea/", ".vscode/",
    "venv/", ".env/", "env/", ".tox/", "coverage/", ".nyc_output/",
}

GENERATED_SUFFIXES = (".min.js", ".min.css", ".map", ".d.ts")

# --- Manifest files (score 90) ---
MANIFEST_FILES = {
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "gemfile", "composer.json", "cmakelists.txt", "makefile",
    "meson.build",
}

# --- Entry points (score 70) ---
ENTRY_POINT_FILES = {
    "main.py", "app.py", "index.ts", "index.js",
    "main.go", "main.rs", "main.java", "program.cs",
}

# --- Source file extensions (score 60) ---
SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".go", ".rs", ".java", ".c", ".cpp", ".h",
    ".rb", ".php", ".swift", ".kt", ".scala",
    ".ex", ".clj", ".hs",
}

# --- Config noise (score 10) ---
CONFIG_NOISE_FILES = {
    ".eslintrc", ".prettierrc", ".editorconfig",
    ".babelrc", ".browserslistrc",
}

# --- App config files (score 75) ---
APP_CONFIG_FILES = {
    ".env.example", "config.yaml", "config.json",
    "settings.py", "tsconfig.json", "webpack.config.js",
    "vite.config.ts", "next.config.js", "tailwind.config.js",
}

# --- Test markers (score 30) ---
TEST_DIRS = {"test/", "tests/", "spec/", "__tests__/"}


def _path_depth(path: str) -> int:
    return len(path.split("/"))


def _filename(path: str) -> str:
    return os.path.basename(path)


def _is_test_file(path: str) -> bool:
    lower = path.lower()
    for d in TEST_DIRS:
        if d in lower:
            return True
    name = _filename(lower)
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.js")
    )


def score_file(path: str, size: int) -> int:
    """Return a score 0-100 for how informative a file is. 0 means skip."""
    lower_path = path.lower()
    name = _filename(lower_path)
    _, ext = os.path.splitext(name)

    # --- Score 0: always skip ---
    if ext in BINARY_EXTENSIONS:
        return 0
    if name in LOCK_FILES:
        return 0
    for skip_dir in SKIP_DIRS:
        if skip_dir in lower_path:
            return 0
    if any(lower_path.endswith(suffix) for suffix in GENERATED_SUFFIXES):
        return 0
    if size > MAX_FILE_SIZE:
        return 0
    if _path_depth(path) > MAX_TREE_DEPTH:
        return 0

    # --- Score 100/80: README ---
    readme_names = {"readme.md", "readme.rst", "readme.txt", "readme"}
    if name in readme_names:
        depth = _path_depth(path)
        return 100 if depth == 1 else 80

    # --- Score 90: manifest/config files ---
    if name in MANIFEST_FILES:
        return 90

    # --- Score 85: C/C++ headers in include/ dirs ---
    if ext == ".h" and "include/" in lower_path:
        return 85

    # --- Score 80: infrastructure/ops ---
    if name in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
        return 80
    if lower_path.startswith(".github/workflows/") and ext == ".yml":
        return 80
    if name in {".gitlab-ci.yml", "jenkinsfile"}:
        return 80
    if ext == ".tf":
        return 80
    if lower_path.startswith("k8s/") and ext == ".yaml":
        return 80

    # --- Score 75: app config ---
    if name in APP_CONFIG_FILES:
        return 75

    # --- Score 70: entry points ---
    if name in ENTRY_POINT_FILES:
        return 70
    # __init__.py at depth <= 2 (top-level package)
    if name == "__init__.py" and _path_depth(path) <= 2:
        return 70

    # --- Score 50: documentation ---
    doc_names = {"contributing.md", "changelog.md", "license", "architecture.md"}
    if name in doc_names:
        return 50
    if lower_path.startswith("docs/") and ext == ".md":
        return 50

    # --- Score 30: test files ---
    if _is_test_file(path):
        return 30

    # --- Score 10: config noise ---
    if name in CONFIG_NOISE_FILES or name.startswith(".eslintrc"):
        return 10

    # --- Score 60: regular source files (penalized by size) ---
    if ext in SOURCE_EXTENSIONS:
        penalty = min(size // 5000, 20)
        return max(60 - penalty, 1)

    # Everything else: score 0 (skip)
    return 0


def filter_and_rank(tree: list[dict]) -> list[dict]:
    """Filter, score, and sort a file tree. Returns files with score > 0."""
    scored: list[dict] = []

    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry["path"]
        size = entry.get("size", 0)
        score = score_file(path, size)
        logger.debug(f"Score {score:3d} — {path}")
        if score > 0:
            scored.append({**entry, "score": score})

    # Sort: score descending, then path length ascending (prefer shallower)
    scored.sort(key=lambda e: (-e["score"], len(e["path"])))
    return scored
