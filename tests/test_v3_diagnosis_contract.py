"""V3 candidate acceptance contracts, using synthetic local inputs only."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.diagnosis import engine, schema
from app.diagnosis.schema import CandidateResume, CareerEntry, DiagnosisRequest, Target
from app.diagnosis.scoring import calculate_timeline, score_match


def candidate():
    return CandidateResume(
        name="合成候选人", title="后端工程师", summary="使用 Python 开发业务接口。",
        skills=["Python"], experience=[CareerEntry(
            heading="2023.01—2025.12 合成公司｜后端工程师", company="合成公司",
            role="后端工程师", start_date="2023.01", end_date="2025.12",
            bullets=["使用 Python 开发业务接口，负责需求核对和测试。"],
        )],
    )


def requirement(**changes):
    result = {"id":"skill-python", "factor_id":"skills", "label":"Python",
              "description":"Python", "weight":100, "enabled":True,
              "hard_gate":False, "source":"user_jd"}
    return {**result, **changes}


def test_role_is_required_even_when_company_is_supplied():
    with pytest.raises(ValidationError):
        Target(company="纯虚构企业", role="  ")


def test_empty_scope_and_empty_resume_cannot_start_diagnosis():
    with pytest.raises(ValidationError):
        DiagnosisRequest(resume=candidate(), target=Target(role="后端工程师"), enabled_sections=[])
    with pytest.raises(ValueError):
        engine.run_diagnosis(CandidateResume(name="只有姓名"), Target(role="后端工程师"))


def test_blank_nested_fields_cannot_masquerade_as_an_analyzable_resume():
    with pytest.raises(ValueError):
        engine.run_diagnosis(CandidateResume(experience=[CareerEntry()], skills=["  "]), Target(role="后端工程师"))


def test_malformed_success_is_rejected_as_a_failed_module(monkeypatch):
    monkeypatch.setitem(engine.RUNNERS, "potential", lambda *args:{"status":"ok"})
    result = engine.run_diagnosis(candidate(), Target(role="后端工程师"), enabled_sections=["potential"])
    assert result["dimensions"]["potential"]["status"] == "error"
    assert result["suggestions"] == []


def test_unrelated_match_evidence_is_not_published_as_success(monkeypatch):
    monkeypatch.setitem(engine.RUNNERS, "match", lambda *args:{
        "status":"ok", "score":100, "requirements":[{
            "id":"unrelated", "coefficient":1, "effective_weight":1,
            "factor_id":"skills", "label":"Rust", "status":"已体现", "reason":"synthetic",
            "evidence_refs":[{"path":"skills.0","original":"编造的 Rust 能力"}],
        }],
    })
    result = engine.run_diagnosis(candidate(), Target(role="后端工程师"), enabled_sections=["match"])
    assert result["dimensions"]["match"]["status"] == "error"
    assert result["suggestions"] == []


def test_unknown_requirement_does_not_silently_reuse_generic_skill_expectations():
    result = score_match(candidate(), Target(role="后端工程师"), requirements=[requirement(description="具备跨境税务筹划能力")])
    assert result["score"] is None
    assert result["requirements"][0]["status"] == "无法判断"


def test_unfamiliar_english_skill_is_not_replaced_by_profile_defaults():
    resume = candidate()
    result = score_match(resume, Target(role="后端工程师"), requirements=[requirement(description="Rust")])
    assert result["score"] == 0
    resume.skills.append("Rust")
    assert score_match(resume, Target(role="后端工程师"), requirements=[requirement(description="Rust")])["score"] > 0


def test_explicit_negative_skill_is_distinct_from_missing_evidence():
    resume = CandidateResume(summary="我未掌握 Python。")
    result = score_match(resume, Target(role="后端工程师"), requirements=[requirement()])
    row = result["requirements"][0]
    assert row["status"] == "明确不满足"
    assert row["evidence_refs"][0]["original"] == resume.summary


def test_higher_recorded_degree_meets_bachelors_or_above_requirement():
    from app.models import Education
    resume = candidate()
    resume.education = [Education(heading="合成大学｜硕士，已毕业")]
    req = requirement(factor_id="education", label="本科以上", description="本科及以上学历")
    result = score_match(resume, Target(role="后端工程师"), requirements=[req])
    assert result["score"] == 100
    assert result["requirements"][0]["status"] == "已体现"


def test_sync_parse_primitive_preserves_original_bytes_and_matches_http_parse():
    from io import BytesIO
    from docx import Document
    from app.diagnosis import api
    doc = Document()
    doc.add_paragraph("合成候选人\n专业技能\nPython SQL")
    buf = BytesIO()
    doc.save(buf)
    raw = buf.getvalue()
    parsed = api.parse_document("synthetic.docx", raw)
    with TestClient(app) as client:
        response = client.post("/api/diagnosis/parse", files={"file":("synthetic.docx", raw)})
    assert response.status_code == 200
    assert response.json() == parsed
    assert raw == buf.getvalue()


def test_cancelled_parse_does_not_begin_extraction(monkeypatch):
    from app.diagnosis import api
    def unexpected(*args):
        pytest.fail("cancelled parsing must not start extraction")
    monkeypatch.setattr(api,"extract_file",unexpected)
    with pytest.raises(ValueError,match="解析已取消"):
        api.parse_document("synthetic.docx",b"unused synthetic bytes",should_cancel=lambda:True)


def test_cancel_after_extraction_prevents_structured_field_work(monkeypatch):
    from app.diagnosis import api
    import app.parser as parser
    extracted=[]
    def extract(*args):
        extracted.append(True)
        return "合成候选人\n专业技能\nPython",[],"docx"
    def unexpected(*args):
        pytest.fail("field extraction must not continue after cancellation")
    monkeypatch.setattr(api,"extract_file",extract)
    monkeypatch.setattr(parser,"parse_resume",unexpected)
    with pytest.raises(ValueError,match="解析已取消"):
        api.parse_document("synthetic.docx",b"unused synthetic bytes",should_cancel=lambda:bool(extracted))


def test_all_failed_results_cannot_generate_suggestions(monkeypatch):
    def fail(*args):
        raise RuntimeError("synthetic module failure")
    monkeypatch.setattr(engine, "RUNNERS", {key:fail for key in engine.RUNNERS})
    report = engine.run_diagnosis(candidate(), Target(role="后端工程师"))
    assert report["report_status"] == "failed"
    assert report["scope"]["can_generate_suggestions"] is False
    assert report["suggestions"] == []


def test_cancel_keeps_finished_results_and_does_not_run_remaining_modules():
    seen = []
    report = engine.run_diagnosis(
        candidate(), Target(role="后端工程师"),
        on_section=lambda key,result:seen.append((key,result["status"])),
        should_cancel=lambda:len(seen) >= 1,
    )
    assert report["dimensions"]["match"]["status"] == "ok"
    assert set(report["scope"]["cancelled"]) == {"experience","potential","motivation","verification"}
    assert report["report_status"] == "partial"
    assert len(seen) == 5


def test_rebuild_reuses_sections_and_limits_advice_to_successful_modules():
    sections = {key:{"status":"error", "conclusion":"synthetic failed"} for key in engine.RUNNERS}
    sections["verification"] = {"status":"ok", "issues":[], "questions":[]}
    report = engine.rebuild_report(candidate(), Target(role="后端工程师"), sections, "2026-10-30")
    assert report["dimensions"] == sections
    assert report["report_status"] == "partial"
    assert report["suggestions"] == []


def test_insufficient_potential_does_not_pad_supporting_evidence():
    result = engine._potential(CandidateResume(skills=["Python"]), Target(role="后端工程师"), "2026-10-30")
    assert result["rating"] == "无法判断"
    assert result["supporting_signals"] == []
    assert result["evidence_count"] == 0


def test_missing_dates_do_not_publish_zero_total_as_known_tenure():
    resume = candidate()
    resume.experience[0].start_date = ""
    result = calculate_timeline(resume, as_of="2026-10-30")
    assert result["months_total"] is None
    assert result["total_status"] == "unknown"
    assert "无法计算" in result["summary"]


def test_confirmed_weights_are_checked_and_used_for_score():
    target = Target(role="后端工程师", job_description="Python SQL")
    items = [requirement(weight=25), requirement(id="skill-sql", label="SQL", description="SQL", weight=75)]
    request = DiagnosisRequest(resume=candidate(), target=target, requirements=items)
    result = score_match(candidate(), target, requirements=request.requirements)
    assert result["score"] == 25
    assert result["raw_score"] == pytest.approx(25)
    assert result["display_score"] == 25
    assert len(result["requirements"]) == 2
    assert sum(row["contribution"] for row in result["requirements"]) == pytest.approx(25)
    assert result["requirements"][0]["evidence_refs"]
    assert result == score_match(candidate(), target, requirements=request.requirements)
    with pytest.raises(ValidationError):
        DiagnosisRequest(resume=candidate(), target=target, requirements=[requirement(weight=99)])


def test_disabled_requirement_is_not_scored_and_description_is_authoritative():
    items = [requirement(description="SQL"), requirement(id="ignored", weight=100, enabled=False)]
    result = score_match(candidate(), Target(role="后端工程师"), requirements=items)
    assert result["score"] == 0
    assert result["requirements"][0]["status"] == "简历未体现"
    assert result["requirements"][1]["contribution"] == 0


def test_empty_duplicate_or_nonfinite_requirement_weights_are_rejected():
    target = Target(role="后端工程师")
    for items in ([], [requirement(), requirement()], [requirement(weight=float("nan"))],
                  [requirement(weight=-1)], [requirement(weight=101)], [requirement(enabled=False)]):
        with pytest.raises((ValidationError, ValueError)):
            DiagnosisRequest(resume=candidate(), target=target, requirements=items)


def test_requirements_endpoint_discloses_generic_model_and_jd_source():
    with TestClient(app) as client:
        generic = client.post("/api/diagnosis/requirements", json={"target":{"role":"后端工程师"}})
        assert generic.status_code == 200
        body = generic.json()
        assert body["source"] == "generic_model"
        assert body["warnings"] and body["rule_version"]
        assert sum(item["weight"] for item in body["requirements"] if item["enabled"]) == pytest.approx(100)
        actual = client.post("/api/diagnosis/requirements", json={"target":{"role":"后端工程师","job_description":"必须掌握 Python，至少 2 年相关工作经验"}})
        assert actual.status_code == 200
        assert actual.json()["source"] == "user_jd"
        assert all(item["source"] == "user_jd" for item in actual.json()["requirements"])
        assert any(item["hard_gate"] for item in actual.json()["requirements"])


def test_report_endpoint_rejects_empty_resume_and_invalid_requirements():
    with TestClient(app) as client:
        response = client.post("/api/diagnosis/report", json={"resume":{},"target":{"role":"后端工程师"}})
        assert response.status_code == 422
        assert "简历" in response.json()["detail"]
        invalid = client.post("/api/diagnosis/report", json={"resume":candidate().model_dump(),"target":{"role":"后端工程师"},"requirements":[requirement(weight=99)]})
        assert invalid.status_code == 422
