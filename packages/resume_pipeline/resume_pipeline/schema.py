from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SectionKey = Literal["education", "skills", "experience", "projects"]


class Header(BaseModel):
    name: str
    location: str
    email: str
    phone_display: str
    phone_href: str
    linkedin: str
    last_updated: str = "September 2024"


class Bullet(BaseModel):
    id: str
    text: str
    tech: str | None = None
    tags: list[str] = Field(default_factory=list)
    priority: int = 50
    pinned: bool = False
    summary: str | None = None


class EducationEntry(BaseModel):
    id: str
    organization: str
    title: str
    title_suffix: str | None = None
    dates: str
    tags: list[str] = Field(default_factory=list)
    priority: int = 50
    pinned: bool = False
    spacing_before: str | None = None
    spacing_after_header: str = "0.10 cm"
    spacing_after: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)
    summary: str | None = None


class SkillLine(BaseModel):
    id: str
    text: str
    tags: list[str] = Field(default_factory=list)
    priority: int = 50
    pinned: bool = False
    summary: str | None = None


class ExperienceEntry(BaseModel):
    id: str
    organization: str
    title: str
    dates: str
    tags: list[str] = Field(default_factory=list)
    priority: int = 50
    pinned: bool = False
    spacing_before: str | None = None
    spacing_after_header: str = "0.10 cm"
    spacing_after: str | None = "0.2 cm"
    bullets: list[Bullet] = Field(default_factory=list)
    summary: str | None = None


class ProjectEntry(BaseModel):
    id: str
    text: str
    tech: str | None = None
    tags: list[str] = Field(default_factory=list)
    priority: int = 50
    pinned: bool = False
    summary: str | None = None


class ResumeContent(BaseModel):
    header: Header
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[SkillLine] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)


class EntrySelection(BaseModel):
    entry_id: str
    bullet_ids: list[str]


class Selection(BaseModel):
    rationale: str
    section_order: list[SectionKey] = Field(
        default_factory=lambda: ["education", "skills", "experience", "projects"]
    )
    education: list[EntrySelection] = Field(default_factory=list)
    skill_line_ids: list[str] = Field(default_factory=list)
    experience: list[EntrySelection] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    bullet_priorities: dict[str, int] = Field(default_factory=dict)


class SelectionResponse(BaseModel):
    rationale: str
    section_order: list[SectionKey]
    education: list[EntrySelection]
    skill_line_ids: list[str]
    experience: list[EntrySelection]
    project_ids: list[str]
    bullet_priorities: dict[str, int]
