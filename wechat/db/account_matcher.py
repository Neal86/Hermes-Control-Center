from __future__ import annotations

from pathlib import Path
from typing import Callable

from .base import BackendUnavailable


def match_account(accounts: list[Path], wxid: str, verify: Callable[[Path], bool] | None = None) -> Path:
    """Match one bound WeChat process to exactly one account directory.

    Directory-name identity is the first signal. A cryptographic DB-key check is
    the final authority when a verifier is supplied. Ambiguity always fails
    closed instead of selecting the first folder.
    """
    identity = str(wxid or "").strip().lower()
    candidates = [path for path in accounts if identity and path.name.lower().startswith(identity + "_")]
    if not candidates:
        candidates = list(accounts)
    if verify is not None:
        candidates = [path for path in candidates if verify(path)]
    if len(candidates) != 1:
        names = ", ".join(path.name for path in candidates) or "none"
        raise BackendUnavailable(f"Unable to uniquely map bound WeChat account; candidates={names}")
    return candidates[0]
