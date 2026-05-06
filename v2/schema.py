# FILE: v2/schema.py
# PURPOSE: Define the staged per-book artifact schema that V2 accumulates in book.yaml.
# OWNS: V2 persisted artifact models for metadata, stages, blocks, chapters, overview, and the full book record.
# EXPORTS: BookArtifact, BlockArtifact, ChapterArtifact, DocumentMetadata, OverviewArtifact, StageState.
# DOCS: README.md, v2/process.py

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class DocumentMetadata(BaseModel):
    title: str
    slug: str
    source_path: str
    source_format: str
    language: str | None = None
    authors: list[str] = Field(default_factory=list)
    source_md: str = "source.md"
    artifact_yaml: str = "book.yaml"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class StageState(BaseModel):
    name: str
    status: Literal["pending", "ready", "running", "partial", "done", "failed"] = "pending"
    version: str = "0.1"
    updated_at: datetime = Field(default_factory=utc_now)
    notes: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)


class BlockArtifact(BaseModel):
    block_id: str
    order: int
    heading: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    text: str | None = None
    token_estimate: int | None = None
    mini_summary: str | None = None
    useful: bool | None = None
    stage_data: dict[str, Any] = Field(default_factory=dict)


class ChapterArtifact(BaseModel):
    chapter_id: str
    order: int
    title: str
    block_start: int | None = None
    block_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    short_summary: str | None = None
    detailed_summary: str | None = None
    blocks: list[str] = Field(default_factory=list)
    stage_data: dict[str, Any] = Field(default_factory=dict)


class OverviewArtifact(BaseModel):
    ultra_dense_summary: str | None = None
    key_themes: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    stage_data: dict[str, Any] = Field(default_factory=dict)


class BookArtifact(BaseModel):
    schema_version: str = "v2-alpha"
    metadata: DocumentMetadata
    stages: dict[str, StageState] = Field(default_factory=dict)
    blocks: list[BlockArtifact] = Field(default_factory=list)
    overview: OverviewArtifact = Field(default_factory=OverviewArtifact)
    chapters: list[ChapterArtifact] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def touch(self) -> "BookArtifact":
        self.metadata.updated_at = utc_now()
        return self
