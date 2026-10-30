"""Synthetic dependency matrix checked against the actual deterministic runners."""
from copy import deepcopy
from importlib import import_module

import pytest

from app.diagnosis.engine import RUNNERS
from app.diagnosis.schema import CandidateResume, Target


MODULES=set(RUNNERS)


def dependencies():
    return import_module("app.diagnosis.dependencies")


def inputs():
    return {
        "document_version_id":"synthetic-document-1", "as_of":"2026-10-30",
        "enabled_sections":list(RUNNERS),
        "resume":{
            "name":"合成候选人", "title":"后端工程师", "summary":"我精通 Python，完成性能优化。",
            "self_evaluation":"希望使用已有 Python 项目经验。", "skills":["Python","SQL"],
            "experience":[{"company":"合成公司", "role":"后端工程师", "heading":"合成公司｜后端工程师",
                           "start_date":"2023.01", "end_date":"至今", "bullets":["学习 Python 后独立负责接口，性能提升20%。"]}],
            "projects":[{"heading":"合成服务项目", "bullets":["使用 Python 开发接口。"]}],
            "education":[{"heading":"示例大学｜本科，已毕业", "details":["计算机专业"]}],
            "certificates":["PMP（已取得）"], "additional":["合成附注"],
        },
        "target":{"role":"后端工程师", "company":"合成公司", "job_description":"掌握 Python SQL，有相关经验。"},
        "requirements":[{"id":factor,"factor_id":factor,"label":factor,"description":description,
                         "weight":weight,"enabled":True,"hard_gate":False,"source":"user_jd"}
                        for factor,description,weight in [
                            ("skills","Python SQL",20),("function","后端工程师",10),
                            ("experience","2年相关工作经验",20),("projects","Python 项目",10),
                            ("education","本科及以上",10),("industry","互联网",10),
                            ("leadership","团队管理",10),("certificates","PMP认证",10),
                        ]],
    }


def set_path(state,path,value):
    current=state
    parts=path.split(".")
    for part in parts[:-1]:
        current=current[int(part)] if isinstance(current,list) else current[part]
    if isinstance(current,list):
        current[int(parts[-1])]=value
    else:
        current[parts[-1]]=value


def changed_modules(before,after):
    old=dependencies().module_fingerprints(before)
    new=dependencies().module_fingerprints(after)
    return {name for name in RUNNERS if old[name]!=new[name]}


def actual_outputs(state):
    resume=CandidateResume.model_validate(state["resume"])
    target=Target.model_validate(state["target"])
    return {name:(runner(resume,target,state["as_of"],state.get("requirements")) if name=="match" else
                  runner(resume,target,state["as_of"])) for name,runner in RUNNERS.items()}


@pytest.mark.parametrize("path,value,expected",[
    ("resume.name","另一合成人",set()),
    ("resume.phone","10000000000",set()),
    ("resume.email","synthetic@example.invalid",set()),
    ("resume.location","合成地区",set()),
    ("resume.additional",["不同附注"],set()),
    ("resume.title","数据工程师",{"match","motivation"}),
    ("resume.summary","我不会 Python。",{"match","motivation","verification"}),
    ("resume.self_evaluation","性能提升80%。",{"match","motivation","verification"}),
    ("resume.skills",["Python","Rust"],{"match","motivation","verification"}),
    ("resume.experience.0.company","学习与培训有限公司",MODULES),
    ("resume.experience.0.role","工程总监",MODULES),
    ("resume.experience.0.heading","另一公司｜工程师",MODULES),
    ("resume.experience.0.bullets",["从未使用 Python。"],{"match","potential","motivation","verification"}),
    ("resume.experience.0.start_date","2024.02",{"match","experience","verification"}),
    ("resume.experience.0.end_date","2024.12",{"match","experience","verification"}),
    ("resume.projects.0.heading","学习迁移项目",{"match","potential","motivation"}),
    ("resume.projects.0.bullets",["性能提升90%。"],{"match","potential","motivation","verification"}),
    ("resume.education.0.heading","示例大学｜硕士在读",{"match","potential","motivation"}),
    ("resume.education.0.details",["另一个专业"],{"match","potential","motivation"}),
    ("resume.certificates",["PMP备考中"],{"match","potential","motivation"}),
    ("target.role","数据工程师",{"match","motivation"}),
    ("target.company","另一合成公司",{"motivation"}),
    ("target.job_description","必须使用 Rust。",{"motivation"}),
    ("requirements.0.label","已确认技能标签",{"match"}),
    ("as_of","2027-10-30",{"match","experience","verification"}),
])
def test_field_matrix_is_minimal_and_covers_real_runner_changes(path,value,expected):
    before=inputs()
    after=deepcopy(before)
    set_path(after,path,value)
    projected=changed_modules(before,after)
    assert projected==expected
    old_results,new_results=actual_outputs(before),actual_outputs(after)
    real_changes={name for name in RUNNERS if old_results[name]!=new_results[name]}
    assert real_changes<=projected, (path,real_changes-projected)


@pytest.mark.parametrize("factor,field,value,changed",[
    ("skills","as_of","2027-10-30",{"experience","verification"}),
    ("skills","resume.experience.0.start_date","2024.01",{"experience","verification"}),
    ("education","resume.skills",["Rust"],{"motivation","verification"}),
    ("certificates","resume.education.0.heading","硕士已毕业",{"potential","motivation"}),
    ("experience","resume.experience.0.company","另一公司",{"experience","potential","motivation","verification"}),
    ("projects","resume.skills",["Rust"],{"motivation","verification"}),
])
def test_confirmed_factor_union_avoids_unrelated_match_recalculation(factor,field,value,changed):
    before=inputs()
    before["requirements"]=[next(item for item in before["requirements"] if item["factor_id"]==factor)]
    before["requirements"][0]["weight"]=100
    after=deepcopy(before)
    set_path(after,field,value)
    assert changed_modules(before,after)==changed
    old,new=actual_outputs(before),actual_outputs(after)
    assert {name for name in RUNNERS if old[name]!=new[name]}<=changed


def test_unconfirmed_match_uses_jd_but_still_not_target_company():
    before=inputs()
    before["requirements"]=None
    after=deepcopy(before)
    after["target"]["job_description"]="必须使用 Rust。"
    assert changed_modules(before,after)=={"match","motivation"}


def test_disabled_requirements_still_affect_displayed_match_rows():
    before=inputs()
    before["requirements"][0]["enabled"]=False
    before["requirements"][1]["weight"]+=20
    after=deepcopy(before)
    after["resume"]["summary"]="我不会 Python。"
    assert "match" in changed_modules(before,after)
    assert actual_outputs(before)["match"]!=actual_outputs(after)["match"]


@pytest.mark.parametrize("kind",["title","project_heading"])
def test_verification_keeps_exact_first_350_refs_before_scope_filter(kind):
    before=inputs()
    if kind=="title":
        before["resume"]={"title":"有标题", "summary":"我精通 Python", "skills":["无关技能"]*348+["我不会 Python"]}
    else:
        before["resume"]={"skills":["无关技能"]*348, "projects":[{"heading":"有项目标题","bullets":["我使用过 Python。","我从未使用 Python。"]}]}
    after=deepcopy(before)
    if kind=="title":
        after["resume"]["title"]=""
    else:
        after["resume"]["projects"][0]["heading"]=""
    assert actual_outputs(before)["verification"]!=actual_outputs(after)["verification"]
    assert "verification" in changed_modules(before,after)


def test_rule_content_and_document_identity_are_part_of_every_fingerprint(monkeypatch):
    deps=dependencies()
    before=inputs()
    old=deps.module_fingerprints(before)
    another=deepcopy(before)
    another["document_version_id"]="synthetic-document-2"
    assert changed_modules(before,another)==MODULES
    rules=deepcopy(deps.load_rules())
    rules["date_policy"]["gap_notice_days"]+=1  # Same visible version, changed real rules.
    monkeypatch.setattr(deps,"load_rules",lambda:rules)
    assert all(old[name]!=deps.module_fingerprints(before)[name] for name in RUNNERS)


def test_plan_reuses_only_success_and_never_recreates_missing_old_fingerprints():
    deps=dependencies()
    state=inputs()
    snapshot={**deepcopy(state),"module_fingerprints":deps.module_fingerprints(state)}
    dimensions={name:{"status":"ok"} for name in RUNNERS}
    assert deps.recompute_plan(snapshot,state,dimensions)["recomputed"]==[]
    dimensions["potential"]={"status":"error"}
    assert deps.recompute_plan(snapshot,state,dimensions)["recomputed"]==["potential"]
    after=deepcopy(state)
    after["enabled_sections"]=["match","experience"]
    plan=deps.recompute_plan(snapshot,after,dimensions)
    assert plan["recomputed"]==[]
    assert plan["reused"]==["match","experience"]
    assert plan["disabled"]==["potential","motivation","verification"]
    legacy={key:value for key,value in snapshot.items() if key!="module_fingerprints"}
    assert set(deps.recompute_plan(legacy,state,dimensions)["recomputed"])==MODULES


def test_changed_field_paths_exclude_raw_source_and_support_legacy_missing_state():
    deps=dependencies()
    before=inputs()
    after=deepcopy(before)
    after["resume"].update(phone="10000000000",source_text="synthetic private source",source_sha256="f"*64)
    after["resume"]["experience"][0]["start_date"]="2024.01"
    after["step"]=4
    assert deps.changed_fields(before,after)==["resume.experience.0.start_date","resume.phone"]
    assert set(deps.module_fingerprints({}))==MODULES
    assert set(deps.recompute_plan({}, {}, {})["recomputed"])==MODULES


def test_unknown_requirement_factor_falls_back_conservatively():
    before=inputs()
    before["requirements"][0]["factor_id"]="future_factor"
    after=deepcopy(before)
    after["resume"]["phone"]="10000000000"
    assert "match" in changed_modules(before,after)
