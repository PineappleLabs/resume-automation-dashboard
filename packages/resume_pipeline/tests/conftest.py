from __future__ import annotations

import pytest

from resume_pipeline.schema import (
    Bullet,
    EducationEntry,
    ExperienceEntry,
    Header,
    ProjectEntry,
    ResumeContent,
    SkillLine,
)


@pytest.fixture
def sample_content() -> ResumeContent:
    return ResumeContent(
        header=Header(
            name="Test Person",
            location="Remote",
            email="test@example.com",
            phone_display="(555) 555-5555",
            phone_href="+15555555555",
            linkedin="linkedin.com/in/testperson",
        ),
        education=[
            EducationEntry(
                id="edu-1",
                organization="Test University",
                title="B.S. Computer Science",
                dates="08/2016 - 05/2020",
                bullets=[
                    Bullet(id="edu-1-b1", text="Relevant coursework.", priority=50),
                    Bullet(id="edu-1-b2", text="Dean's list.", priority=30),
                ],
            )
        ],
        skills=[
            SkillLine(id="skill-1", text="Python, Go", priority=80),
            SkillLine(id="skill-2", text="AWS, Docker", priority=40),
        ],
        experience=[
            ExperienceEntry(
                id="exp-1",
                organization="Acme Corp",
                title="Senior Engineer",
                dates="06/2021 - Present",
                bullets=[
                    Bullet(
                        id="exp-1-b1",
                        text="Pinned achievement bullet.",
                        priority=90,
                        pinned=True,
                    ),
                    Bullet(id="exp-1-b2", text="Lower priority bullet.", priority=20),
                ],
            ),
            ExperienceEntry(
                id="exp-2",
                organization="Beta LLC",
                title="Engineer",
                dates="01/2019 - 05/2021",
                bullets=[
                    Bullet(id="exp-2-b1", text="Another achievement.", priority=60),
                    Bullet(id="exp-2-b2", text="Least important bullet.", priority=10),
                ],
            ),
        ],
        projects=[
            ProjectEntry(id="proj-1", text="Built a thing.", priority=70),
            ProjectEntry(id="proj-2", text="Built another thing.", priority=15),
        ],
    )
