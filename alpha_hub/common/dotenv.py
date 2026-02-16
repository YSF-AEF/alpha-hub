from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Iterable


def _is_allowed_key(key: str, allow_keys: Optional[set[str]], allow_prefixes: Optional[tuple[str, ...]]) -> bool:
    if allow_keys is None and allow_prefixes is None:
        return True
    if allow_keys is not None and key in allow_keys:
        return True
    if allow_prefixes is not None:
        for p in allow_prefixes:
            if key.startswith(p):
                return True
    return False


def load_dotenv(
    path: str | Path,
    *,
    override: bool = False,
    allow_keys: Optional[Iterable[str]] = None,
    allow_prefixes: Optional[Iterable[str]] = None,
) -> bool:
    """Load environment variables from a .env file.

    - Supports lines: KEY=VALUE or export KEY=VALUE
    - Ignores blank lines and comments (# ...)
    - If override=False (default), existing env vars are not overwritten.
    - If allow_keys / allow_prefixes is provided, only matching keys are loaded.

    Returns True if the file existed and was processed, else False.
    """
    p = Path(path)
    if not p.exists():
        return False

    allow_keys_set: Optional[set[str]] = set(allow_keys) if allow_keys is not None else None
    allow_prefixes_t: Optional[tuple[str, ...]] = tuple(allow_prefixes) if allow_prefixes is not None else None

    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            continue
        if not _is_allowed_key(key, allow_keys_set, allow_prefixes_t):
            continue

        # strip quotes if present
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        if not override and key in os.environ:
            continue
        os.environ[key] = value

    return True


def load_dotenv_auto(
    *,
    env_file: Optional[str] = None,
    override: bool = False,
    allow_keys: Optional[Iterable[str]] = None,
    allow_prefixes: Optional[Iterable[str]] = None,
) -> Optional[Path]:
    """Try to load environment variables from a .env file.

    Priority:
    1) ALPHA_HUB_ENV_FILE (if set) or env_file parameter (if provided)
    2) ./ .env (current working dir)
    3) repo root's .env (best-effort heuristic)

    Returns the loaded path if success, else None.
    """
    candidate: Optional[Path] = None

    env_path = os.getenv("ALPHA_HUB_ENV_FILE") or env_file
    if env_path:
        candidate = Path(env_path)
        if load_dotenv(candidate, override=override, allow_keys=allow_keys, allow_prefixes=allow_prefixes):
            return candidate

    # CWD
    candidate = Path.cwd() / ".env"
    if load_dotenv(candidate, override=override, allow_keys=allow_keys, allow_prefixes=allow_prefixes):
        return candidate

    # repo root heuristic: <repo>/alpha_hub/common/dotenv.py -> parents[2] is <repo>
    try:
        repo_root = Path(__file__).resolve().parents[2]
        candidate = repo_root / ".env"
        if load_dotenv(candidate, override=override, allow_keys=allow_keys, allow_prefixes=allow_prefixes):
            return candidate
    except Exception:
        pass

    return None
