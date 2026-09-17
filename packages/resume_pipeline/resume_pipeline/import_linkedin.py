from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml
from pypdf import PdfReader

from .schema import ResumeContent

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTENT_PATH = PROJECT_ROOT / "content" / "content.yaml"

PDF_ORG_MARKERS = [
    "Centers for Disease Control and Prevention",
    "Novarata, Inc.",
    "Equifax",
    "Georgia Tech Research Institute",
    "CockyDoodle Inc.",
    "Pineapple Labs",
    "Superior Flow Solutions",
]


def extract_linkedin_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def summarize_for_review(pdf_path: Path) -> str:
    text = extract_linkedin_text(pdf_path)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def load_content(path: Path = CONTENT_PATH) -> ResumeContent:
    with path.open(encoding="utf-8") as handle:
        return ResumeContent.model_validate(yaml.safe_load(handle))


class _QuotedStr(str):
    pass


def _quoted_str_representer(dumper: yaml.Dumper, data: str) -> yaml.nodes.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


yaml.add_representer(_QuotedStr, _quoted_str_representer, Dumper=yaml.SafeDumper)

_QUOTED_FIELDS = frozenset(
    {"text", "tech", "title_suffix", "summary", "dates", "phone_display", "phone_href"}
)


def _quote_special_strings(obj: object) -> object:
    if isinstance(obj, dict):
        quoted: dict = {}
        for key, value in obj.items():
            if key in _QUOTED_FIELDS and isinstance(value, str):
                quoted[key] = _QuotedStr(value)
            else:
                quoted[key] = _quote_special_strings(value)
        return quoted
    if isinstance(obj, list):
        return [_quote_special_strings(item) for item in obj]
    return obj


def _experience_sort_key(entry) -> tuple[int, int]:
    match = re.search(r"(\d{2})/(\d{4})\s*-\s*(?:(\d{2})/(\d{4})|Present)", entry.dates)
    if not match:
        return (0, 0)
    end_month = int(match.group(3) or "12")
    end_year = int(match.group(4) or "2099")
    return (end_year, end_month)


def _sort_experience(content: ResumeContent) -> None:
    content.experience.sort(key=_experience_sort_key, reverse=True)


def save_content(content: ResumeContent, path: Path = CONTENT_PATH) -> None:
    _sort_experience(content)
    payload = _quote_special_strings(content.model_dump(exclude_none=True))
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
    )


def collect_all_ids(content: ResumeContent) -> list[str]:
    ids: list[str] = []
    for entry in content.education:
        ids.append(entry.id)
        ids.extend(bullet.id for bullet in entry.bullets)
    for line in content.skills:
        ids.append(line.id)
    for entry in content.experience:
        ids.append(entry.id)
        ids.extend(bullet.id for bullet in entry.bullets)
    for project in content.projects:
        ids.append(project.id)
    return ids


def validate_content(content: ResumeContent, pdf_path: Path | None = None) -> list[str]:
    issues: list[str] = []

    ids = collect_all_ids(content)
    duplicate_ids = [item for item, count in Counter(ids).items() if count > 1]
    if duplicate_ids:
        issues.append(f"Duplicate IDs: {', '.join(duplicate_ids)}")

    org_dates: list[tuple[str, str]] = []
    for entry in content.experience:
        key = (entry.organization.strip().lower(), entry.dates.strip())
        if key in org_dates:
            issues.append(
                f"Duplicate experience entry: {entry.organization} ({entry.dates})"
            )
        org_dates.append(key)

        if not entry.bullets:
            issues.append(f"Experience entry {entry.id} has no bullets")

        bullet_texts = [bullet.text.strip().lower() for bullet in entry.bullets]
        seen_texts = set()
        for bullet in entry.bullets:
            normalized = re.sub(r"\s+", " ", bullet.text.strip().lower())
            if normalized in seen_texts:
                issues.append(
                    f"Duplicate bullet text in {entry.id}: {bullet.id}"
                )
            seen_texts.add(normalized)

    for entry in content.education:
        if not entry.bullets:
            issues.append(f"Education entry {entry.id} has no bullets")

    if pdf_path and pdf_path.exists():
        text = extract_linkedin_text(pdf_path)
        yaml_orgs = {entry.organization.lower() for entry in content.experience}
        for marker in PDF_ORG_MARKERS:
            if marker.lower() in text.lower():
                matched = any(
                    marker.split(",")[0].lower() in org for org in yaml_orgs
                )
                if not matched:
                    issues.append(f"LinkedIn org not in content.yaml: {marker}")

    return issues


def merge_from_linkedin_pdf(pdf_path: Path) -> ResumeContent:
    """Merge LinkedIn PDF experience into content.yaml (idempotent on re-run)."""
    content = load_content()
    text = extract_linkedin_text(pdf_path)

    if "Centers for Disease Control and Prevention" in text:
        cdc = next(entry for entry in content.experience if entry.id == "exp-cdc")
        cdc.organization = "Centers for Disease Control and Prevention"
        cdc.title = "Full Stack Engineer"
        cdc.bullets = [
            bullet
            for bullet in cdc.bullets
            if bullet.id not in {"exp-cdc-b1", "exp-cdc-b2"}
        ]
        cdc.bullets = [
            {
                "id": "exp-cdc-b1",
                "text": (
                    "Year 2 was spent on the New Data Source Development Team in support "
                    "of the National Syndromic Surveillance Program. Created and maintained "
                    "pipelines for the intake, analysis, and visualization of Public Health Data "
                    "from a variety of sources to monitor and predict national health emergencies. "
                    "Developed AI enabled python and java scripts to sanitize and prepare data "
                    "for entry into SQL databases."
                ),
                "tech": "Python, Java, MS SQL",
                "tags": [
                    "python",
                    "java",
                    "sql",
                    "ml",
                    "data-pipeline",
                    "healthcare",
                    "big-data",
                    "visualization",
                ],
                "priority": 98,
                "pinned": True,
                "summary": "Syndromic surveillance data pipelines with AI-enabled Python/Java ETL",
            },
            {
                "id": "exp-cdc-b2",
                "text": (
                    "Previously worked in support of the National Center for Chronic Disease "
                    "Prevention and Health Promotion's Cancer profiling and screening app, added "
                    "new functionality and security features to protect and validate user data."
                ),
                "tech": "Kotlin, .NET, C\\#, MySQL, Swift",
                "tags": [
                    "mobile",
                    "kotlin",
                    "dotnet",
                    "csharp",
                    "mysql",
                    "swift",
                    "security",
                    "healthcare",
                ],
                "priority": 92,
                "summary": "Cancer profiling mobile app with security and data validation features",
            },
            {
                "id": "exp-cdc-b3",
                "text": (
                    "Additionally was responsible for maintaining and developing a variety of "
                    "mobile and web apps on both Android and iOS in a variety of frameworks, "
                    "all subject to section 508 compliance for accessibility regulations."
                ),
                "tech": "Kotlin, Swift, Ionic, Javascript, .NET",
                "tags": [
                    "mobile",
                    "android",
                    "ios",
                    "accessibility",
                    "section-508",
                    "web",
                ],
                "priority": 88,
                "summary": "Cross-platform mobile/web apps with Section 508 accessibility compliance",
            },
        ] + cdc.bullets
        from .schema import Bullet

        cdc.bullets = [Bullet.model_validate(item) for item in cdc.bullets[:3]]

    gtri = next((entry for entry in content.experience if entry.id == "exp-gtri"), None)
    if gtri:
        gtri.title = "Student Researcher"

    existing_ids = {entry.id for entry in content.experience}
    new_entries = []

    if "exp-equifax" not in existing_ids and "Equifax" in text:
        from .schema import ExperienceEntry, Bullet

        new_entries.append(
            ExperienceEntry(
                id="exp-equifax",
                organization="Equifax",
                title="Quality Engineer",
                dates="07/2022 - 01/2023",
                tags=["qa", "testing", "java", "karate", "cucumber", "rest-api", "devops"],
                priority=78,
                spacing_after_header="0.1 cm",
                spacing_after="0.2 cm",
                summary="Quality engineer maintaining automated tests and REST API validation at Equifax",
                bullets=[
                    Bullet(
                        id="exp-equifax-b1",
                        text=(
                            "Updated and maintained automated testing scripts using the Java "
                            "frameworks Karate and Cucumber, including the creation of new test cases."
                        ),
                        tech="Java, Karate, Cucumber",
                        tags=["java", "testing", "automation", "karate", "cucumber"],
                        priority=76,
                        summary="Automated test maintenance with Karate and Cucumber",
                    ),
                    Bullet(
                        id="exp-equifax-b2",
                        text=(
                            "Manually tested and filed bug reports for various government service "
                            "REST endpoints."
                        ),
                        tech="REST API",
                        tags=["testing", "rest-api", "qa", "government"],
                        priority=74,
                        summary="Manual REST API testing and bug reporting for government services",
                    ),
                    Bullet(
                        id="exp-equifax-b3",
                        text="Provided on call support during production deployments of live services.",
                        tags=["devops", "on-call", "production", "deployment"],
                        priority=70,
                        summary="On-call production deployment support",
                    ),
                ],
            )
        )

    if "exp-cockydoodle" not in existing_ids and "CockyDoodle Inc." in text:
        from .schema import ExperienceEntry, Bullet

        new_entries.append(
            ExperienceEntry(
                id="exp-cockydoodle",
                organization="CockyDoodle Inc.",
                title="Android/iOS Developer",
                dates="09/2018 - 05/2019",
                tags=["mobile", "android", "ios", "sql", "json", "startup"],
                priority=68,
                spacing_after_header="0.1 cm",
                spacing_after="0.2 cm",
                summary="Native iOS and Android developer for startup prototype app",
                bullets=[
                    Bullet(
                        id="exp-cockydoodle-b1",
                        text=(
                            "Developed native versions of startup company's prototype app on both iOS "
                            "and Android."
                        ),
                        tech="Swift, Kotlin",
                        tags=["mobile", "android", "ios", "native"],
                        priority=67,
                        summary="Native iOS and Android prototype app development",
                    ),
                    Bullet(
                        id="exp-cockydoodle-b2",
                        text=(
                            "Handled queries to SQL database to dynamically update app data through "
                            "JSON objects."
                        ),
                        tech="SQL, JSON",
                        tags=["sql", "json", "mobile", "backend"],
                        priority=65,
                        summary="SQL-backed dynamic app data via JSON",
                    ),
                ],
            )
        )

    if "exp-pineapple-labs" not in existing_ids and "Pineapple Labs" in text:
        from .schema import ExperienceEntry, Bullet

        new_entries.append(
            ExperienceEntry(
                id="exp-pineapple-labs",
                organization="Pineapple Labs",
                title="Founder",
                dates="08/2016 - 01/2019",
                tags=["founder", "mobile", "android", "game-dev", "3d-printing", "startup"],
                priority=62,
                spacing_after_header="0.1 cm",
                spacing_after="0.2 cm",
                summary="Founder of Pineapple Labs mobile apps, games, and 3D printing services",
                bullets=[
                    Bullet(
                        id="exp-pineapple-b1",
                        text="Front and backend developer on Android applications and games.",
                        tech="Java, Android",
                        tags=["android", "mobile", "fullstack"],
                        priority=64,
                        summary="Full stack Android app and game development",
                    ),
                    Bullet(
                        id="exp-pineapple-b2",
                        text=(
                            "Released mobile phone business management and simulation game. Single "
                            "developer, gained over 10,000 downloads post launch."
                        ),
                        tech="Android, Java",
                        tags=["mobile", "game-dev", "android", "indie"],
                        priority=63,
                        summary="Solo-developed Android game with 10,000+ downloads",
                    ),
                    Bullet(
                        id="exp-pineapple-b3",
                        text="Providing online 3D printing services with custom built 3D printers.",
                        tags=["3d-printing", "hardware", "maker"],
                        priority=55,
                        summary="Custom 3D printer build and online printing services",
                    ),
                    Bullet(
                        id="exp-pineapple-b4",
                        text="Creating free online tutorials and instructional content on website.",
                        tags=["technical-writing", "education", "web"],
                        priority=50,
                        summary="Technical tutorials and instructional web content",
                    ),
                ],
            )
        )

    if "exp-superior-flow" not in existing_ids and "Superior Flow Solutions" in text:
        from .schema import ExperienceEntry, Bullet

        new_entries.append(
            ExperienceEntry(
                id="exp-superior-flow",
                organization="Superior Flow Solutions",
                title="IT/Web Developer",
                dates="11/2017 - 07/2018",
                tags=["web", "frontend", "crm", "automation"],
                priority=58,
                spacing_after_header="0.1 cm",
                spacing_after=None,
                summary="Web developer and CRM document automation at Superior Flow Solutions",
                bullets=[
                    Bullet(
                        id="exp-superior-flow-b1",
                        text="Frontend web development and website design.",
                        tags=["web", "frontend", "design"],
                        priority=57,
                        summary="Frontend web development and website design",
                    ),
                    Bullet(
                        id="exp-superior-flow-b2",
                        text=(
                            "Automating and designing document processing/formats for Customer "
                            "Relationship Management software"
                        ),
                        tags=["crm", "automation", "documents"],
                        priority=56,
                        summary="CRM document processing automation and format design",
                    ),
                ],
            )
        )

    if new_entries:
        content.experience.extend(new_entries)
        _sort_experience(content)

    frameworks = next(line for line in content.skills if line.id == "skills-frameworks")
    if "Section 508" not in frameworks.text:
        frameworks.text = frameworks.text.replace(
            "AI/ML", "AI/ML; Section 508"
        )
    if "section-508" not in frameworks.tags:
        frameworks.tags.append("section-508")
        frameworks.tags.append("accessibility")

    return content


def merge_and_validate(pdf_path: Path) -> tuple[ResumeContent, list[str]]:
    content = merge_from_linkedin_pdf(pdf_path)
    issues = validate_content(content, pdf_path)
    if not issues:
        save_content(content)
    return content, issues


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m resume_pipeline.import_linkedin Profile.pdf          # print extracted text")
        print("  python -m resume_pipeline.import_linkedin Profile.pdf --merge  # merge into content.yaml")
        print("  python -m resume_pipeline.import_linkedin Profile.pdf --check  # validate content.yaml")
        raise SystemExit(1)

    pdf = Path(sys.argv[1])
    if "--merge" in sys.argv:
        content, issues = merge_and_validate(pdf)
        if issues:
            print("Merge blocked due to validation issues:")
            for issue in issues:
                print(f"  - {issue}")
            raise SystemExit(1)
        print(f"Merged LinkedIn content into {CONTENT_PATH}")
        print(f"Experience entries: {len(content.experience)}")
    elif "--check" in sys.argv:
        content = load_content()
        issues = validate_content(content, pdf)
        if issues:
            print("Validation issues:")
            for issue in issues:
                print(f"  - {issue}")
            raise SystemExit(1)
        print("No validation issues found.")
    else:
        print(summarize_for_review(pdf))
