"""Review quality must guide correction without blocking usable sparse resumes."""
from app.diagnosis import quality
from app.diagnosis.schema import CandidateResume, CareerEntry


def test_missing_or_effectively_empty_resume_blocks_diagnosis():
    assert quality.review_quality(None)["blockers"]
    assert quality.review_quality(CandidateResume(experience=[CareerEntry()]))["blockers"]


def test_sparse_resume_does_not_require_noncritical_identity_or_work_history():
    report = quality.review_quality(CandidateResume(skills=["Python"]))
    assert report["blockers"] == []
    assert all(item["path"] and item["message"] for item in report["warnings"])


def test_illegal_and_reversed_dates_have_located_nonblocking_warnings():
    resume = CandidateResume(experience=[
        CareerEntry(company="A", role="工程师", start_date="2024.13", end_date="2025.01"),
        CareerEntry(company="B", role="工程师", start_date="2024.07", end_date="2023.12"),
    ])
    report = quality.review_quality(resume)
    assert report["blockers"] == []
    assert any(item["path"] == "experience.0.start_date" and "格式" in item["message"] for item in report["warnings"])
    assert any(item["path"] == "experience.1.end_date" and "早于" in item["message"] for item in report["warnings"])


def test_existing_experience_missing_critical_fields_is_visible_without_blanket_block():
    report = quality.review_quality(CandidateResume(experience=[CareerEntry(bullets=["使用 Python 开发接口"])]))
    assert report["blockers"] == []
    paths = {item["path"] for item in report["warnings"]}
    assert {"experience.0.company","experience.0.role","experience.0.start_date","experience.0.end_date"} <= paths


def test_overlap_and_explicit_conflict_are_review_questions_not_accusations():
    resume = CandidateResume(summary="我精通 Python。", skills=["不会 Python"], experience=[
        CareerEntry(company="A",role="工程师",start_date="2022.01",end_date="2023.12"),
        CareerEntry(company="B",role="工程师",start_date="2023.01",end_date="2024.12"),
    ])
    report = quality.review_quality(resume)
    assert report["blockers"] == []
    assert any("重叠" in item["message"] for item in report["warnings"])
    assert any("两处" in item["message"] or "矛盾" in item["message"] for item in report["warnings"])
    assert not any(term in str(report) for term in ("造假","虚假","不诚信"))
