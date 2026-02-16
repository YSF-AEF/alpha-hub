from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class ApiError(Exception):
    """统一的业务错误，用于转换成契约规定的错误响应结构。"""
    code: str
    message: str
    http_status: int = 400
    data: Optional[dict[str, Any]] = None
