from __future__ import annotations

from ingest_gmail.prefilter import passes_prefilter


def test_known_ats_domain_passes():
    assert passes_prefilter("noreply@greenhouse.io", "Update on your application", "") is True


def test_ats_subdomain_passes():
    assert passes_prefilter("jobs@mail.lever.co", "hi", "") is True


def test_subject_keyword_passes():
    assert passes_prefilter("someone@example.com", "Interview scheduled", "") is True


def test_body_keyword_passes():
    assert passes_prefilter(
        "someone@example.com", "hi", "Attached is the job description and compensation details."
    ) is True


def test_unrelated_email_fails():
    assert passes_prefilter(
        "newsletter@randomblog.com", "Your weekly digest", "Check out our latest posts!"
    ) is False


def test_missing_at_sign_does_not_crash():
    assert passes_prefilter("not-an-email", "hi", "hi") is False
