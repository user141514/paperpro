"""Independent review counterexamples for earned facts and explicit JD coverage."""
import pytest

from app.diagnosis.requirements import prepare_requirements
from app.diagnosis.schema import CandidateResume, CareerEntry, Target
from app.diagnosis.scoring import score_match
from app.models import Education


def criterion(factor, description):
    return {"id":"review", "factor_id":factor,"label":"真实条件核对", "description":description,
            "weight":100,"enabled":True,"hard_gate":True,"source":"user_jd"}


def test_minimum_degree_is_not_raised_by_a_preferred_degree():
    resume=CandidateResume(education=[Education(heading="示例大学｜本科，已毕业")])
    result=score_match(resume,Target(role="后端工程师"),requirements=[criterion("education","本科及以上学历，硕士优先")])
    assert result["score"]==100
    assert result["requirements"][0]["status"]=="已体现"


@pytest.mark.parametrize("heading",["示例大学｜硕士在读，预计2028年毕业", "示例大学｜正在攻读硕士", "示例大学｜硕士（肄业）"])
def test_degree_in_progress_is_not_a_completed_degree(heading):
    result=score_match(CandidateResume(education=[Education(heading=heading)]),Target(role="后端工程师"),
                       requirements=[criterion("education","必须已取得硕士学历")])
    assert result["score"]==0
    assert result["requirements"][0]["status"]!="已体现"
    assert result["requirements"][0]["evidence_refs"]


@pytest.mark.parametrize("text",["PMP备考中（尚未参加考试）","PMP课程培训已完成，尚未取得认证","计划报考 PMP"])
def test_exam_preparation_is_not_an_earned_certificate(text):
    result=score_match(CandidateResume(certificates=[text]),Target(role="后端工程师"),
                       requirements=[criterion("certificates","必须持有PMP认证")])
    assert result["score"]==0
    assert result["requirements"][0]["status"]!="已体现"


def skilled_resume():
    return CandidateResume(skills=["Python"], certificates=["PMP（已取得）"], experience=[
        CareerEntry(bullets=["在项目中使用Python开发接口。"]),
    ])


def test_common_comma_requirements_do_not_mix_certificate_and_skill_tokens():
    target=Target(role="后端工程师",job_description="必须掌握 Python，必须持有 PMP 认证。")
    prepared=prepare_requirements(target)
    result=score_match(skilled_resume(),target,requirements=prepared["requirements"])
    assert result["score"]==100
    cert=next(item for item in result["requirements"] if item["factor_id"]=="certificates")
    assert cert["status"]=="已体现"
    assert "Python" not in cert["description"]


def test_explicit_unlisted_english_skill_is_retained_as_a_requirement():
    target=Target(role="后端工程师",job_description="必须掌握 Python 和 Rust。")
    prepared=prepare_requirements(target)
    assert any("Rust" in item["description"] for item in prepared["requirements"])
    result=score_match(skilled_resume(),target,requirements=prepared["requirements"])
    assert result["score"]<100
    assert any("Rust" in item["description"] and item["status"]=="简历未体现" for item in result["requirements"])


def test_combined_jd_keeps_minimum_preference_and_all_explicit_conditions():
    target=Target(role="后端工程师",job_description="必须掌握 Python 和 Rust，必须持有 PMP 认证，本科及以上学历，硕士优先")
    prepared=prepare_requirements(target)
    education=[item for item in prepared["requirements"] if item["factor_id"]=="education"]
    assert len(education)==1
    assert "硕士优先" in education[0]["description"]
    resume=skilled_resume()
    resume.skills.append("Rust")
    resume.experience[0].bullets.append("在真实项目中使用 Rust 开发服务。")
    resume.education=[Education(heading="示例大学｜本科，已毕业")]
    result=score_match(resume,target,requirements=prepared["requirements"])
    assert result["score"]==100
