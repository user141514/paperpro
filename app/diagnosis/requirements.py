"""Prepare editable requirements from the same deterministic rule vocabulary."""
import re

from .schema import Target
from .scoring import YEAR_REQUIREMENT, _contains, _profile, load_rules


def prepare_requirements(target: Target) -> dict:
    rules = load_rules()
    family, profile = _profile(target.role, rules)
    jd = target.job_description.strip()
    source = "user_jd" if jd else "generic_model"
    items = []

    def add(factor, label, description):
        if len(items) >= 40 or any(item["factor_id"] == factor and item["description"] == description for item in items):
            return
        items.append({"id":f"req-{len(items)+1:02d}", "factor_id":factor,
                      "label":label, "description":description, "weight":0,
                      "enabled":True, "hard_gate":bool(re.search(r"必须|必备|至少|硬性|不得低于|must|required", description, re.I)),
                      "source":source})

    if jd:
        clauses = [part.strip() for part in re.split(r"[\n。；;，,]+", jd) if part.strip()]
        for clause in clauses:
            if re.search(r"不要求|无需|不限|not required", clause, re.I):
                continue
            skills = [term for term in rules["factors"][0]["keywords"] if _contains(clause, term)]
            if re.search(r"掌握|熟悉|熟练|精通|擅长|proficien|skills?|knowledge",clause,re.I):
                explicit=re.findall(r"[A-Za-z][A-Za-z0-9+#./-]*",clause)
                stop={"and","or","must","required","be","in","with","of","have","skills","skill","knowledge","proficient"}
                skills += [term for term in explicit if term.lower() not in stop and not any(_contains(known,term) for known in skills)]
            for term in skills:
                add("skills", term + "能力", ("必须掌握 " if re.search(r"必须|必备|must|required", clause, re.I) else "掌握 ") + term)
            if YEAR_REQUIREMENT.search(clause):
                add("experience", "相关工作年限", clause)
            if re.search(r"博士|硕士|本科|学士|大专|专科|学历|bachelor|master|phd", clause, re.I):
                existing=next((item for item in items if item["factor_id"]=="education"),None)
                if existing and re.search(r"优先|优选|preferred",clause,re.I):
                    existing["description"] += "，"+clause
                else:
                    add("education", "学历要求", clause)
            if re.search(r"证书|资格证|认证|certificate|certification", clause, re.I):
                add("certificates", "证书要求", clause)
            if any(_contains(clause, term) for term in profile["sector_terms"]):
                add("industry", "行业经历", clause)
            if any(_contains(clause, term) for term in rules["evidence_terms"]["leadership"]):
                add("leadership", "管理职责", clause)
            if re.search(r"项目|交付|成果|project", clause, re.I):
                add("projects", "项目实践", clause)
        if not items:
            add("function", "岗位职责（待核对）", jd)
    else:
        add("function", "岗位职责", target.role)
        for term in profile["expected_skills"]:
            add("skills", term + "能力", term)
        if profile.get("expected_months"):
            add("experience", "通用相关年限参考", f"{profile['expected_months']/12:g} 年相关工作经验（通用岗位参考，非企业条件）")
        if profile["project_terms"]:
            add("projects", "通用项目实践", "、".join(profile["project_terms"]))
        if len(items) == 1:
            items[0]["label"] = "通用岗位职责（待核对）"

    # Profile weights are suggestions, never a hidden accepted user preference.
    factor_counts = {factor:sum(item["factor_id"] == factor for item in items) for factor in {item["factor_id"] for item in items}}
    bases = [profile["weights"].get(item["factor_id"], .1) / factor_counts[item["factor_id"]] for item in items]
    total = sum(bases)
    for item, base in zip(items, bases):
        item["weight"] = round(base / total * 100, 2)
    items[-1]["weight"] = round(items[-1]["weight"] + 100 - sum(item["weight"] for item in items), 2)
    warnings = (["使用通用岗位模型及建议权重，并非目标公司的真实招聘要求；请确认或修改后启动。"] if not jd else [])
    if len(items) < 6:
        warnings.append("当前依据仅形成少于六项有效要求；未拆词凑数，请核对并按真实岗位补充。")
    if family == "general":
        warnings.append("未识别专用岗位模型，仅按明确文字核对，无法可靠推断的要求需人工确认。")
    return {"requirements":items, "source":source, "rule_version":rules["version"], "warnings":warnings}
