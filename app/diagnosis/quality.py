"""Small deterministic admission check shared by synchronous and task runs."""
from datetime import date

from .schema import CandidateResume


def validate_resume_for_diagnosis(resume: CandidateResume) -> None:
    from .scoring import _refs
    if not _refs(resume) and not any(value.strip() for value in resume.additional):
        raise ValueError("简历没有可分析的履历内容，请补充经历、教育、技能或个人概述")


def review_quality(resume: CandidateResume | None) -> dict:
    """Only unusable input blocks; missing details and conflicts invite review."""
    blockers, warnings = [], []
    if resume is None:
        return {"blockers":[{"path":"resume","message":"尚未完成简历解析，请先提交或重试解析。"}], "warnings":[]}
    try:
        validate_resume_for_diagnosis(resume)
    except ValueError as exc:
        blockers.append({"path":"resume", "message":str(exc)})
        return {"blockers":blockers,"warnings":warnings}

    from .scoring import _month, calculate_timeline
    from .claim_conflicts import detect_description_conflicts
    today = date.today()
    if not resume.experience:
        warnings.append({"path":"experience", "message":"未提供工作／实习经历，相关年限与任期暂时无法判断；可在明确限制下继续。"})
    for index, entry in enumerate(resume.experience):
        prefix=f"experience.{index}."
        for field, label in (("company","公司／机构"),("role","职位"),("start_date","开始年月"),("end_date","结束年月")):
            if not getattr(entry,field).strip():
                warnings.append({"path":prefix+field,"message":label+"尚未填写，请核对；缺少日期时不发布确定年限。"})
        start=_month(entry.start_date)
        present=entry.end_date.strip().lower() in {"至今","现在","present","current"}
        end=today if present else _month(entry.end_date)
        for field, value, parsed in (("start_date",entry.start_date,start),("end_date",entry.end_date,end)):
            if value.strip() and parsed is None:
                warnings.append({"path":prefix+field,"message":"年月格式无法识别，请使用 YYYY.MM；无法可靠计算对应任期。"})
        if start and end and end < start:
            warnings.append({"path":prefix+"end_date","message":"结束年月早于开始年月，请对照原文核对；对应年限无法计算。"})
        if start and start > today or end and not present and end > today:
            warnings.append({"path":prefix+("start_date" if start and start > today else "end_date"),"message":"日期晚于当前时点，请核对是否为预计日期；不能将未来任期视为已经历年限。"})
        if not any(value.strip() for value in entry.bullets):
            warnings.append({"path":prefix+"bullets","message":"尚未描述实际职责／成果，岗位相关性证据有限，可补充真实内容。"})
    for issue in calculate_timeline(resume,as_of=today.isoformat())["issues"]:
        warnings.append({"path":issue["location"],"message":issue["reason"]})
    for issue in detect_description_conflicts(resume):
        warnings.append({"path":issue["location"],"message":issue["type"]+"："+issue["reason"]})
    # The same missing date can affect several checks; show one identical hint.
    warnings=list({(item["path"],item["message"]):item for item in warnings}.values())
    return {"blockers":blockers,"warnings":warnings}
