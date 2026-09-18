from __future__ import annotations

# Starter list -- deliberately small, not exhaustive. Tune based on real false-negative rate
# once this has run against a real inbox for a while.
KNOWN_ATS_DOMAINS = {
    "greenhouse.io",
    "lever.co",
    "myworkday.com",
    "icims.com",
    "taleo.net",
    "smartrecruiters.com",
    "ashbyhq.com",
    "jobvite.com",
    "bamboohr.com",
    "workable.com",
    "breezy.hr",
    "linkedin.com",
}
SUBJECT_KEYWORDS = {
    "interview",
    "application",
    "recruiter",
    "opportunity",
    "position",
    "role",
    "hiring",
    "job offer",
    "phone screen",
    "next steps",
    "thank you for applying",
    "your application",
}
BODY_KEYWORDS = {
    "resume",
    "cv",
    "job description",
    "interview",
    "recruiter",
    "hiring manager",
    "position",
    "compensation",
    "offer letter",
}


def passes_prefilter(from_addr: str, subject: str | None, body_text: str | None) -> bool:
    domain = from_addr.rsplit("@", 1)[-1].lower() if "@" in from_addr else ""
    if any(domain == d or domain.endswith("." + d) for d in KNOWN_ATS_DOMAINS):
        return True

    subject_l = (subject or "").lower()
    if any(keyword in subject_l for keyword in SUBJECT_KEYWORDS):
        return True

    body_l = (body_text or "").lower()[:2000]
    return any(keyword in body_l for keyword in BODY_KEYWORDS)
