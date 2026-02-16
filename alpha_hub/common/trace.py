from __future__ import annotations

import uuid


def new_id() -> str:
    """Generate a stable, sortable identifier.

    Contract (v0) prefers ULID (26 chars). We use ulid-py when available.
    Fallback to UUID4 hex to avoid crashing if dependency is missing.
    """
    try:
        import ulid  # type: ignore
        return str(ulid.new())
    except Exception:
        return uuid.uuid4().hex


def new_trace_id() -> str:
    """Generate trace_id (same format as IDs)."""
    return new_id()
