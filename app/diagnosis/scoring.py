"""Deterministic, auditable multi-criteria job-fit scoring.

Job analysis and content validity are NOT the same as prediction accuracy.
Weights are explicit, versioned hypotheses. Missing evidence is labeled as such.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import random
import re

from .schema import CandidateResume, Target, validate_requirements

RULES_PATH = Path(__file__).with_name("rules.json")
ALL_SECTIONS = ("match", "experience", "potential", "motivation", "verification")
ENGLISH = re.compile(r"^[a-z0-9][a-z0-9.+_-]*$", re.I)
DATE = re.compile(r"^((?:19|20)\d\d)[./-](0?[1-9]|1[0-2])$")
YEAR_REQUIREMENT = re.compile(
    r"(?<!\d)([1-9]|[12]\d|30)\s*年(?=[^\d\n。；;]{0,16}(?:经验|工作|任职|从业|以上|及以上))"
    r"|(?<!\d)([1-9]|[12]\d|30)\s*years?\b", re.I
)


def load_rules() -> dict:
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    ids = [x["id"] for x in data["factors"]]
    if len(ids) < 6 or len(ids) != len(set(ids)):
        raise ValueError("岗位维度规则表无效")
    known_skills = set(data["factors"][0]["keywords"])
    for name, profile in data["profiles"].items():
        if set(profile["expected_skills"]) - known_skills:
            raise ValueError("岗位默认技能必须包含于公共技能词表：" + name)
        if set(profile["weights"]) != set(ids) or abs(sum(profile["weights"].values())-1) > 1e-7:
            raise ValueError("岗位权重必须完整且总和为 1: " + name)
        if any(v < 0 or v > 1 for v in profile["weights"].values()):
            raise ValueError("岗位权重范围必须为 0..1")
    return data


def rules_prompt() -> str:
    """The exact rule source supplied to optional AI narration; one authority."""
    rubric = load_rules()
    return (
        "不得杜撰经历、学历、入职/离职年月、职位、成果或权重；"
        "不能把没有在简历中出现的证据定性为候选人不具备；"
        "只能解读后端已计算出的时间线与评分，不能重新推断日期、修改分数；"
        "公司未提供 JD 时不能声称知道其招聘要求。"
        + "\n评分规则表(JSON)：\n"
        + json.dumps(rubric, ensure_ascii=False, sort_keys=True)
    )


def _contains(text: str, term: str) -> bool:
    if not term:
        return False
    if ENGLISH.fullmatch(term.strip()):
        return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.I))
    return term.lower() in text.lower()


def _positive_skill(ref: dict, term: str) -> bool:
    """A negated keyword is not evidence of possessing the skill."""
    text=ref["original"]
    fragments=re.split(r"[，,。;；!！?？\n]|但是|但|but",text,flags=re.I)
    negative = (
        r"未掌握|未获得|未取得|未完成|尚未|不熟悉|不会|不具备|缺乏|"
        r"没(?:有|用过|接触)|无(?:相关)?经验|"
        r"not familiar|never used|no experience|do not know|lack"
    )
    for fragment in fragments:
        if not _contains(fragment, term):
            continue
        for match in re.finditer(re.escape(term), fragment, re.I):
            before = fragment[max(0,match.start()-26):match.start()]
            after = fragment[match.end():match.end()+22]
            if re.search(negative, before, re.I):
                continue
            # "Python：不会" and "SQL（未掌握）" are explicitly negative
            # even though the negation appears after the keyword.
            if re.match(r"^\s*[:：\-\u2014（(\[]?\s*(?:" + negative + r")", after, re.I):
                continue
            return True
    return False


def _skill_strength(refs: list[dict], term: str) -> tuple[float,list[dict]]:
    positive=[ref for ref in refs if _positive_skill(ref,term)]
    if not positive:
        return 0.0, []
    applied=[ref for ref in positive if (ref["path"].startswith(("experience.","projects."))
             and ".bullets." in ref["path"])]
    listed=[ref for ref in positive if ref["path"].startswith("skills.")]
    if applied and listed:
        strength=1.0
    elif applied:
        strength=0.85
    elif listed:
        strength=0.55
    else:
        strength=0.35
    # Deduplicate the evidence; many repeated mentions are never additional skills.
    return strength,(applied+listed+positive)[:3]


def _refs(resume: CandidateResume) -> list[dict]:
    result = []
    for key in ("title", "summary", "self_evaluation"):
        value = getattr(resume, key, "")
        if value.strip():
            result.append({"path": key, "original": value})
    for i, word in enumerate(resume.skills):
        result.append({"path": f"skills.{i}", "original": word})
    for i, item in enumerate(resume.experience):
        for field in ("company", "role", "heading"):
            value = getattr(item, field, "").strip()
            if value:
                result.append({"path": f"experience.{i}.{field}", "original": value})
        for j, value in enumerate(item.bullets):
            if value.strip():
                result.append({"path": f"experience.{i}.bullets.{j}", "original": value})
    for i, item in enumerate(resume.projects):
        result.append({"path": f"projects.{i}.heading", "original": item.heading})
        for j, value in enumerate(item.bullets):
            result.append({"path": f"projects.{i}.bullets.{j}", "original": value})
    for i, item in enumerate(resume.education):
        result.append({"path": f"education.{i}.heading", "original": item.heading})
        for j, value in enumerate(item.details):
            result.append({"path": f"education.{i}.details.{j}", "original": value})
    for i, value in enumerate(resume.certificates):
        result.append({"path": f"certificates.{i}", "original": value})
    return [x for x in result if x["original"].strip()]


def _find(
    refs: list[dict], terms: list[str], limit: int = 3, *,
    positive: bool = False,
) -> list[dict]:
    predicate = _positive_skill if positive else lambda ref, term: _contains(ref["original"], term)
    matched = []
    seen_claims = set()
    for ref in refs:
        if not any(predicate(ref, term) for term in terms if term):
            continue
        # Identical copied claims are one independent piece of evidence,
        # irrespective of whether they occur in repeated projects/jobs.
        normalized = re.sub(r"\s+", " ", ref["original"]).strip().casefold()
        if normalized in seen_claims:
            continue
        seen_claims.add(normalized)
        matched.append(ref)
        if len(matched) >= limit:
            break
    return matched


def _profile(role: str, rules: dict) -> tuple[str, dict]:
    # Match the strongest *domain-specific* alias, not the first profile
    # containing a generic role suffix. Tie precedence lives in rules.json.
    lowered = role.lower()
    priority = rules["role_match_priority"]
    choices = []
    for name, profile in rules["profiles"].items():
        if name == "general":
            continue
        matched = [alias for alias in profile["aliases"] if _contains(lowered, alias)]
        if matched:
            choices.append((-priority.index(name),
                            max(len(alias) for alias in matched), name))
    if not choices:
        return "general", rules["profiles"]["general"]
    name = max(choices)[2]
    return name, rules["profiles"][name]


def _month(value: str) -> date | None:
    match = DATE.match(value.strip())
    if not match:
        return None
    return date(int(match[1]), int(match[2]), 1)


def _month_end(day: date) -> date:
    import calendar
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _months_between(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + end.month - start.month + 1)


def _valid_date_range(start: str, end: str, as_of: date) -> tuple[date, date] | None:
    first = _month(start)
    final = as_of if end.lower().strip() in {"现在", "至今", "present", "current"} else _month(end)
    if first and final:
        last = as_of if final == as_of else _month_end(final)
        if first <= last and first <= as_of:
            return first, min(last, as_of)
    return None


def _dated_experience(resume: CandidateResume, as_of: date):
    entries = []
    for idx, item in enumerate(resume.experience):
        period = _valid_date_range(item.start_date, item.end_date, as_of)
        if period:
            entries.append((period[0], period[1], idx, item))
    return sorted(entries, key=lambda x: (x[0], x[1], x[2]))


def calculate_timeline(resume: CandidateResume, *, as_of: str) -> dict:
    from datetime import timedelta
    as_of_day = date.fromisoformat(as_of)
    entries = _dated_experience(resume, as_of_day)
    dated = len(entries)
    gaps = []
    overlaps = []
    issues = []
    nodes = []
    running_end = None
    month_union: set[int] = set()
    months_recorded_sum = 0
    short = 0
    for first, last, idx, item in entries:
        months = _months_between(first, last)
        months_recorded_sum += months
        # Each calendar month contributes at most once, even when different
        # employers, internships or part-time roles overlap.
        month_union.update(range(first.year * 12 + first.month,
                                 last.year * 12 + last.month + 1))
        if months < load_rules()["date_policy"]["short_stint_months"]:
            short += 1
        path = f"experience.{idx}.heading"
        original = item.heading or (item.company + " " + item.role).strip()
        nodes.append({
            "path": path, "company": item.company, "role": item.role,
            "start": first.isoformat(), "end": last.isoformat(),
            "months": months, "original": original,
        })
        if running_end is not None:
            if first > running_end + timedelta(days=1):
                days = (first-running_end).days-1
                if days >= load_rules()["date_policy"]["gap_notice_days"]:
                    gaps.append({"days": days, "before": running_end.isoformat(),
                                 "after": first.isoformat(), "path": path})
                    issues.append({
                        "id": f"timeline-gap-{idx}", "type": "经历时间间隔待说明",
                        "location": path, "path": path, "original": original,
                        "reason": f"两段已注明的工作经历之间有 {days} 天未覆盖，建议补充实际情况。",
                        "severity": "中" if days < load_rules()["date_policy"]["gap_high_days"] else "高",
                    })
            elif first <= running_end:
                days = (min(last, running_end)-first).days+1
                if days > 0:
                    overlaps.append({"days":days,"path":path})
                    issues.append({
                        "id":f"timeline-overlap-{idx}", "type":"履历时间重叠待确认",
                        "location":path, "path":path, "original":original,
                        "reason":f"与另一段已记录工作经历重叠 {days} 天，可能是兼职或时间标注方式，建议确认。",
                        "severity":"中",
                    })
        running_end = max(running_end, last) if running_end else last
    months_total = len(month_union)
    policies = load_rules()["date_policy"]
    score = max(0, 100 - short*policies["short_stint_penalty"] -
                len(gaps)*policies["gap_penalty"] - len(overlaps)*policies["overlap_penalty"]) if dated else None
    unparseable = len(resume.experience)-dated
    return {
        "status":"ok", "stability_score":score,
        "dated_entries":dated,"unknown_date_entries":unparseable,
        "months_total":months_total if dated and not unparseable else None,
        "known_months_total":months_total,
        "months_recorded_sum":months_recorded_sum if dated and not unparseable else None,
        "known_months_recorded_sum":months_recorded_sum,
        "total_status":"unknown" if unparseable or not dated else "known",
        "timeline":nodes, "gaps":gaps,
        "overlaps":overlaps,"issues":issues,
        "summary": ("缺少可核验的工作年月，总年限无法计算，稳定性未知"
                    if dated==0 else
                    f"有 {unparseable} 段日期待补充，总年限无法计算；已知 {dated} 段按自然月去重 {months_total} 个月。"
                    if unparseable else
                    f"可核对工作记录 {dated} 段，按自然月去重共 {months_total} 个月；时间空档 {len(gaps)} 处。"),
    }


def _related_work_months(
    resume: CandidateResume, target: Target, profile: dict,
    *, family: str, as_of: str,
) -> tuple[int, list[dict]]:
    """Conservative job-relevant tenure proxy; overlap is counted once.

    A generic role or employer name alone is insufficient. Use dated work
    whose role or actual duty text has target-function evidence.
    """
    if not target.role.strip():
        return 0, []
    terms = [target.role] if family == "general" else profile["function_terms"]
    covered: set[int] = set()
    evidence: list[dict] = []
    for first, last, index, entry in _dated_experience(
        resume, date.fromisoformat(as_of)
    ):
        locations = [(f"experience.{index}.role", entry.role)]
        locations.extend(
            (f"experience.{index}.bullets.{j}", bullet)
            for j, bullet in enumerate(entry.bullets)
        )
        supported = [
            {"path": path, "original": text} for path, text in locations
            if any(_positive_skill({"original": text}, term) for term in terms)
        ]
        if supported:
            covered.update(range(
                first.year * 12 + first.month,
                last.year * 12 + last.month + 1,
            ))
            evidence.append(supported[0])
    return len(covered), evidence[:4]


def score_match(
    resume: CandidateResume, target: Target, *,
    as_of: str = "2026-10-19",
    weight_override: dict[str, float] | None = None,
    requirements=None,
) -> dict:
    if requirements is not None:
        return _score_confirmed_requirements(resume, target, requirements, as_of)
    rules = load_rules()
    family, profile = _profile(target.role, rules)
    refs = _refs(resume)
    target_defined = bool(target.role.strip())
    jd = target.job_description
    job_terms = [s for s in rules["factors"][0]["keywords"] if _contains(jd, s)]
    skill_terms = job_terms or profile["expected_skills"]
    requirement_years = YEAR_REQUIREMENT.search(jd)
    month_requirement = (int(requirement_years[1] or requirement_years[2])*12 if requirement_years else
                         profile.get("expected_months", 0))
    timeline = calculate_timeline(resume, as_of=as_of)
    months, tenure_refs = _related_work_months(
        resume, target, profile, family=family, as_of=as_of,
    )
    rows = []
    normal_weights = weight_override or profile["weights"]
    for factor in rules["factors"]:
        factor_id = factor["id"]
        weight = normal_weights[factor_id]
        coefficient = 0.0
        actual_refs: list[dict] = []
        required = True
        reason = ""
        if factor_id == "skills":
            if skill_terms:
                strengths=[_skill_strength(refs,term) for term in skill_terms]
                found = [term for term,item in zip(skill_terms,strengths) if item[0] > 0]
                applied_count=sum(item[0]>=0.85 for item in strengths)
                actual_refs = list({ref["path"]:ref for strength,items in strengths for ref in items}.values())[:5]
                coefficient = round(sum(item[0] for item in strengths)/len(skill_terms), 4)
                reason = (
                    f"参考技能 {len(skill_terms)} 项；{len(found)} 项有正向文字证据，"
                    f"其中 {applied_count} 项有项目/工作实践描述。单纯罗列技能不等于实践证据。"
                )
            else:
                required = False
                coefficient=0.5
                reason="未提供明确技能要求，此项不参与总分。"
        elif factor_id == "function":
            terms = profile["function_terms"]
            if target_defined and family != "general":
                actual_refs=_find(refs, terms, 4, positive=True)
                title_matches = (
                    _positive_skill({"original": resume.title}, target.role)
                    if resume.title and target.role else False
                )
                coefficient = 1.0 if title_matches or len(actual_refs)>=2 else 0.5 if actual_refs else 0.0
                reason="比较目标职能与当前职位、经历的相关表述。"
            elif target_defined:
                # Unknown role: only explicit role mention counts; never infer a broad semantic match.
                actual_refs = _find(refs, [target.role], 3, positive=True)
                coefficient=1 if actual_refs else 0.0
                reason="未识别岗位族群，只检查简历是否明确提及目标职位。"
            else:
                required=False
                coefficient=0.5
                reason="未提供岗位名称，职能无法核验，不计入总分。"
        elif factor_id == "experience":
            if month_requirement:
                coefficient = round(min(1.0, months / month_requirement), 4)
                actual_refs=tenure_refs
                reason=(
                    (f"已记录任职 {timeline['months_total']} 月，" if timeline['months_total'] is not None else "部分任职日期缺失，总年限无法计算；") + "其中可见岗位职能证据"
                    f"且起止年月明确的相关任职 {months} 月（重叠去重）；"
                    f"评估参考阈值 {month_requirement} 月。"
                )
                if not requirement_years:
                    reason+=" 阈值来自岗位族群初版规则，不是企业官方条件。"
            else:
                required=False; coefficient=0.5
                reason="未提供工作年限条件，且未有可核定的族群阈值，此项不计分。"
        elif factor_id == "projects":
            terms = job_terms + profile["project_terms"]
            project_refs=[r for r in refs if r["path"].startswith("projects.")]
            actual_refs=_find(project_refs,terms,positive=True)
            if not actual_refs:
                actual_refs=_find([r for r in refs if r["path"].startswith("experience.") and ".bullets." in r["path"]],terms,positive=True)
            if not terms:
                required=False
                coefficient=0.5
                reason="未提供可判定的项目或职能条件，本项不计分。"
            else:
                coefficient=1 if len(actual_refs)>=2 else 0.5 if actual_refs else 0.0
                reason="只计入与目标项目关键词相关且存在正向原文证据的工作或项目。"
        elif factor_id == "education":
            demanded = [x for x in ("博士","硕士","本科","学士","大专","专科","phd","master","bachelor") if _contains(jd,x)]
            if demanded:
                education_refs=[r for r in refs if r["path"].startswith("education.")]
                actual_refs=_find(education_refs,demanded,positive=True)
                coefficient=1 if actual_refs else 0.0
                reason="仅以教育经历中的明确学历信息对照岗位要求，不将愿望或否定描述当作证据。"
            else:
                required=False;coefficient=0.5
                reason="岗位未提供学历要求，不应擅自设置学历门槛。"
        elif factor_id == "industry":
            demanded=[x for x in profile["sector_terms"] if _contains(jd,x)]
            if demanded:
                career_refs=[r for r in refs if r["path"].startswith(("experience.","projects."))]
                actual_refs=_find(career_refs,demanded,positive=True)
                coefficient=1 if actual_refs else 0.0
                reason="仅根据工作/项目经历中出现的行业词汇与岗位明确要求交叉检查。"
            else:
                required=False; coefficient=0.5
                reason="未见明确行业要求，不计分。"
        elif factor_id == "leadership":
            demanded=[x for x in rules["evidence_terms"]["leadership"] if _contains(jd,x) or _contains(target.role,x)]
            if demanded:
                role_refs=[r for r in refs if r["path"].startswith(("experience.","projects."))]
                actual_refs=_find(role_refs,demanded,positive=True)
                coefficient=1 if len(actual_refs)>=2 else 0.5 if actual_refs else 0.0
                reason="仅在目标岗位明确管理要求时，参考工作/项目中的正向职责证据。"
            else:
                required=False;coefficient=0.5
                reason="岗位未明确管理要求，不扣分。"
        rows.append({
            "id":factor_id, "label":factor["label"],"coefficient":coefficient,
            "base_weight":round(weight,5), "weight":round(weight,5),
            "status":("岗位未要求" if not required else "已体现" if coefficient >= 0.999
                      else "部分具备" if coefficient > 0 else "简历未体现"),
            "reason":reason, "evidence_refs":actual_refs,
            "_active":required,
        })
    weight_sum=sum(row["base_weight"] for row in rows if row["_active"])
    for row in rows:
        row["effective_weight"]=(round(row["base_weight"]/weight_sum,6)
                                 if row["_active"] and weight_sum else 0.0)
        del row["_active"]
        row["factor_id"] = row["id"]
        row["contribution"] = round(row["coefficient"] * row["effective_weight"] * 100, 6)
    if weight_sum:
        # Compute from unrounded base weights, not display-rounded projections.
        points=sum(row["coefficient"]*row["base_weight"] for row in rows if row["effective_weight"])
        score=round(100*points/weight_sum)
    else:
        score=0
    score=min(100,max(0,score))
    thresholds=rules["thresholds"]
    grade="高" if score>=thresholds["high"] else "中" if score>=thresholds["medium"] else "低"
    confidence="低" if not target.role or not target.job_description else "中"
    warning=("仅提供公司名称，没有目标职位/JD：这是通用证据覆盖度，不代表该公司实际录用标准。"
             if not target.role else "尚无完整官方JD：按岗位类型参考要求估计，非该企业招聘筛选概率。"
             if not jd else "岗位描述来自用户输入；该分数并非经真实录用结果校准的录取概率。")
    return {
        "status":"ok","score":score,"grade":grade,"requirements":rows,
        "raw_score":100*points/weight_sum if weight_sum else 0.0,
        "display_score":score,
        "job_family":family,"confidence":confidence,
        "calibration_warning":warning,
        "conclusion":f"候选人在当前岗位要求中的书面证据覆盖度为 {grade}（{score}/100）。",
        "score_kind":("岗位要求的书面证据覆盖度" if target_defined
                      else "资料证据指数（未提供岗位，不能用于岗位分层）"),
        "job_fit_applicable":target_defined,
        "hr_interpretation":(
            "HR 可能关注简历能否迅速呈现岗位相关证据；该分数不是通过/淘汰决策依据。"
            if target_defined else
            "只提供公司名称，缺少明确岗位要求；HR 也无法据此进行有效的岗位匹配判断。"
        ),
        "rule_version":rules["version"],
    }


def _credential_in_progress(text: str) -> bool:
    return bool(re.search(
        r"在读|攻读|就读|肄业|未毕业|备考|报考|待考|计划|预计|预期|"
        r"尚未|未参加|未取得|未获得|未持有|未通过|培训中|preparing|in progress|expected",
        text, re.I,
    ))


def _minimum_degree(description, levels):
    clauses=[part for part in re.split(r"[，,；;。\n]",description) if part.strip()]
    mandatory=[part for part in clauses if not re.search(r"优先|优选|preferred",part,re.I)]
    text="；".join(mandatory or clauses)
    return min((level for term,level in levels.items() if _contains(text,term)),default=0)


def _score_confirmed_requirements(resume, target, requirements, as_of):
    items = validate_requirements(requirements)
    rules = load_rules()
    rows = []
    for item in items:
        # Reuse the existing factor coefficient logic with THIS confirmed
        # description, rather than treating the original JD as authority.
        scoped = Target(role=item.description if item.factor_id == "function" else target.role,
                        company=target.company, job_description=item.description)
        base = score_match(resume, scoped, as_of=as_of)
        factor = next((row for row in base["requirements"] if row["id"] == item.factor_id), None)
        refs = _refs(resume)
        evidence = factor["evidence_refs"] if factor else []
        coefficient = factor["coefficient"] if factor else 0.0
        reason = factor["reason"] if factor else "仅核对要求中明确列出的证书。"
        status = factor["status"] if factor else "简历未体现"
        if item.factor_id in {"skills", "projects", "certificates"}:
            terms = [term for term in rules["factors"][0]["keywords"] if _contains(item.description, term)]
            if not terms:
                terms = re.findall(r"[A-Za-z][A-Za-z0-9+#./-]*", item.description)
                terms = [term for term in terms if term.lower() not in {"must","required","and","or","skill","skills","certificate","certification","have","hold","a","an","the","with","of","in","to"}]
            if not terms and item.factor_id == "certificates":
                terms = [re.sub(r"必须|持有|取得|具备|获得|相关|证书要求|资格证|证书|认证|[，,。；;：:\s]", "", item.description)]
            if terms and all(terms):
                pool = refs if item.factor_id == "skills" else [ref for ref in refs if ref["path"].startswith(("projects.", "experience."))] if item.factor_id == "projects" else [ref for ref in refs if ref["path"].startswith("certificates.")]
                in_progress=[]
                if item.factor_id == "certificates":
                    in_progress=[ref for ref in pool if _credential_in_progress(ref["original"]) and any(_contains(ref["original"],term) for term in terms)]
                    pool=[ref for ref in pool if ref not in in_progress]
                strengths = [_skill_strength(pool, term) for term in terms]
                coefficient = sum(strength for strength,_ in strengths) / len(terms)
                if item.factor_id == "certificates":
                    coefficient = sum(bool(evidence) for _,evidence in strengths) / len(terms)
                evidence = list({ref["path"]:ref for _,found in strengths for ref in found}.values())[:5]
                status = "已体现" if coefficient >= .999 else "部分具备" if coefficient else "简历未体现"
                reason = "按已确认要求中的明确关键词核对真实文字证据；缺少证据不等于不具备。"
                negative = [ref for ref in pool if any(_contains(ref["original"], term) and not _positive_skill(ref, term) for term in terms)]
                if not coefficient and negative:
                    status, evidence = "明确不满足", negative[:5]
                    reason = "已确认要求与简历中明确的否定事实有直接差距；请核实原文或要求。"
                elif not coefficient and in_progress:
                    status, evidence = "简历未体现", in_progress[:5]
                    reason = "原文仅说明备考、培训或待取得状态，不能作为已经持有认证的证据。"
            else:
                status, coefficient = "无法判断", 0.0
                evidence = []
                reason = "该要求没有当前规则可可靠核对的明确技能／项目／证书，需澄清要求或人工核对。"
        if item.factor_id == "education":
            levels={"博士":5,"phd":5,"硕士":4,"master":4,"本科":3,"学士":3,"bachelor":3,"大专":2,"专科":2,"高中":1}
            demanded=_minimum_degree(item.description,levels)
            education_refs=[ref for ref in refs if ref["path"].startswith("education.")]
            pending=[ref for ref in education_refs if _credential_in_progress(ref["original"])]
            observed=[(level,ref) for ref in education_refs if ref not in pending for term,level in levels.items() if _positive_skill(ref,term)]
            if demanded and observed:
                level,ref=max(observed,key=lambda pair:pair[0])
                evidence=[ref]
                coefficient=1.0 if level>=demanded else 0.0
                status="已体现" if coefficient else "明确不满足"
                reason="将已取得的学历层次与已确认最低层次比较；优先项不提高最低学历门槛。"
            elif demanded and pending:
                coefficient, status, evidence=0.0,"简历未体现",pending[:5]
                reason="原文仅说明在读、攻读或预计毕业，尚不能作为已经取得该学历的证据。"
        if item.factor_id == "experience" and calculate_timeline(resume, as_of=as_of)["total_status"] == "unknown":
            status = "无法判断"
            reason = "部分或全部工作日期缺失／异常，不能发布确定的相关年限或年限匹配分数。"
        if factor and factor["status"] == "岗位未要求" and item.factor_id not in {"skills", "projects", "certificates"}:
            status, coefficient = "无法判断", 0.0
            reason = "已确认的要求尚无可计算口径，请明确描述或关闭该评分项。"
        if not item.enabled:
            status = "已关闭"
        weight = item.weight / 100 if item.enabled else 0
        rows.append({**item.model_dump(), "coefficient":round(coefficient, 6),
                     "effective_weight":weight, "base_weight":item.weight/100,
                     "status":status, "reason":reason, "evidence_refs":evidence,
                     "contribution":round(coefficient * weight * 100, 6), "weight_unit":"percent"})
    unscorable = any(row["status"] == "无法判断" for row in rows if row["enabled"])
    raw = sum(row["coefficient"] * row["effective_weight"] * 100 for row in rows)
    display = None if unscorable else round(raw)
    grade = "无法判断" if unscorable else "高" if display >= rules["thresholds"]["high"] else "中" if display >= rules["thresholds"]["medium"] else "低"
    return {"status":"ok", "score":display, "raw_score":None if unscorable else raw,
            "display_score":display, "grade":grade, "requirements":rows,
            "job_family":_profile(target.role, rules)[0], "rule_version":rules["version"],
            "job_fit_applicable":not unscorable, "score_kind":"已确认岗位要求的书面证据覆盖度",
            "confidence":"低" if unscorable else "中", "hr_interpretation":"按已确认能力项及权重逐项核对；不作为录用概率或淘汰决定。",
            "calibration_warning":"要求及权重由用户确认；通用模型假设不是企业官方招聘条件。",
            "conclusion":"部分要求缺少可计算口径，暂不发布总分。" if unscorable else f"已确认要求的书面证据覆盖度为 {display}/100。",
            "limitations":[row["label"]+"："+row["reason"] for row in rows if row["status"] == "无法判断"]}


def weight_sensitivity(
    resume: CandidateResume, target: Target, *, trials: int = 50, seed: int = 0
) -> dict:
    rules=load_rules()
    family, profile=_profile(target.role,rules)
    base=profile["weights"]
    rng=random.Random(seed)
    measured=[score_match(resume,target)["score"]]
    for _ in range(trials):
        weights={k:v*rng.uniform(0.8,1.2) for k,v in base.items()}
        total=sum(weights.values())
        weights={k:v/total for k,v in weights.items()}
        measured.append(score_match(resume,target,weight_override=weights)["score"])
    return {
        "trials":trials, "baseline":measured[0],
        "minimum_score":min(measured),"maximum_score":max(measured),
        "spread":max(measured)-min(measured),"family":family,
        "perturbation":"±20% independent weight perturbation, renormalized",
    }


def evaluate_ordinal_benchmarks() -> dict:
    """Synthetic construct stress test; never criterion/outcome validation."""
    from .schema import CareerEntry
    from app.models import Entry
    baseline=CandidateResume(
        name="人工情景",
        title="后端开发工程师",
        experience=[CareerEntry(
            company="示例机构",role="后端开发工程师",
            start_date="2022.01",end_date="2025.12",
            heading="2022.01-2025.12 示例机构 | 后端开发工程师",
            bullets=["开发内部 API 和系统服务"]
        )],
        projects=[{"heading":"后端项目","bullets":["API 项目与系统开发"]}],
    )
    tgt=Target(role="后端开发工程师",job_description="需要 Python SQL Git Docker，3年后端系统开发经验")
    # Ordered scenarios intentionally add independently visible evidence.
    feature_sets=[
        [],
        ["Python"],
        ["Python","SQL"],
        ["Python","SQL","Git"],
        ["Python","SQL","Git","Docker"],
    ]
    values=[]
    for terms in feature_sets:
        c=baseline.model_copy(deep=True)
        c.skills=terms
        values.append(score_match(c,tgt)["score"])
    # Three controlled separations in two contrasting job families, using
    # the exact same scorer. These are NOT human-labelled hiring outcomes.
    kinds=[
        ("后端开发工程师", "Python SQL Docker Git"),
        ("数据分析师","Python SQL 数据分析"),
        ("产品经理","SQL Excel 数据分析"),
    ]
    for role, tags in kinds:
        for level in range(3):
            c=CandidateResume(name="合成候选人",title=role if level>=1 else "无关岗位")
            if level>=1:
                c.skills=tags.split(" ")[:level+1]
            if level==2:
                c.experience=[
                    CareerEntry(company="示例企业",role=role,start_date="2021.01",end_date="2025.05",
                                heading="2021.01-2025.05 示例企业 | "+role,
                                bullets=["负责 Python SQL 数据分析 产品 开发 系统 API"])
                ]
                c.projects=[Entry(heading="项目",bullets=["完成 Python SQL 数据分析 产品开发的项目"])]
            values.append(score_match(c,Target(role=role,job_description="需要 "+tags+"，2年工作经验"))["score"])
    # 5 + 9 = 14 scenarios. Strict ordering in each local group is
    # evaluated separately; do not compare different role families as equals.
    groups=[values[:5],values[5:8],values[8:11],values[11:14]]
    pairs=sum(len(g)*(len(g)-1)//2 for g in groups)
    correct=sum(g[j]>=g[i] for g in groups for i in range(len(g)) for j in range(i+1,len(g)))
    return {
        "scenario_count":len(values),"pairwise_order_accuracy":round(correct/pairs,4),
        "score_span":max(values)-min(values),
        "minimum_score":min(values),"maximum_score":max(values),
        "criterion_validated":False,
        "scope":"synthetic ordinal/construct scenarios only",
        "scores":values,
    }
