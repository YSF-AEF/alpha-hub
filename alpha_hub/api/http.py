from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse

from ..common.auth import require_bearer
from ..common.time_util import utc_now_iso
from ..common.trace import new_trace_id, new_id
from ..common.errors import ApiError

from ..models import (
    Attachment,
    AttachmentCreateResult,
    AttachmentRef,
    CapabilitiesResponse,
    CapabilityItem,
    MessageCreateRequest,
    MessageCreateResult,
    MessageListResult,
    MessageRecord,
    OkEnvelope,
)
from ..storage.attachments import AttachmentStore
from ..storage.db import SqliteStore

router = APIRouter()


def ok(trace_id: str, data: dict):
    return OkEnvelope(trace_id=trace_id, data=data)


@router.get("/health")
def health_check():
    # Health endpoint must be public (no auth)
    trace_id = new_trace_id()
    return ok(trace_id, {"service": "alpha_hub", "time_utc": utc_now_iso()}).model_dump()


@router.get("/capabilities")
def capabilities(request: Request, _: None = Depends(require_bearer)):
    trace_id = new_trace_id()
    registry = request.app.state.registry
    items = [
        CapabilityItem(
            name=s.name,
            status=s.status,
            notify_policy_default=s.notify_policy_default,
            last_changed_at_utc=s.last_changed_at_utc,
            enabled=s.enabled,
            mode=s.mode,
        )
        for s in registry.snapshot()
    ]
    return ok(trace_id, CapabilitiesResponse(items=items).model_dump()).model_dump()


@router.post("/attachments")
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    type: Optional[str] = Form(default=None),
    _: None = Depends(require_bearer),
):
    trace_id = new_trace_id()
    astore: AttachmentStore = request.app.state.attachments

    attachment_id = new_id()
    meta = astore.save(attachment_id=attachment_id, filename=file.filename or "file", fileobj=file.file)

    mime = file.content_type or "application/octet-stream"
    atype = type
    if atype is None:
        if mime.startswith("image/"):
            atype = "image"
        elif mime.startswith("audio/"):
            atype = "audio"
        else:
            atype = "file"

    url = f"/v1/attachments/{meta.attachment_id}/download"
    attachment = Attachment(id=meta.attachment_id, type=atype, mime=mime, url=url, sha256=meta.sha256)
    return ok(trace_id, AttachmentCreateResult(attachment=attachment).model_dump()).model_dump()


@router.get("/attachments/{attachment_id}/download")
def download_attachment(request: Request, attachment_id: str, _: None = Depends(require_bearer)):
    # v0: local dir prefix match
    astore: AttachmentStore = request.app.state.attachments
    base = astore.base_dir
    matches = list(base.glob(f"{attachment_id}__*"))
    if not matches:
        raise ApiError(code="NOT_FOUND", message="Attachment not found", http_status=404)
    return FileResponse(matches[0])


@router.post("/messages")
def post_message(request: Request, body: MessageCreateRequest, _: None = Depends(require_bearer)):
    # Non-streaming: store the user message. For streaming assistant responses, use WS.
    trace_id = new_trace_id()
    store: SqliteStore = request.app.state.store

    attachments = [a.model_dump() for a in body.attachments]  # [{'id': ...}]
    row = store.create_message(
        message_id=new_id(),
        conversation_id=body.conversation_id,
        role="user",
        content_text=body.content_text,
        client_request_id=body.client_request_id,
        attachments=attachments,
    )
    msg = MessageRecord(
        id=row.message_id,
        conversation_id=row.conversation_id,
        role=row.role,
        content_text=row.content_text,
        created_at_utc=row.created_at_utc,
        client_request_id=row.client_request_id,
        attachments=[AttachmentRef.model_validate(a) for a in row.attachments],
    )
    return ok(trace_id, MessageCreateResult(message=msg).model_dump()).model_dump()


@router.get("/conversations/{conversation_id}/messages")
def list_messages(
    request: Request,
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    before: Optional[str] = Query(default=None, description="Message ID for pagination"),
    _: None = Depends(require_bearer),
):
    trace_id = new_trace_id()
    store: SqliteStore = request.app.state.store

    before_ts: Optional[str] = None
    if before:
        row = store.get_message(before)
        if not row:
            raise ApiError(code="NOT_FOUND", message="before message not found", http_status=404)
        before_ts = row.created_at_utc

    rows = store.list_messages(conversation_id, limit=limit, before_created_at_utc=before_ts)
    items = [
        MessageRecord(
            id=r.message_id,
            conversation_id=r.conversation_id,
            role=r.role,
            content_text=r.content_text,
            created_at_utc=r.created_at_utc,
            client_request_id=r.client_request_id,
            attachments=[AttachmentRef.model_validate(a) for a in r.attachments],
        )
        for r in rows
    ]

    next_before = items[-1].id if len(items) == limit else None
    return ok(trace_id, MessageListResult(items=items, next_before=next_before).model_dump()).model_dump()