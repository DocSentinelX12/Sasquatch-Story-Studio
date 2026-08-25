"""Shared Phase 9 webhook event schema."""
from typing import Optional
from pydantic import BaseModel


class WebhookEvent(BaseModel):
    provider: str
    job_id: str                       # provider job id
    status: str                       # succeeded | failed | running | cancelled
    video_url: Optional[str] = None
    error: Optional[str] = None
    usage: Optional[dict] = None
    timestamp: Optional[str] = None   # ISO; replay protection when present
