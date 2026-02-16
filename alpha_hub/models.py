from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Status = Literal["up", "degraded", "down"]
NotifyPolicy = Literal["explicit", "implicit_light", "none"]


# -------------------------
# HTTP envelopes & errors
# -------------------------

class OkEnvelope(BaseModel):
    status: Literal["ok"] = "ok"
    trace_id: str
    data: Any


class ErrorEnvelope(BaseModel):
    status: Literal["error"] = "error"
    code: str
    message: str
    trace_id: str
    data: Any = Field(default_factory=dict)


# -------------------------
# Capabilities
# -------------------------

class CapabilityItem(BaseModel):
    name: str
    status: Status
    notify_policy_default: NotifyPolicy
    last_changed_at_utc: str
    enabled: Optional[bool] = None
    mode: Optional[str] = None


class CapabilitiesResponse(BaseModel):
    items: List[CapabilityItem]


# -------------------------
# Attachments & messages
# -------------------------

AttachmentType = Literal["image", "audio", "file"]


class Attachment(BaseModel):
    id: str
    type: AttachmentType
    mime: str
    url: str
    sha256: str
    duration_ms: Optional[int] = None


class AttachmentRef(BaseModel):
    id: str


class AttachmentCreateResult(BaseModel):
    attachment: Attachment


Role = Literal["user", "assistant", "system"]


class MessageRecord(BaseModel):
    id: str
    conversation_id: str
    role: Role
    content_text: str
    created_at_utc: str
    client_request_id: Optional[str] = None
    attachments: List[AttachmentRef] = Field(default_factory=list)


class MessageCreateRequest(BaseModel):
    conversation_id: str
    content_text: str
    attachments: List[AttachmentRef] = Field(default_factory=list)
    client_request_id: Optional[str] = None


class MessageCreateResult(BaseModel):
    message: MessageRecord


class MessageListResult(BaseModel):
    items: List[MessageRecord]
    next_before: Optional[str] = None


# -------------------------
# WebSocket messages
# -------------------------

class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class CapabilityWarning(BaseModel):
    name: str
    status: Status
    notify: NotifyPolicy


class WsUserMessage(BaseModel):
    type: Literal["user_message"] = "user_message"
    trace_id: Optional[str] = None
    conversation_id: Optional[str] = None
    content_text: str
    attachments: List[AttachmentRef] = Field(default_factory=list)
    client_request_id: Optional[str] = None


class WsCancel(BaseModel):
    type: Literal["cancel"] = "cancel"
    trace_id: str
    reason: Optional[str] = None


WsStage = Literal["queued", "thinking", "tool", "streaming", "done"]


class WsAssistantStatus(BaseModel):
    type: Literal["assistant_status"] = "assistant_status"
    trace_id: str
    stage: str
    detail: Optional[str] = None
    progress: Optional[float] = None


class WsAssistantDelta(BaseModel):
    type: Literal["assistant_delta"] = "assistant_delta"
    trace_id: str
    delta: str


class WsAssistantAppend(BaseModel):
    type: Literal["assistant_append"] = "assistant_append"
    trace_id: str
    message_id: str
    append_text: str


class WsAssistantDone(BaseModel):
    type: Literal["assistant_done"] = "assistant_done"
    trace_id: str
    reason: Literal["completed", "cancelled", "error"]
    message_id: Optional[str] = None
    usage: Usage = Field(default_factory=Usage)
    capability_warnings: List[CapabilityWarning] = Field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
