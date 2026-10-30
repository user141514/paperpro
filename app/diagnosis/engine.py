"""Five independent candidate-facing diagnostic products + selected-only advice.

No hiring decision, deception accusation, or unsupported employment claims.
Computed dates and weights remain authoritative; prose can only explain them.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
import re

from .schema import CandidateResume, Target
from .schema import validate_requirements
from .quality import validate_resume_for_diagnosis
from .claim_conflicts import detect_description_conflicts
from .scoring import (
    _contains, _find, _refs, _profile, calculate_timeline, load_rules,
    score_match, weight_sensitivity, evaluate_ordinal_benchmarks, rules_prompt,
)


def _experience(resume: CandidateResume, target: Target, as_of: str) -> dict:
    result = calculate_timeline(resume, as_of=as_of)
    known = [
        (i, e) for i, e in enumerate(resume.experience)
        if e.company or e.role or e.heading
    ]
    # Employment history is often displayed newest first. Only a dated
    # chronological sequence can support a progression judgement.
    dated_indices=[int(n["path"].split(".")[1]) for n in result["timeline"]]
    titles = [(i, resume.experience[i].role) for i in dated_indices
              if resume.experience[i].role]
    level_terms = [
        ("实习", 1), ("助理", 1), ("专员", 2), ("工程师", 2), ("高级", 3),
        ("资深", 3), ("主管", 4), ("经理", 4), ("总监", 5), ("负责人", 5),
    ]
    stages = []
    for i, value in titles:
        matches = [level for term, level in level_terms if term in value]
        if matches:
            stages.append({"path":f"experience.{i}.role","original":value,"level":max(matches)})
    # Compare all observed job families, not whether a single keyword
    # appears anywhere. Unknown/ambiguous roles cannot prove continuity.
    rules=load_rules()
    families=[_profile(title,rules)[0] for _,title in titles]
    same_function=(
        len(families)>=2 and
        all(family==families[0] and family!="general" for family in families)
    )
    if len(stages)>=2 and stages[-1]["level"]>stages[0]["level"]:
        direction="可见较高职级称谓，但仍需核实职责及是否为真实晋升"
    elif len(stages)>=2 and stages[-1]["level"]<stages[0]["level"]:
        direction="职位称谓变化需要结合职责解释，不能据此推断退步"
    else:
        direction="未见明确的职级上升证据，不能仅凭职位称谓推断晋升"
    result.update({
        "career_continuity":(
            "存在相近岗位职能表述" if same_function else
            "当前记录不足以确认职业方向连贯程度"
        ),
        "career_progression": direction,
        "career_level_evidence": stages,
        "conclusion": (
            f"已登记 {len(resume.experience)} 段工作/实习经历；"
            "稳定性指标只依据明确年月计算。"
        ),
        "interpretation_boundary": "跨行业和岗位类型的变化并非缺陷；空窗与重叠可能来自求学、兼职或标注方式，须候选人确认。",
    })
    return result


def _potential(resume: CandidateResume, target: Target, as_of: str) -> dict:
    refs = _refs(resume)
    rules = load_rules()
    signals = []
    def positive_record(ref):
        return not re.search(
            r"未取得|未获得|尚未|没有|暂未|未通过|未完成|"
            r"not certified|not obtained|no credential",
            ref["original"],re.I,
        )
    work_refs=[r for r in refs if r["path"].startswith(("experience.","projects."))]
    checks = [
        ("学历", [r for r in refs if r["path"].startswith("education.") and positive_record(r)]),
        ("证书", [r for r in refs if r["path"].startswith("certificates.") and positive_record(r)]),
        # A skill list does not prove learning *speed*. Require a described
        # training, migration, promotion, or acquisition event instead.
        ("技能更新", _find(work_refs, rules["evidence_terms"]["skill_update"],positive=True)),
        ("职责扩张", _find(work_refs, rules["evidence_terms"]["responsibility_growth"],positive=True)),
        ("成果层级", _find(work_refs, rules["evidence_terms"]["metric"]+
                            rules["evidence_terms"]["leadership"],positive=True)),
    ]
    for name, support in checks:
        ref = support[0] if support else None
        signals.append({
            "signal":name,
            "status":"支持" if ref else "未体现",
            "path":ref["path"] if ref else name+"（未填写）",
            "original":ref["original"] if ref else "",
            "explanation":("仅说明简历存在对应文字证据，仍需人工确认真实性"
                           if ref else "简历未显示这一信号，不代表候选人不具备该能力"),
        })
    num=sum(item["status"]=="支持" for item in signals)
    rating="高" if num>=4 else "中" if num>=3 else "无法判断"
    supporting=[item for item in signals if item["status"]=="支持"][:3]
    needed=next((i for i in signals if i["status"]!="支持"),None)
    return {
        "status":"ok",
        "rating":rating,
        "evidence_count":num,
        "supporting_signals":supporting,
        "signals":signals,
        "weakness":{
            "signal":needed["signal"],
            "action":"请补充该信号的可核实经历、证书或项目材料，不要推测或编造。"
        } if needed else {
            "signal":"成果的来源与可信度",
            "action":"选择最重要的两项成果，补充可核实的职责和计算口径。"
        },
        "conclusion":f"五个明确可见证据信号中有 {num} 项；" + ("证据不足，暂时无法判断。" if num<3 else "该评级表示简历证据充足度，不是心理能力测验。"),
        "limitations":(["可观察的学习与发展信号不足三类，不能形成可靠评级。"] if num<3 else []),
        "caveat":"真实学习速度、能力潜力无法仅凭简历确定；评级不可用于人格或智力判断。",
    }


def _motivation(resume: CandidateResume, target: Target, as_of: str) -> dict:
    refs=_refs(resume)
    company_refs=_find(refs,[target.company]) if target.company.strip() else []
    role_refs=_find(refs,[target.role]) if target.role.strip() else []
    jd=target.job_description.strip()
    rules=load_rules()
    sectors=[k for k in rules["factors"][0]["keywords"] if _contains(jd,k)]
    jd_refs=_find(refs,sectors)
    count=int(bool(company_refs))+int(bool(role_refs))+int(bool(jd_refs))
    rating="高" if count>=3 else "中" if count>=1 else "低"
    evidence=(company_refs+role_refs+jd_refs)[:4]
    details=(
        "未提供目标公司，不对公司了解程度作推断，仅核对岗位表达。"
        if not target.company.strip() else
        "当前证据只来源于简历原文，不代表核验过该公司的真实需求。"
    )
    return {
        "status":"ok","rating":rating,
        "evidence":evidence,
        "rationale":f"检测到 {count} 类定制表达证据（目标公司、岗位、JD 关键词）。{details}",
        "suggestion":(
            "在自我评价或项目描述中，按真实经历指出与目标岗位匹配的技能、产出及兴趣。"
            "不要添加没有参与过的企业项目或虚构公司了解。"
        ),
        "conclusion":f"岗位针对性表述证据：{rating}。没有出现公司名称不能证明求职者不重视。",
    }


def _verification(resume: CandidateResume, target: Target, as_of: str) -> dict:
    rules=load_rules()
    timeline=calculate_timeline(resume,as_of=as_of)
    issues=list(timeline["issues"])
    dated_paths={node["path"] for node in timeline["timeline"]}
    for i,item in enumerate(resume.experience):
        path=f"experience.{i}.heading"
        if path not in dated_paths:
            reason=("工作日期有缺失，无法计算实际任期和空档。"
                    if not item.start_date or not item.end_date else
                    "起止年月格式或先后顺序异常，请核对真实任期；没有据此推测实际行为。")
            issues.append({
                "id":f"undated-{i}", "type":"工作任期需要核对",
                "location":path,
                "original":item.heading or (item.company+" "+item.role).strip() or "（没有记录）",
                "reason":reason,
                "severity":"中",
            })
    issues.extend(detect_description_conflicts(resume))
    for ref in _refs(resume):
        text=ref["original"]
        # Warn only about numeric achievements with context, not years, phone or education dates.
        if ("bullets." in ref["path"] or ref["path"] in {"summary","self_evaluation"}) and re.search(
                r"\d+(?:\.\d+)?\s*(?:%|％|倍)",text):
            if not any(marker in text for marker in ("从","到","基线","对照","口径","前","后","记录","监测")):
                issues.append({
                    "id":"metric-"+ref["path"].replace(".","-"),
                    "type":"成果计算口径可追问",
                    "location":ref["path"],"original":text,
                    "reason":"成果包含量化数字，但未说明基线、测量时段或统计方式；可补充可核实的计算口径。",
                    "severity":"中",
                })
    questions=[]
    for issue in issues:
        if issue["severity"] in {"高","中"}:
            questions.append({
                "id":"question-"+issue["id"],"issue_id":issue["id"],
                "check":issue["type"],
                "question":(f"简历中关于 {issue['subject']} 的两处说法不一致：请核实是否为同一时期、"
                            "同一主体与同一事实，并说明哪一处需要修改？"
                            if issue.get("conflict_kind")=="explicit_skill_polarity" else
                            "请结合这段经历说明具体起止时间、你的实际职责，以及可核实的证据是什么？"
                            if "时间" in issue["type"] or "任期" in issue["type"]
                            else "这项成果的计算方式、数据基线及你个人负责的部分分别是什么？"),
                "purpose":"确认简历描述的上下文与可追溯事实，不预设不诚信。",
            })
    return {
        "status":"ok","issues":issues,"questions":questions,
        "conclusion":f"检测到 {len(issues)} 项可能引起面试官追问的表述或时间问题。",
        "caveat":"自动检查无法判断真实情况；每项仅供本人核对，不构成对个人品行的评价。",
    }


def _advice(resume: CandidateResume, target: Target, dimensions: dict) -> list[dict]:
    sources=_refs(resume)
    def first(paths: list[str]):
        for p in paths:
            if p in {"experience","projects","education"}:
                found=next((x for x in sources if x["path"].startswith(p+".")),None)
            else:
                found=next((x for x in sources if x["path"]==p),None)
            if found:
                return found
        return {"path":paths[0],"original":"（该字段未填写）"}
    match=dimensions.get("match",{})
    missing_hard=[r for r in match.get("requirements",[]) if r["status"] in {"简历未体现","明确不满足"}
                  and r.get("factor_id", r["id"]) in {"skills","function","experience"}]
    weak_ids={r.get("factor_id",r["id"]) for r in missing_hard}
    hard_ids={r.get("factor_id",r["id"]) for r in missing_hard if r.get("hard_gate",True)}
    matched={}
    for item in match.get("requirements",[]):
        factor=item.get("factor_id",item["id"])
        if factor not in matched or item["coefficient"] < matched[factor]["coefficient"]:
            matched[factor]=item
    verification_issues=dimensions.get("verification",{}).get("issues",[])
    metric_issues=[issue for issue in verification_issues if issue.get("type")=="成果计算口径可追问"]
    timeline_issues=[issue for issue in verification_issues
                     if issue.get("id","").startswith(("timeline-","undated-"))]
    has_work_details=any(
        len(text.strip()) >= 10 for entry in resume.experience for text in entry.bullets
    )
    templates=[
        ("岗位定位不明确","title","现有职位表述与目标岗位之间缺少直接连接。",
         "在求职方向写明实际匹配的岗位方向。",
         "求职方向：[真实具备经验的目标职位]", "高" if "function" in hard_ids else "中"),
        ("关键技能证据不足","skills","目标岗位技能的书面证据不够完整。",
         "仅补充真实掌握的技能，并在实际项目中对应到使用场景。",
         "技能：[已掌握的技术]；项目中实际使用方式：[对应任务]", "高" if "skills" in hard_ids else "中"),
        ("个人概述缺乏针对性","summary","简介未明确说明与目标岗位最相关的经历。",
         "保留真实职责，按工作领域→核心技能→可验证事项组织。",
         "曾在[真实业务领域]参与[真实职责]，主要使用[已掌握技能]。", "中"),
        ("工作职责需要更具体","experience","岗位经历中的行为边界或交付责任可能不够清晰。",
         "写明本人负责哪一步、和谁协作、交付了什么。",
         "负责[真实任务]的[本人具体部分]，交付[有证据支持的成果]。", "高" if "experience" in hard_ids else "中"),
        ("项目经历与岗位关联偏弱","projects","项目描述可能未显式证明目标岗位要求。",
         "每个项目选择一项与目标岗位直接相关的实际技能、问题和结果。",
         "项目[真实名称]：使用[真实工具]解决[真实问题]。", "中"),
        ("成果量化依据不完整","experience","成果描述如果没有统计口径，容易引出核查问题。",
         "补充能证明的基线、周期、个人职责；没有数字就写可验证的交付内容。",
         "在[已核实周期]通过[实际措施]，使[可核实指标]从[基线]变化至[结果]。", "中"),
        ("时间信息需要核对","experience","任期和空档可能尚未注明准确年月。",
         "核实每段经历真实开始/结束月份，必要时解释重叠与空档。",
         "[实际开始年月]—[实际结束年月] [实际单位]｜[真实职务]", "中"),
        ("成长证据呈现不足","certificates","证书、培训或新技能的证明材料可能未充分体现。",
         "仅列已经取得的证书、完成的培训或有交付的学习成果。",
         "证书：[真实证书名称/日期]；学习成果：[可核实项目]。", "低"),
        ("求职动机表达过于泛化","self_evaluation","简历可能没有说明为什么与目标岗位相关。",
         "结合真实经历说明岗位兴趣，企业信息只能来自用户提供的JD。",
         "希望在[目标岗位真实工作内容]中应用已有的[具体经验]。", "中"),
    ]
    advice=[]
    for i,(title,group,problem,action,example,priority) in enumerate(templates,1):
        source_modules = {
            1:["match"] if "function" in weak_ids else [],
            2:["match"] if "skills" in weak_ids else [],
            3:["motivation"] if dimensions.get("motivation",{}).get("rating") in {"低","中"} and bool(resume.summary.strip()) else [],
            4:["match"] if "experience" in weak_ids else [],
            5:["match"] if matched.get("projects",{}).get("status") == "简历未体现" else [],
            6:["verification"] if metric_issues else [],
            7:["verification"] if timeline_issues else [],
            8:["potential"] if dimensions.get("potential",{}).get("evidence_count",0) < 3 and dimensions.get("potential",{}).get("status") == "ok" else [],
            9:["motivation"] if dimensions.get("motivation",{}).get("rating") == "低" and not resume.summary.strip() else [],
        }[i]
        source_modules = [key for key in source_modules if dimensions.get(key,{}).get("status") == "ok"]
        if not source_modules:
            continue
        assessment="需要修正"
        ref=first([group,"summary"] if group != "skills" else ["skills.0","summary"])
        if i==1 and resume.title.strip() and "function" not in weak_ids:
            assessment="可选深化";priority="低"
            problem="已经填写当前职位或求职方向；可进一步核对与目标岗位的实际关联，避免空泛的定位。"
        elif i==2:
            skill=matched.get("skills")
            if skill and skill["coefficient"]>=0.75:
                assessment="可选深化";priority="低"
                problem="已展示较多岗位相关技能证据；可选择最重要的一项补充实际应用方式。"
            elif skill and skill["coefficient"]>0:
                priority="中"
                problem="部分目标技能有书面证据，另一些仍需按真实使用经历补充。"
        elif i==3 and len(resume.summary.strip())>=30:
            assessment="可选深化";priority="低"
            problem="已有较完整的个人概述；可选择最切合目标岗位的真实经历置于开头。"
        elif i==4:
            if has_work_details and "experience" not in weak_ids:
                assessment="可选深化";priority="低"
                problem="已填写具体工作职责；可按目标岗位需要提高重点交付物的可核查性。"
            elif not has_work_details:
                priority="高" if "experience" in hard_ids else "中"
                problem="简历中尚未展示可核对的工作或实习职责；可能影响岗位经验的初步判读。"
        elif i==5:
            project=matched.get("projects")
            if project and project["coefficient"]>=0.5:
                assessment="可选深化";priority="低"
                problem="已有与岗位部分相关的项目证据，可进一步说明个人责任边界及交付方式。"
        elif i==6:
            if metric_issues:
                issue=metric_issues[0]
                ref={"path":issue["location"],"original":issue["original"]}
                problem=issue["reason"]
            else:
                assessment="可选深化";priority="低"
                problem="当前没有触发成果统计口径存疑规则；可选补充更多能够证明的交付证据。"
        elif i==7:
            if timeline_issues:
                issue=timeline_issues[0]
                ref={"path":issue["location"],"original":issue["original"]}
                problem=issue["reason"]
            else:
                assessment="可选深化";priority="低"
                problem="已提供的工作起止年月未触发时间冲突或明显空档提示；导出前可再次核对。"
        elif i==8:
            title="学习与发展证据待补充"
            problem="当前可观察的学习与发展信号不足，暂时无法判断；不表示缺少学习能力。"
            action="补充真实完成的学习、职责扩展或成果材料；没有相应材料时保持待验证。"
        elif i==9 and dimensions.get("motivation",{}).get("rating")=="高":
            assessment="可选深化";priority="低"
            problem="已出现目标岗位的针对性表达；可进一步核实与岗位描述的具体联系。"
        advice.append({
            "id":f"advice-{i:02d}","title":title,
            "assessment":assessment,
            "priority":priority,"location":ref["path"],"original":ref["original"],
            "problem":problem,"action":action,"example":example,
            "target":(target.role or target.company),
            "source_modules":source_modules,
        })
    # Only concrete two-source contradictions receive a targeted correction
    # item. No missing skill or unverified inference is called a contradiction.
    for issue in verification_issues:
        if issue.get("conflict_kind")!="explicit_skill_polarity":
            continue
        advice.append({
            "id":"advice-"+issue["id"],"issue_id":issue["id"],
            "conflict_kind":issue["conflict_kind"],
            "title":f"核对两处矛盾描述：{issue['subject']}",
            "assessment":"需要修正","priority":"高",
            "location":issue["location"],"original":issue["original"],
            "related_location":issue["related_location"],
            "related_original":issue["related_original"],
            "problem":issue["reason"],
            "action":"逐条核对两处原文与真实能力、时期及本人负责内容；修正不准确的一处，不能照搬岗位JD补写经历。",
            "example":"[核实后，保留能够提供依据的一致描述]",
            "target":(target.role or target.company),
            "source_modules":["verification"],
        })
    # High-priority suggestions must be linked to a real gap or two sources.
    return sorted(advice,key=lambda x:({"高":0,"中":1,"低":2}[x["priority"]],x["id"]))


RUNNERS={
    "match":lambda resume,target,as_of,requirements=None:score_match(resume,target,as_of=as_of,requirements=requirements),
    "experience":_experience,
    "potential":_potential,
    "motivation":_motivation,
    "verification":_verification,
}


def _validate_section(name, result, resume):
    required={"match":("requirements","score"), "experience":("timeline","months_total"),
              "potential":("signals","supporting_signals","rating"),
              "motivation":("rating","evidence"), "verification":("issues","questions")}
    if not isinstance(result,dict) or result.get("status") != "ok" or any(key not in result for key in required[name]):
        raise ValueError("模块没有形成结构完整的有效结果")
    list_keys={"match":["requirements"],"experience":["timeline"],"potential":["signals","supporting_signals"],
               "motivation":["evidence"],"verification":["issues","questions"]}
    if any(not isinstance(result[key],list) for key in list_keys[name]):
        raise ValueError("模块证据结构无效")
    evidence=[]
    if name=="match":
        if not result["requirements"] or result["score"] is not None and not 0 <= result["score"] <= 100:
            raise ValueError("评分模块没有有效要求或分数")
        for row in result["requirements"]:
            coefficient=row.get("coefficient")
            if not isinstance(coefficient,(int,float)) or not math.isfinite(coefficient) or not 0 <= coefficient <= 1:
                raise ValueError("匹配系数无效")
            if not all(key in row for key in ("id","status","evidence_refs")) or not isinstance(row["evidence_refs"],list):
                raise ValueError("评分项证据结构无效")
            evidence.extend(row["evidence_refs"])
    elif name=="potential":
        evidence=result["supporting_signals"]
        if any(item.get("status")!="支持" for item in evidence):
            raise ValueError("未体现项不能作为支撑证据")
    elif name=="motivation":
        evidence=result["evidence"]
    actual={(item["path"],item["original"]) for item in _refs(resume)}
    if any(not isinstance(item,dict) or (item.get("path"),item.get("original")) not in actual for item in evidence):
        raise ValueError("诊断证据没有指向当前简历的真实字段")


def run_diagnosis(
    resume: CandidateResume, target: Target, *,
    enabled_sections: list[str] | None = None, as_of: str | None = None,
    requirements=None, on_section=None, should_cancel=None,
) -> dict:
    today=as_of or date.today().isoformat()
    date.fromisoformat(today)
    validate_resume_for_diagnosis(resume)
    requirements=validate_requirements(requirements)
    selected=set(RUNNERS) if enabled_sections is None else set(enabled_sections)
    if not selected or selected-set(RUNNERS):
        raise ValueError("请至少开启一个有效诊断模块")
    sections={}
    for key,runner in RUNNERS.items():
        if key not in selected:
            sections[key]={"status":"disabled","conclusion":"已按用户选择关闭该维度"}
        elif should_cancel and should_cancel():
            sections[key]={"status":"cancelled","conclusion":"已取消，未继续执行此模块"}
        else:
            try:
                result=(runner(resume,target,today,requirements) if key=="match" else runner(resume,target,today))
                _validate_section(key,result,resume)
                result.setdefault("summary",result.get("conclusion",result.get("summary","已完成证据核对")))
                result.setdefault("limitations",[result["caveat"]] if result.get("caveat") else [])
                result.setdefault("version_info",{"rules_version":load_rules()["version"],"as_of":today})
                sections[key]=result
            except Exception:
                sections[key]={"status":"error","conclusion":"此维度未能生成有效证据结果，请检查输入后重试"}
        if on_section:
            on_section(key,sections[key])
    return rebuild_report(resume,target,sections,today,requirements)


def rebuild_report(resume: CandidateResume, target: Target, sections: dict, as_of: str, requirements=None) -> dict:
    """Project the accepted frozen module versions without rerunning siblings."""
    date.fromisoformat(as_of)
    requirements=validate_requirements(requirements)
    rules=load_rules()
    dimensions={key:sections.get(key,{"status":"pending","conclusion":"等待生成"}) for key in RUNNERS}
    completed=[key for key,item in dimensions.items() if item.get("status")=="ok"]
    failed=[key for key,item in dimensions.items() if item.get("status")=="error"]
    disabled=[key for key,item in dimensions.items() if item.get("status")=="disabled"]
    cancelled=[key for key,item in dimensions.items() if item.get("status")=="cancelled"]
    pending=[key for key in dimensions if key not in completed+failed+disabled+cancelled]
    active=[key for key in dimensions if key not in disabled]
    report_status=("complete" if completed and len(completed)==len(active) else
                   "partial" if completed or pending else "cancelled" if cancelled and not failed else "failed")
    scope={"status":report_status,"enabled":active,"completed":completed,"failed":failed,
           "disabled":disabled,"cancelled":cancelled,"pending":pending,
           "can_generate_suggestions":bool(completed)}
    valid={key:item for key,item in dimensions.items() if key in completed}
    verification=valid.get("verification",{})
    questions=verification.get("questions",[])
    suggestions=_advice(resume,target,valid) if completed else []
    uncovered=[key for key in dimensions if key not in completed]
    for item in suggestions:
        item["uncovered_modules"]=uncovered
        item["report_scope"]=report_status
    source=resume.model_dump(exclude={"source_text"})
    snapshot={"resume":source,"target":target.model_dump(),"as_of":as_of,
              "requirements":[item.model_dump() for item in requirements] if requirements is not None else None,
              "enabled_sections":active,"rules_version":rules["version"]}
    return {
        "meta":{
            "version":"paperpro-diagnosis-v1",
            "rules_version":rules["version"],
            "rules_status":rules["status"],
            "generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "as_of":as_of,
            "source_sha256":resume.source_sha256,
            "reviewed_draft_sha256":sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            "input_snapshot_sha256":sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            "score_is_hiring_probability":False,
            "disclaimer":"输出供候选人自查，不是实际企业录用概率；缺少真实 HR 标注数据，预测效度未验证。",
        },
        "target":target.model_dump(),
        "dimensions":dimensions,
        "report_status":report_status,
        "scope":scope,
        "can_generate_suggestions":bool(completed),
        "requirements":[item.model_dump() for item in requirements] if requirements is not None else None,
        "suggestions":suggestions,
        "interview_questions":questions,
    }
