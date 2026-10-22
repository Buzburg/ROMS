"""Explicit MCP argument shapes; task_skills remains the provenance validator."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class StrictObject(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class EvidenceSource(StrictObject):
    id: str
    doc_id: str
    checksum: Digest
    chunk_ids: list[int]
    text: str
    content_hash: Digest


class EvidencePacket(StrictObject):
    task: str
    constraints: str
    sources: list[EvidenceSource]
    revision: Digest


class CitedEntry(StrictObject):
    text: str
    sources: list[str]


class SkillDraft(StrictObject):
    title: str
    when_to_use: str
    when_not_to_use: str
    prerequisites: list[CitedEntry]
    steps: list[CitedEntry]
    checks: list[CitedEntry]
    unknowns: list[str]


class NeedsInformation(StrictObject):
    status: Literal['needs_information']
    questions: list[str]


def encoded(value: BaseModel | str) -> str:
    return value.model_dump_json() if isinstance(value, BaseModel) else value
