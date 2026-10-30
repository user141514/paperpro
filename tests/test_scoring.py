"""Scoring contract: deterministic evidence, separation, sensitivity, no pretend validity."""
from __future__ import annotations
import copy
import random
import pytest
from app.models import Entry
from app.diagnosis.schema import CandidateResume, CareerEntry, Target
from app.diagnosis.engine import (
    run_diagnosis, load_rules, score_match, calculate_timeline,
    evaluate_ordinal_benchmarks, weight_sensitivity, rules_prompt,
)


def candidate(kind="strong"):
    base = CandidateResume(
        name="测试候选人", title="后端开发工程师",
        education=[{"heading": "2018.09 - 2022.06 本科计算机科学"}],
        experience=[CareerEntry(
            company="示例科技", role="后端开发工程师",
            start_date="2022.07", end_date="2025.06",
            heading="2022.07-2025.06 示例科技 | 后端开发工程师",
            bullets=["负责内部API开发，通过 SQL 索引优化使接口耗时降低20%，使用 Python Docker Git"],
        )],
        projects=[{"heading":"订单服务系统","bullets":["开发 Python SQL API，承担系统测试和数据库设计"]}],
        skills=["Python","SQL","Git","Docker"],
        summary="参与后端开发，具备 Python 与 SQL 技术经验",
        certificates=["CET-6"],
        source_text="虚构测试数据",
    )
    if kind == "partial":
        base.experience[0].bullets = ["参与内部后端开发与测试"]
        base.projects = [Entry(heading="课程项目", bullets=["开发一个小程序"])]
        base.skills = ["Python"]
    elif kind == "weak":
        base.title = "平面设计"
        base.experience = []
        base.projects = []
        base.skills = ["Figma","设计"]
        base.summary = "设计作品与视觉表达"
    elif kind == "empty":
        base = CandidateResume(name="候选人")
    return base


def target():
    return Target(role="后端开发工程师", company="测试公司",
                  job_description="任职要求：熟悉 Python SQL Docker Git，有 2 年开发经验，参与 API 与系统项目")


def test_single_rule_source_and_profile_normalization():
    rules=load_rules()
    assert rules["version"]
    assert len(rules["factors"]) >= 6
    for profile in rules["profiles"].values():
        assert abs(sum(profile["weights"].values())-1) < 1e-9
    prompt=rules_prompt()
    assert rules["version"] in prompt
    assert "不能" in prompt or "不得" in prompt


def test_job_family_routing_prioritizes_specialty_not_generic_engineer_suffix():
    from app.diagnosis.scoring import _profile
    rules = load_rules()
    assert _profile("后端开发工程师", rules)[0] == "software"
    assert _profile("数据工程师", rules)[0] == "data"
    assert _profile("数据开发工程师", rules)[0] == "data"
    assert _profile("数据产品经理", rules)[0] == "product"
    assert _profile("算法工程师", rules)[0] == "data"
    assert _profile("机器学习工程师", rules)[0] == "data"
    assert _profile("交互设计工程师", rules)[0] == "design"
    assert _profile("UX 设计师", rules)[0] == "design"
    assert _profile("工程师", rules)[0] == "general"


def test_repeated_score_is_exact_and_exposes_seven_factor_coefficients():
    scores = [score_match(candidate(), target()) for _ in range(6)]
    assert len({r["score"] for r in scores}) == 1
    row=scores[0]
    assert 0 <= row["score"] <= 100
    assert row["grade"] in {"高","中","低"}
    assert len(row["requirements"]) >= 7
    assert all(0 <= x["coefficient"] <= 1 for x in row["requirements"])
    assert all("weight" in x and "reason" in x and "evidence_refs" in x for x in row["requirements"])
    assert sum(x["effective_weight"] for x in row["requirements"]) == pytest.approx(1.0)


def test_stronger_job_evidence_improves_match():
    values=[score_match(candidate(kind),target())["score"] for kind in ("strong","partial","weak")]
    assert values[0]>values[1]>values[2], values
    assert values[0]-values[2]>=30


def test_declared_skills_vs_applied_evidence_have_different_strength():
    stated=CandidateResume(name="示例",title="后端开发工程师",
        skills=["Python","SQL","Git","Docker"])
    used=stated.model_copy(deep=True)
    used.experience=[CareerEntry(
        company="示例公司",role="后端开发工程师",
        start_date="2022.01",end_date="2025.02",
        heading="2022.01-2025.02 示例公司 | 后端开发工程师",
        bullets=["负责用 Python SQL Docker Git 完成后端系统项目"],
    )]
    jd=Target(role="后端开发工程师",job_description="熟悉 Python SQL Docker Git")
    stated_score=score_match(stated,jd)
    used_score=score_match(used,jd)
    assert used_score["score"] > stated_score["score"]+20
    assert next(r for r in stated_score["requirements"] if r["id"]=="skills")["coefficient"]==pytest.approx(0.55)
    assert next(r for r in used_score["requirements"] if r["id"]=="skills")["coefficient"]==pytest.approx(1.0)


def test_negated_skills_do_not_count_as_positive_evidence():
    clean=CandidateResume(name="示例", title="待转行")
    negated=clean.model_copy(deep=True)
    negated.summary="不熟悉 Python，也未掌握 SQL；没有 Docker 经验，也不会 Git。"
    jd=Target(role="后端开发工程师", job_description="熟悉 Python SQL Docker Git")
    coefficient=lambda c: next(x["coefficient"] for x in score_match(c,jd)["requirements"] if x["id"]=="skills")
    assert coefficient(clean)==0
    assert coefficient(negated)==0


def test_absence_and_negation_do_not_turn_into_positive_credentials():
    from app.models import Entry, Education

    r = CandidateResume(
        name="Synthetic Candidate",
        title="平面设计",
        summary="没有硕士学位，也不会开发接口；没有带队管理团队经验，希望未来进入金融行业。",
        education=[Education(heading="本科毕业，没有硕士学位")],
        projects=[Entry(heading="绘画作品", bullets=["完成视觉设计"])],
        experience=[CareerEntry(
            company="零售公司", role="平面设计", heading="2023.01–2024.12 零售公司",
            start_date="2023.01", end_date="2024.12",
            bullets=["负责平面设计与海报排版"],
        )],
    )
    target = Target(
        role="数据分析师",
        job_description="要求硕士学历、金融行业经验，并具备带队管理团队经验。",
    )
    mapped = {row["id"]: row for row in score_match(r, target)["requirements"]}
    assert mapped["education"]["coefficient"] == 0
    assert mapped["industry"]["coefficient"] == 0
    assert mapped["leadership"]["coefficient"] == 0

    job2 = Target(role="后端开发工程师", job_description="熟悉 Python SQL 系统 API 项目")
    mapped2 = {row["id"]: row for row in score_match(r, job2)["requirements"]}
    assert mapped2["projects"]["coefficient"] == 0


def test_no_identity_or_irrelevant_skill_bonus():
    a=candidate(); b=a.model_copy(deep=True)
    b.name="另一候选人"; b.email="different@example.test"; b.location="某地"
    b.skills += ["无关技能X","音乐","瑜伽"]
    assert score_match(a,target())["score"] == score_match(b,target())["score"]


def test_company_without_required_role_is_rejected():
    with pytest.raises(ValueError, match="目标职位"):
        Target(company="从未提供岗位描述的公司")


def test_unsupported_years_are_not_inferred():
    a=candidate(); a.experience[0].start_date="";a.experience[0].end_date="";a.experience[0].heading="示例科技 | 后端开发工程师"
    t=calculate_timeline(a, as_of="2026-10-19")
    assert t["dated_entries"] == 0
    assert t["months_total"] is None
    assert t["total_status"] == "unknown"
    assert "未知" in t["summary"] or "未" in t["summary"]


def test_related_work_years_do_not_count_unrelated_career_tenure():
    from app.diagnosis.schema import CareerEntry
    job = Target(
        role="后端开发工程师",
        job_description="需要 2 年后端开发经验，熟悉 Python SQL",
    )
    finance = CandidateResume(
        name="Synthetic Finance Applicant",
        title="财务经理",
        experience=[CareerEntry(
            heading="2012.01–2025.12 财务部门 | 会计",
            company="财务部门", role="会计",
            start_date="2012.01", end_date="2025.12",
            bullets=["负责财务报表、税务结算、成本核算"],
        )],
    )
    developer = CandidateResume(
        name="Synthetic Developer",
        title="后端开发工程师",
        experience=[CareerEntry(
            heading="2024.01–2025.12 科技企业 | 后端开发工程师",
            company="科技企业", role="后端开发工程师",
            start_date="2024.01", end_date="2025.12",
            bullets=["负责 Python SQL 接口和服务开发"],
        )],
    )
    def item(candidate):
        return next(r for r in score_match(candidate, job)["requirements"]
                    if r["id"] == "experience")
    unrelated = item(finance)
    relevant = item(developer)
    assert unrelated["coefficient"] == 0
    assert relevant["coefficient"] == 1
    assert "相关" in unrelated["reason"]

    # Adding a large unrelated career must not inflate a developer's job tenure.
    developer.experience.append(finance.experience[0])
    assert item(developer)["coefficient"] == 1


def test_overlapping_experience_counts_unique_calendar_months_not_double():
    r = CandidateResume(
        name="Synthetic",
        experience=[
            CareerEntry(
                company="A", role="后端开发工程师", heading="2022.01–2022.12 A | 后端开发工程师",
                start_date="2022.01", end_date="2022.12",
            ),
            CareerEntry(
                company="B", role="后端开发工程师", heading="2022.06–2023.05 B | 后端开发工程师",
                start_date="2022.06", end_date="2023.05",
            ),
        ],
    )
    timeline = calculate_timeline(r, as_of="2026-10-19")
    assert timeline["dated_entries"] == 2
    assert timeline["months_total"] == 17  # Jan 2022 through May 2023
    assert timeline["overlaps"]
    t = Target(role="后端开发工程师", job_description="需要 2 年开发经验，熟悉 Python")
    work = next(x for x in score_match(r, t)["requirements"] if x["id"] == "experience")
    assert work["coefficient"] == pytest.approx(17 / 24, abs=0.0001)
    assert work["coefficient"] < 1


def test_gap_and_overlap_calculated_from_calendar_without_moral_claim():
    a=candidate()
    a.experience=[
        CareerEntry(company="A",role="工程师",heading="A",start_date="2022.01",end_date="2022.03"),
        CareerEntry(company="B",role="工程师",heading="B",start_date="2022.08",end_date="2023.04"),
        CareerEntry(company="C",role="工程师",heading="C",start_date="2023.03",end_date="2024.01"),
    ]
    result=calculate_timeline(a,as_of="2026-10-19")
    assert result["gaps"][0]["days"]>=120
    assert result["overlaps"][0]["days"]>=1
    assert 0<=result["stability_score"]<=100
    assert all("path" in i and "original" in i for i in result["issues"])


def test_five_blocks_nonfatal_isolation_and_report_quality():
    report=run_diagnosis(candidate(),target(),as_of="2026-10-19")
    assert set(report["dimensions"])=={"match","experience","potential","motivation","verification"}
    assert all(v["status"]=="ok" for v in report["dimensions"].values())
    assert report["meta"]["rules_version"]==load_rules()["version"]
    assert report["suggestions"]
    assert all(s["source_modules"] for s in report["suggestions"])
    assert len({x["id"] for x in report["suggestions"]})==len(report["suggestions"])
    for s in report["suggestions"]:
        assert all(s.get(k) for k in ("id","location","original","problem","action","example","priority"))
        assert s["priority"] in {"高","中","低"}
    assert not any(any(term in (str(i["reason"]) + str(i["type"])) for term in ("造假","虚假")) for i in report["dimensions"]["verification"]["issues"])
    assert all(q["issue_id"] in {i["id"] for i in report["dimensions"]["verification"]["issues"]} for q in report["interview_questions"])


def test_disabled_dimension_does_not_cascade():
    report=run_diagnosis(candidate(),target(),enabled_sections=["match","verification"],as_of="2026-10-19")
    assert report["dimensions"]["match"]["status"]=="ok"
    assert report["dimensions"]["experience"]["status"]=="disabled"
    assert report["dimensions"]["verification"]["status"]=="ok"
    assert all(set(s["source_modules"]) <= {"match","verification"} for s in report["suggestions"])


def test_potential_claims_are_evidence_linked_or_explicit_unknown():
    sparse=candidate("empty")
    sparse.skills=["Python"]
    result=run_diagnosis(sparse,target(),as_of="2026-10-19")["dimensions"]["potential"]
    assert result["status"]=="ok"
    assert result["rating"]=="无法判断"
    assert result["supporting_signals"]==[]
    for item in result["supporting_signals"]:
        assert item.get("path") and item.get("status")
        if item["status"]=="支持":
            assert item.get("original")


def test_benchmark_ordinal_and_sensitivity_is_internally_checked_not_accuracy_claim():
    bench=evaluate_ordinal_benchmarks()
    assert bench["scenario_count"]>=12
    assert bench["pairwise_order_accuracy"]>=0.85
    assert bench["criterion_validated"] is False
    assert bench["score_span"]>=30
    result=weight_sensitivity(candidate(),target(),trials=40,seed=9)
    assert result["trials"]==40
    assert result["maximum_score"]<=100
    assert result["minimum_score"]>=0
    assert result["spread"]<25


def test_time_score_does_not_depend_on_demographics():
    x=candidate();y=x.model_copy(deep=True)
    x.additional=["男","25岁"];y.additional=["女","45岁"]
    assert score_match(x,target())["score"]==score_match(y,target())["score"]
