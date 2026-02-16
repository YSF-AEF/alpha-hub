from __future__ import annotations

from datetime import datetime, timezone

def utc_now_iso() -> str:
    """返回 UTC 时间的 ISO-8601 字符串（带 Z）。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
