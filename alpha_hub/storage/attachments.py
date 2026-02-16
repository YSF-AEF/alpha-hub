from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional

from ..common.time_util import utc_now_iso


def _default_dir() -> Path:
    # Read env at runtime, not import time (tests may set env after import).
    return Path(os.getenv("ALPHA_HUB_ATTACHMENTS_DIR", "data/attachments"))


@dataclass
class AttachmentMeta:
    attachment_id: str
    filename: str
    sha256: str
    size_bytes: int
    created_at_utc: str
    path: str


class AttachmentStore:
    """v0 attachment storage: local directory."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or _default_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, *, attachment_id: str, filename: str, fileobj: BinaryIO) -> AttachmentMeta:
        created_at_utc = utc_now_iso()
        out_path = self.base_dir / f"{attachment_id}__{filename}"
        h = hashlib.sha256()
        size = 0
        with out_path.open("wb") as f:
            while True:
                chunk = fileobj.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
        return AttachmentMeta(
            attachment_id=attachment_id,
            filename=filename,
            sha256=h.hexdigest(),
            size_bytes=size,
            created_at_utc=created_at_utc,
            path=str(out_path),
        )
