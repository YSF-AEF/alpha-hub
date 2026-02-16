from __future__ import annotations

import os
from fastapi import Header
from .errors import ApiError

def _get_token() -> str:
    token = os.getenv("ALPHA_HUB_TOKEN", "").strip()
    if not token:
        # 强制要求设置 token，避免“无鉴权裸奔”
        raise ApiError(code="UNAUTHORIZED", message="Server token not configured (ALPHA_HUB_TOKEN)", http_status=401)
    return token

def require_bearer(authorization: str | None = Header(default=None)) -> None:
    """HTTP Bearer 鉴权依赖。"""
    token = _get_token()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(code="UNAUTHORIZED", message="Missing Bearer token", http_status=401)
    got = authorization.split(" ", 1)[1].strip()
    if got != token:
        raise ApiError(code="UNAUTHORIZED", message="Invalid token", http_status=401)

def check_ws_bearer(authorization: str | None) -> None:
    """WebSocket Bearer 鉴权。"""
    token = _get_token()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(code="UNAUTHORIZED", message="Missing Bearer token", http_status=401)
    got = authorization.split(" ", 1)[1].strip()
    if got != token:
        raise ApiError(code="UNAUTHORIZED", message="Invalid token", http_status=401)
