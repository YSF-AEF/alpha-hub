from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


class LlmConfig(BaseModel):
    """LLM provider configuration.

    Notes:
    - We keep OpenAI-compatible fields so you can point this to OpenAI, Azure OpenAI
      (via a gateway), or any OpenAI-compatible proxy.
    """

    enabled: bool = True
    mode: Literal["mock", "remote"] = "mock"

    # OpenAI-compatible base URL, e.g. "https://api.openai.com"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: str = "gpt-4o-mini"
    stream_path: str = "/v1/chat/completions"
    timeout_s: float = 30.0


class KernelConfig(BaseModel):
    """Kernel runtime configuration loaded from file + env overrides."""

    db_path: str = "data/alpha_hub.db"
    attachments_dir: str = "data/attachments"
    context_limit: int = 30
    system_prompt: str = "You are a helpful assistant."

    llm: LlmConfig = Field(default_factory=LlmConfig)


class ConfigManager:
    """Load configuration from JSON file with environment overrides.

    Contract alignment (v0):
    - default < config file < environment variables (including those loaded from .env)
    - self-healing:
        * if config file is missing: write a default config (best-effort)
        * if config file is corrupted: backup the bad file then write a default config (best-effort)
    - never crash the kernel due to config issues
    """

    def __init__(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self.default_path = repo_root / "config" / "alpha_hub.json"

    def _default_data(self) -> dict:
        # Keep a stable, file-friendly representation
        return KernelConfig().model_dump()

    def _write_default(self, cfg_path: Path) -> None:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps(self._default_data(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self) -> KernelConfig:
        raw_path = os.getenv("ALPHA_HUB_CONFIG_PATH", str(self.default_path))
        cfg_path = Path(raw_path)
        if not cfg_path.is_absolute():
            # interpret relative paths from repo root (not process CWD)
            repo_root = self.default_path.parent.parent
            cfg_path = repo_root / cfg_path


        data: dict = {}

        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                # backup bad file then heal with defaults
                try:
                    ts = __import__("datetime").datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                    backup = cfg_path.with_suffix(cfg_path.suffix + f".bad-{ts}")
                    cfg_path.replace(backup)
                except Exception:
                    pass
                try:
                    self._write_default(cfg_path)
                except Exception:
                    pass
                data = self._default_data()
        else:
            # missing config: heal by writing defaults (best-effort)
            try:
                self._write_default(cfg_path)
            except Exception:
                pass
            data = self._default_data()

        # 2) env overrides (non-secret & secret allowed)
        # Secrets: ALPHA_HUB_TOKEN is handled by auth.py, but we still allow llm api_key here.
        env_overrides = {
            "db_path": os.getenv("ALPHA_HUB_DB_PATH"),
            "attachments_dir": os.getenv("ALPHA_HUB_ATTACHMENTS_DIR"),
            "context_limit": os.getenv("ALPHA_HUB_CONTEXT_LIMIT"),
            "system_prompt": os.getenv("ALPHA_HUB_SYSTEM_PROMPT"),
        }
        for k, v in env_overrides.items():
            if v is None or str(v).strip() == "":
                continue
            if k == "context_limit":
                try:
                    data[k] = int(v)
                except ValueError:
                    continue
            else:
                data[k] = v

        # llm overrides
        llm_data = dict(data.get("llm") or {})
        if os.getenv("ALPHA_HUB_LLM_ENABLED") is not None:
            llm_data["enabled"] = os.getenv("ALPHA_HUB_LLM_ENABLED", "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
        if os.getenv("ALPHA_HUB_LLM_MODE"):
            llm_data["mode"] = os.getenv("ALPHA_HUB_LLM_MODE", "mock").strip().lower()
        if os.getenv("ALPHA_HUB_LLM_BASE_URL"):
            llm_data["base_url"] = os.getenv("ALPHA_HUB_LLM_BASE_URL")
        if os.getenv("ALPHA_HUB_LLM_API_KEY"):
            llm_data["api_key"] = os.getenv("ALPHA_HUB_LLM_API_KEY")
        if os.getenv("ALPHA_HUB_LLM_MODEL"):
            llm_data["model"] = os.getenv("ALPHA_HUB_LLM_MODEL")
        if os.getenv("ALPHA_HUB_LLM_STREAM_PATH"):
            llm_data["stream_path"] = os.getenv("ALPHA_HUB_LLM_STREAM_PATH")
        if os.getenv("ALPHA_HUB_LLM_TIMEOUT_S"):
            try:
                llm_data["timeout_s"] = float(os.getenv("ALPHA_HUB_LLM_TIMEOUT_S", "30"))
            except ValueError:
                pass
        data["llm"] = llm_data

        return KernelConfig.model_validate(data)

