"""Pydantic models used across the pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Hook(BaseModel):
    name: str
    url: str
    description: str
    tags: list[str] = Field(default_factory=list)
    topic_seeds: list[str] = Field(default_factory=list)


class Beat(BaseModel):
    """A single visual+narration segment of a short-form video."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["hook_intro", "hook_reaction", "body", "cta"]
    narration: str
    broll_keywords: list[str] = Field(default_factory=list)
    target_seconds: float = 4.0

    # ── v2 viral fields (all optional with safe defaults) ──
    energy: Literal["high", "medium", "low"] = "medium"
    transition_hint: str = "auto"
    caption_emphasis: list[str] = Field(default_factory=list)
    speed: Literal["normal", "slow", "fast"] = "normal"


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