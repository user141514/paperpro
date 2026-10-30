"""Evidence-based advice, not nine unconditional allegations."""
from __future__ import annotations

from app.diagnosis.schema import CandidateResume, CareerEntry, Target
from app.diagnosis.engine import run_diagnosis
from app.models import Entry, Education


def _complete():
    return CandidateResume(
        name="合成候选人", title="后端开发工程师",
        summary="五年后端系统与数据库开发经验；能解释自己承担的接口、部署与项目职责。",
        self_evaluation="希望继续从事后端系统与 API 工程。",
        skills=["Python", "SQL", "Docker", "Git"],
        experience=[CareerEntry(
            heading="2022.01–2025.06 合成科技 | 后端开发工程师",
            company="合成科技", role="后端开发工程师",
            start_date="2022.01", end_date="2025.06",
            bullets=[
                "负责 Python SQL API 开发，并与团队完成 Docker Git 部署。",
                "通过已核对的数据基线，从 100ms 降至 75ms，测量周期为两个月。",
            ],
        )],
        projects=[Entry(
            heading="系统服务项目",
            bullets=["通过 Python SQL 与 Docker 构建可复核的后端 API 服务。"],
        )],
        education=[Education(heading="2018.09–2022.06 示例大学 | 本科")],
        certificates=["已取得 CET-6"],
    )


def test_complete_resume_has_no_unfounded_gaps_or_high_priority():
    report=run_diagnosis(
        _complete(),
        Target(role="后端开发工程师",
               job_description="熟悉 Python SQL Docker Git；需要2年后端开发经验"),
        as_of="2026-10-19",
    )
    by_id={x["id"]:x for x in report["suggestions"]}
    assert len(by_id)<8  # Do not pad a strong resume to the old demo count.
    assert "advice-06" not in by_id
    assert "advice-07" not in by_id
    assert not [a for a in report["suggestions"] if a["priority"]=="高"]
    for advice in report["suggestions"]:
        assert all(advice[k] for k in ("location","original","problem","action","example"))
        assert advice["assessment"] in {"需要修正","可选深化"}


def test_missing_core_job_qualifications_are_specific_and_high_priority():
    report=run_diagnosis(
        CandidateResume(name="合成候选人",summary="正在转向后端岗位，尚未填写相关职责与技能。"),
        Target(role="后端开发工程师",
               job_description="熟悉 Python SQL Docker Git，需要2年后端开发经验"),
        as_of="2026-10-19",
    )
    by_id={x["id"]:x for x in report["suggestions"]}
    assert by_id["advice-02"]["priority"]=="高"
    assert by_id["advice-02"]["assessment"]=="需要修正"
    assert by_id["advice-04"]["priority"]=="高"
    assert by_id["advice-04"]["assessment"]=="需要修正"
    # Only hard filtering gaps may be marked high.
    assert all(x["id"] in {"advice-01","advice-02","advice-04","advice-05"}
               for x in report["suggestions"] if x["priority"]=="高")


def test_selected_optional_suggestion_exports_as_opportunity_not_allegation():
    from fastapi.testclient import TestClient
    from app.main import app

    report=run_diagnosis(
        _complete(),Target(role="后端开发工程师",
                           job_description="熟悉 Python SQL Docker Git，2年后端开发经验"),
        as_of="2026-10-19",
    )
    candidate=next(x for x in report["suggestions"] if x["id"]=="advice-03")
    assert candidate["assessment"]=="可选深化"
    result=TestClient(app).post("/api/diagnosis/export",json={
        "report":report,
        "selected_ids":[candidate["id"]],
        "kind":"todo","format":"txt",
    })
    assert result.status_code==200,result.text
    content=result.content.decode("utf-8-sig")
    assert "建议类别：可选深化" in content
    assert "优化机会：" in content
    assert "缺少统计口径" not in content


def test_dated_resume_without_metric_should_not_fake_a_missing_baseline():
    resume=_complete()
    resume.experience[0].bullets=[
        "负责 Python SQL API 开发；交付了已核实的两个接口模块。"
    ]
    report=run_diagnosis(
        resume, Target(role="后端开发工程师"), as_of="2026-10-19",
    )
    by_id={x["id"]:x for x in report["suggestions"]}
    assert "advice-06" not in by_id
