from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class Preferences(BaseModel):
    mood: str = ""
    genres: list[str] = Field(default_factory=list)
    company: str = ""
    max_minutes: int | None = Field(default=None, ge=1, le=600)
    title_query: str = Field(default="", max_length=200)
    avoid: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: UUID
    message: str = Field(min_length=1, max_length=3000)
    max_minutes: int | None = Field(default=None, ge=1, le=600)

    @field_validator("message")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("메시지를 입력하세요.")
        return value.strip()


class Recommendation(BaseModel):
    movie_id: str
    title: str
    year: int | None
    runtime: int | None
    genres: list[str]
    synopsis: str
    reason: str
    tip: str
    evidence: str
    poster: str | None = None
    rating: float | None = None
    votes: int | None = None
    source: str
    source_url: str | None = None
    evidence_chunks: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: UUID
    mode: Literal["demo", "live"]
    message: str
    preferences: Preferences
    recommendations: list[Recommendation] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source: str = "imdb"
    tool_trace: list[dict] = Field(default_factory=list)


class Feedback(BaseModel):
    session_id: UUID
    movie_id: str = Field(min_length=1, max_length=50)
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)
    mood_change: int = Field(default=0, ge=-5, le=5)
