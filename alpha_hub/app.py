from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from .api.http import router as http_router
from .api.ws import router as ws_router
from .common.errors import ApiError
from .common.trace import new_trace_id
from .common.dotenv import load_dotenv_auto
from .storage.db import SqliteStore
from .storage.attachments import AttachmentStore
from .events.bus import InProcessEventBus
from .core.registry import CapabilityRegistry
from .core.orchestrator import Orchestrator
from .core.config import ConfigManager
from .capabilities.mock_llm import MockLlmProvider

try:
    # optional dependency (enabled when requirements include httpx)
    from .modules.llm_remote import RemoteChatCompletionsProvider, RemoteChatConfig
except Exception:  # noqa: BLE001
    RemoteChatCompletionsProvider = None  # type: ignore[assignment]
    RemoteChatConfig = None  # type: ignore[assignment]


def _build_llm(cfg) -> object:
    """Select an LLM provider based on config.

    Fallback rules:
    - If remote mode is requested but remote provider is unavailable -> mock.
    - If remote config is incomplete -> mock.
    """
    if not cfg.llm.enabled:
        return MockLlmProvider()

    if cfg.llm.mode == "remote":
        if RemoteChatCompletionsProvider is None:
            return MockLlmProvider()
        if not cfg.llm.base_url:
            return MockLlmProvider()
        return RemoteChatCompletionsProvider(
            RemoteChatConfig(
                base_url=cfg.llm.base_url,
                api_key=cfg.llm.api_key,
                model=cfg.llm.model,
                stream_path=cfg.llm.stream_path,
                timeout_s=cfg.llm.timeout_s,
            )
        )

    return MockLlmProvider()


def create_app() -> FastAPI:
    app = FastAPI(title="Alpha Hub Kernel (v0)")

    # Load .env (best-effort). Environment variables set by the process take precedence.
    load_dotenv_auto(override=False, allow_keys={"ALPHA_HUB_TOKEN"}, allow_prefixes={"ALPHA_HUB_LLM_"})

    # CORS (dev-friendly; tighten in prod)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Load config
    cfg = ConfigManager().load()
    app.state.config = cfg

    # Dependency injection via app.state
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent  # <repo>
    db_path = Path(cfg.db_path)
    if not db_path.is_absolute():
        db_path = repo_root / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    attachments_dir = Path(cfg.attachments_dir)
    if not attachments_dir.is_absolute():
        attachments_dir = repo_root / attachments_dir

    app.state.store = SqliteStore(db_path=str(db_path))
    app.state.attachments = AttachmentStore(base_dir=attachments_dir)

    app.state.bus = InProcessEventBus()
    app.state.registry = CapabilityRegistry()

    llm = _build_llm(cfg)
    app.state.orchestrator = Orchestrator(
        store=app.state.store,
        bus=app.state.bus,
        llm=llm,  # type: ignore[arg-type]
        context_limit=cfg.context_limit,
        system_prompt=cfg.system_prompt,
    )
    # Capabilities snapshot (for /v1/capabilities)
    # Default notify_policy is how clients should treat failures for this capability.
    llm_status = "up"
    if cfg.llm.mode == "remote" and not cfg.llm.api_key:
        llm_status = "down"
    app.state.registry.set(name="kernel", status="up", enabled=True, mode="server", notify_policy_default="none")
    app.state.registry.set(name="storage", status="up", enabled=True, mode="sqlite", notify_policy_default="none")
    app.state.registry.set(name="attachments", status="up", enabled=True, mode="fs", notify_policy_default="none")
    app.state.registry.set(name="events", status="up", enabled=True, mode="inprocess", notify_policy_default="none")
    app.state.registry.set(name="llm", status=llm_status, enabled=True, mode=cfg.llm.mode, notify_policy_default="explicit")


    @app.on_event("shutdown")
    def _shutdown() -> None:
        try:
            app.state.store.close()
        except Exception:
            pass

    @app.exception_handler(ApiError)
    async def api_error_handler(_, exc: ApiError):
        trace_id = new_trace_id()
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "status": "error",
                "code": exc.code,
                "message": exc.message,
                "trace_id": trace_id,
                "data": exc.data,
            },
        )

    app.include_router(http_router, prefix="/v1")
    app.include_router(ws_router, prefix="/v1")
    return app


app = create_app()