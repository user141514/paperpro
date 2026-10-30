"""High-precision, source-linked contradictions in resume descriptions.

Only compare two explicit, incompatible assertions about the SAME technology
and a compatible subject/time/scope. Absence of evidence is not negation.
These are review candidates, never judgements about a candidate's honesty.
"""
from __future__ import annotations

from hashlib import sha256
import re

from .schema import CandidateResume
from .scoring import _refs, load_rules


# "Uses X" does not imply "is expert in X", and "doesn't know advanced X"
# does not necessarily contradict a basic skill listing.
_DENIALS = (
    ("not_used", r"没有使用|从未使用|未使用|没用过|\bnever\s+used\b|\bdid\s+not\s+use\b"),
    ("unable", r"不会|不懂|未掌握|没掌握|无法使用|不能使用|\bcannot\s+use\b|\bdo\s+not\s+know\b"),
    ("unfamiliar", r"不熟悉|不擅长|\bnot\s+familiar\s+with\b|\bnot\s+proficient\s+in\b|\bunfamiliar\s+with\b"),
)
_AFFIRMATIONS = (
    ("proficient", r"熟悉|掌握|精通|擅长|熟练(?:使用|掌握)?|\bproficient\s+in\b|\bskilled\s+in\b|\bexperienced\s+with\b"),
    ("able", r"会|能使用|能够使用|\bcan\s+use\b"),
    ("used", r"使用(?:过)?|运用|\bused?\b|\bbuilt\s+with\b"),
)
_COMPATIBLE = {
    "proficient": {"unable", "unfamiliar"},
    "able": {"unable"},
    "listed": {"unable"},
    "used": {"not_used"},
}
_TEMPORAL = re.compile(
    r"过去|以前|此前|先前|原先|曾经|当时|起初|最初|入职时|"
    r"初期|后期|后来|随后|逐步|尚未|未来|以后|计划|"
    r"从不熟悉到熟悉|\b(?:previously|formerly|used\s+to)\b|"
    r"(?:19|20)\d{2}\s*年",
    re.I,
)
_OTHER_ACTOR = re.compile(
    r"团队|同事|客户|业务方|招聘方|应聘者|其他人|"
    r"岗位要求|任职要求|招聘要求|JD|job\s+description",
    re.I,
)
_SPLIT = re.compile(r"[，,。；;!?！？\n]|\bbut\b|但(?:是)?|然而", re.I)


def _scope(path: str) -> str | None:
    if path.startswith("skills.") or path in {"summary", "self_evaluation"}:
        return "current"
    item = re.fullmatch(r"(experience|projects)\.(\d+)\.bullets\.\d+", path)
    return f"{item[1]}.{item[2]}" if item else None


def _technical_terms() -> list[str]:
    # One authoritative vocabulary; two-letter words such as Go are often
    # normal English verbs, so do not infer technical meaning from them.
    return [
        name for name in load_rules()["factors"][0]["keywords"]
        if name.isascii() and len(name) >= 3 and re.search("[A-Za-z]", name)
    ]


def _near(pattern: str, before: str, after: str) -> bool:
    if re.search(r"(?:" + pattern + r")\s*$", before, re.I):
        return True
    return bool(re.match(r"^\s*[:：\-—（(\[]?\s*(?:" + pattern + r")", after, re.I))


def _read_claims(ref: dict, term: str) -> list[tuple[str, str, dict]]:
    """One assertion per clause, preserving the exact user-visible snippet."""
    claims = []
    for part in _SPLIT.split(ref["original"])[:80]:
        if not part.strip() or len(part) > 350:
            continue
        if _TEMPORAL.search(part) or _OTHER_ACTOR.search(part):
            continue
        match = re.search(
            r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])",
            part, re.I,
        )
        if not match:
            continue
        before, after = part[:match.start()], part[match.end():]
        status = None
        qualified_denial = False
        for category, pattern in _DENIALS:
            if _near(pattern, before, after):
                # A denial limited to an advanced subtopic is not a denial
                # of the whole technology. It must also NOT fall through
                # to the positive "熟悉" substring inside "不熟悉".
                if category == "unfamiliar" and re.match(
                    r"^\s*(?:的|方面|高级|底层|内部|生态)", after
                ):
                    qualified_denial = True
                    break
                status = ("denied", category)
                break
        if qualified_denial:
            continue
        if status is None:
            for category, pattern in _AFFIRMATIONS:
                if _near(pattern, before, after):
                    status = ("affirmed", category)
                    break
        if status is None and ref["path"].startswith("skills."):
            if re.search(r"学习中|初学|正在学|计划学|希望学|learning|beginner", part, re.I):
                continue
            if re.fullmatch(r"\s*" + re.escape(term) + r"\s*", part, re.I):
                status = ("affirmed", "listed")
        if status:
            stance, category = status
            claims.append((stance, category, {
                "path": ref["path"],
                "original": part.strip(),
            }))
    return claims


def conflict_refs(resume: CandidateResume) -> list[dict]:
    """Exact bounded inputs: apply the global limit before selecting scopes."""
    return [ref for ref in _refs(resume)[:350] if _scope(ref["path"])]


def detect_description_conflicts(
    resume: CandidateResume, *, limit: int = 12,
) -> list[dict]:
    """Identify reviewable contradictions without modifying score or resume.

    Compare current skill claims across summary/self-evaluation/skill fields,
    or claims inside the same experience/project entry. Historical learning
    statements, JD text, and third-party claims are deliberately excluded.
    """
    if limit <= 0:
        return []
    terms = _technical_terms()
    observed: dict[tuple[str, str], dict[str, list[tuple[str, dict]]]] = {}
    for ref in conflict_refs(resume):
        scope = _scope(ref["path"])
        if not scope:
            continue
        for term in terms:
            for stance, category, evidence in _read_claims(ref, term):
                group = observed.setdefault(
                    (scope, term), {"affirmed": [], "denied": []}
                )
                if len(group[stance]) < 4:
                    group[stance].append((category, evidence))

    issues = []
    for (scope, term), group in observed.items():
        compatible = None
        for yes_kind, positive in group["affirmed"]:
            for no_kind, negative in group["denied"]:
                if no_kind not in _COMPATIBLE[yes_kind]:
                    continue
                if (positive["path"] == negative["path"] and
                        positive["original"] == negative["original"]):
                    continue
                compatible = (yes_kind, no_kind, positive, negative)
                break
            if compatible:
                break
        if not compatible:
            continue
        yes_kind, no_kind, positive, negative = compatible
        issue_id = sha256(
            (scope + "|" + term + "|" + positive["path"] + "|" +
             positive["original"] + "|" + negative["path"] + "|" +
             negative["original"]).encode("utf-8")
        ).hexdigest()[:12]
        mismatch = (
            "在同一段经历中，一处明确说使用过，另一处明确说没有使用"
            if yes_kind == "used" else
            "一处明确肯定掌握程度，另一处明确否定了该能力"
        )
        issues.append({
            "id": f"claim-conflict-{issue_id}",
            "type": "简历描述相互矛盾",
            "conflict_kind": "explicit_skill_polarity",
            "subject": term,
            "location": positive["path"],
            "original": positive["original"],
            "related_location": negative["path"],
            "related_original": negative["original"],
            "evidence_refs": [positive, negative],
            "reason": (
                f"关于 {term} 的陈述需要核对：{mismatch}。"
                "请确认双方是否指向同一时期、同一主体和同一事实；"
                "自动检查不能决定哪一句真实，也不会修改简历。"
            ),
            "severity": "中",
        })
        if len(issues) >= min(limit, 12):
            break
    return issues
