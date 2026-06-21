"""Pydantic models used across the pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Hook(BaseModel):
    name: str
    url: str
    description: str
    tags: list[str] = Field(default_factory=list)


class Beat(BaseModel):
    role: Literal["hook_intro", "body", "cta"]
    narration: str
    broll_keywords: list[str] = Field(default_factory=list)
    target_seconds: float = 4.0


class Script(BaseModel):
    topic: str
    hook_name: str
    beats: list[Beat]

    @property
    def full_narration(self) -> str:
        return " ".join(b.narration for b in self.beats)

    @property
    def target_duration(self) -> float:
        return sum(b.target_seconds for b in self.beats)


class WordCue(BaseModel):
    word: str
    start: float
    end: float


class Captions(BaseModel):
    cues: list[WordCue]