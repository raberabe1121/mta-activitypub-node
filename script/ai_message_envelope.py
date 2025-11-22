"""AI Message Envelope v0.1 dataclass definition.

This module provides a serializable Envelope representation for agent-to-agent
messaging that can be used by LMTP handlers, workers, and SMTP senders. The
format is intentionally signatureless for v0.1 and is designed to be JSON
round-trippable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Union
from uuid import uuid4

AgentId = str
Payload = Union[str, Dict[str, Any]]


AGENT_ID_PATTERN = re.compile(r"^https?://[^\s/@]+/@[^\s/@]+$")


def _validate_agent_id(agent_id: AgentId) -> AgentId:
    if not AGENT_ID_PATTERN.match(agent_id):
        raise ValueError(
            "Agent ID must be an ActivityPub-style handle such as https://domain/@name"
        )
    return agent_id


def _normalise_recipients(recipients: Iterable[AgentId]) -> List[AgentId]:
    unique = []
    seen = set()
    for recipient in recipients:
        validated = _validate_agent_id(recipient)
        if validated not in seen:
            seen.add(validated)
            unique.append(validated)
    return unique


def _iso_timestamp(ts: Optional[datetime] = None) -> str:
    return (ts or datetime.now(timezone.utc)).isoformat()


@dataclass(slots=True)
class ThreadContext:
    """Threading metadata using ActivityPub-friendly fields."""

    context: Optional[str] = None
    in_reply_to: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        data: Dict[str, str] = {}
        if self.context:
            data["context"] = self.context
        if self.in_reply_to:
            data["inReplyTo"] = self.in_reply_to
        return data

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ThreadContext":
        data = data or {}
        return cls(
            context=data.get("context"),
            in_reply_to=data.get("inReplyTo") or data.get("in_reply_to"),
        )


@dataclass(slots=True)
class Envelope:
    """AI Message Envelope v0.1 representation.

    - Uses ActivityPub-style Agent IDs (https://domain/@name) for sender/recipients.
    - Supports text or JSON payloads.
    - Threads messages through ``context`` / ``inReplyTo`` metadata.
    - v0.1 intentionally excludes cryptographic signatures.
    """

    sender: AgentId
    recipients: List[AgentId]
    payload: Payload
    payload_type: str = "json"
    thread: ThreadContext = field(default_factory=ThreadContext)
    version: str = "v0.1"
    envelope_id: str = field(default_factory=lambda: f"urn:uuid:{uuid4()}")
    created_at: str = field(default_factory=_iso_timestamp)

    def __post_init__(self) -> None:
        self.sender = _validate_agent_id(self.sender)
        self.recipients = _normalise_recipients(self.recipients)
        if self.payload_type not in {"json", "text"}:
            raise ValueError("payload_type must be 'json' or 'text'")
        if self.payload_type == "json" and isinstance(self.payload, str):
            # Attempt to coerce valid JSON string into a native object for consistency
            try:
                self.payload = json.loads(self.payload)
            except json.JSONDecodeError:
                pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "id": self.envelope_id,
            "createdAt": self.created_at,
            "sender": self.sender,
            "recipients": self.recipients,
            "payload": self.payload,
            "payloadType": self.payload_type,
            "thread": self.thread.to_dict(),
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Envelope":
        return cls(
            sender=data["sender"],
            recipients=data.get("recipients", []),
            payload=data.get("payload"),
            payload_type=data.get("payloadType", "json"),
            thread=ThreadContext.from_dict(data.get("thread")),
            version=data.get("version", "v0.1"),
            envelope_id=data.get("id", f"urn:uuid:{uuid4()}"),
            created_at=data.get("createdAt", _iso_timestamp()),
        )

    @classmethod
    def from_json(cls, raw: Union[str, bytes]) -> "Envelope":
        return cls.from_dict(json.loads(raw))
