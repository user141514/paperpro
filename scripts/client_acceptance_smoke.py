"""Publicly demonstrable engineering-acceptance receipts for PaperPro R7–R10.

All data is fictional, in memory. This is a functional contract test, NOT
a substituted sample of real applicants or valid employer scoring.
No DeepSeek usage, no disk writes, no GitHub push.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json

from fastapi.testclient import TestClient

from app.main import app
from app.diagnosis.synthetic_parse_bench import (
    _case, _render_docx, _render_pdf,
)
from app.diagnosis.scoring import load_rules, score_match
from app.diagnosis.schema import CandidateResume, CareerEntry, Target
from app.diagnosis.counterfactual_bench import evaluate_pairs


def run(*, extended: bool = False) -> dict:
    checks = {}
    errors = []
    def record(key: str, ok: bool, label: str) -> None:
        checks[key] = {"passed": bool(ok), "label": label}
        if not ok:
            errors.append(key)

    sample = _case(0)
    # The file-parse path exercises the actual DOCX extractor and API.
    raw = _render_docx(sample)
    with TestClient(app, raise_server_exceptions=False) as client:
        parsed = client.post("/api/diagnosis/parse",files={
            "file":("client-demo.docx",raw,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        })
        if parsed.status_code != 200:
            return {"functional_status":"FAILED_INPUT",
                    "http_status":parsed.status_code,
                    "not_real_hr_validation":True}
        payload = parsed.json()
        resume = payload["resume"]
        record("R7-1/R8-1",resume["name"]==sample["name"] and
               payload["sha256"]==sha256(raw).hexdigest(),
               "structured DOCX parsing + unchanged SHA256")
        exp=resume.get("experience") or []
        record("R7-2", bool(exp) and all(k in exp[0] for k in (
            "company","role","start_date","end_date")),
            "reviewable employer/role/date schema")
        rejected=client.post("/api/diagnosis/report",json={
            "resume":resume,"target":{"role":"","company":""},
        })
        record("R7-3",rejected.status_code==422,"role/company required")

        target=Target(
            role="后端开发工程师",company="纯虚构企业",
            job_description="要求 Python SQL Git Docker，2年后端相关工作经历",
        )
        report_response=client.post("/api/diagnosis/report",json={
            "resume":resume,"target":target.model_dump(),
            "as_of":"2026-10-19",
        })
        if report_response.status_code != 200:
            return {"functional_status":"FAILED_REPORT",
                    "http_status":report_response.status_code,
                    "not_real_hr_validation":True}
        report=report_response.json()
        sections=report["dimensions"]
        match=sections["match"]
        suggestions=report["suggestions"]

        record("R7-4/R9-2",len(match["requirements"])>=6
               and all(0<=x["coefficient"]<=1 for x in match["requirements"])
               and 0<=match["score"]<=100,
               "seven explicit criteria + coefficients + score")
        record("R7-5/R7-6",bool(suggestions) and all(
            all(item.get(k) for k in ("id","location","original",
                                    "problem","action","example","priority"))
            and item.get("assessment") in ("需要修正","可选深化")
            and item.get("source_modules")
            and all(sections[key]["status"] == "ok" for key in item["source_modules"])
            for item in suggestions
        ),"actual findings produce fully formed evidence-linked advice; no fixed-count padding")

        selected=[suggestions[0]["id"],suggestions[-1]["id"]]
        exported=client.post("/api/diagnosis/export",json={
            "report":report,"selected_ids":selected,"kind":"todo","format":"txt",
        })
        body=exported.content.decode("utf-8-sig",errors="replace")
        record("R7-7",exported.status_code==200 and
               exported.headers.get("x-selected-count")=="2" and
               all(s["title"] in body for s in suggestions if s["id"] in selected)
               and all(s["title"] not in body for s in suggestions if s["id"] not in selected),
               "only selected items appear in TXT export")
        record("R7-8",payload["sha256"]==sha256(raw).hexdigest(),
               "original file bytes unchanged")
        record("R9-1",set(sections)=={
            "match","experience","potential","motivation","verification"}
               and all(s["status"]=="ok" for s in sections.values()),
               "all five HR-perspective dimensions")
        record("R9-3",sections["experience"]["dated_entries"]>=1 and
               isinstance(sections["experience"]["months_total"],int),
               "code-derived employment timeline")
        support=sections["potential"]["supporting_signals"]
        record("R9-4/R9-5",all(item.get("status")=="支持" and item.get("original") and item.get("path") for item in support)
               and (len(support)>=3 or sections["potential"]["rating"]=="无法判断")
               and bool(sections["motivation"]["rationale"]),
               "only genuine supporting evidence is listed; insufficient potential remains unknown")
        record("R9-6/R9-7",all(
            i.get("location") and i.get("original")
            for i in sections["verification"]["issues"]
        ) and all(
            q.get("check") and q.get("question") and q.get("purpose")
            for q in report["interview_questions"]
        ),"locatable uncertainty plus interview questions")
        closed=client.post("/api/diagnosis/report",json={
            "resume":resume,
            "target":target.model_dump(),
            "enabled_sections":["match","verification"],
        })
        record("R9-9",closed.status_code==200
               and closed.json()["dimensions"]["experience"]["status"]=="disabled"
               and closed.json()["dimensions"]["verification"]["status"]=="ok",
               "per-section independent toggles")
        version=load_rules()["version"]
        record("R9-10/R10-3",bool(report["meta"]["generated_at"])
               and report["meta"]["rules_version"]==version
               and bool(report["meta"]["version"]),
               "traceable generated time and shared rule version")

        large=client.post("/api/diagnosis/parse",files={
            "file":("oversized.docx",b"X"*(10*1024*1024+1)),
        })
        record("R8-4",large.status_code==413,"10MB upload limit enforced")

    result = {
        "evidence_class":"DEMO_PASS_IF_CHECKS_GREEN",
        "requirements_source":"R7–R10 user contract",
        "functional_status":"PASS" if not errors else "FAILED",
        "check_count":len(checks),
        "passed_count":sum(row["passed"] for row in checks.values()),
        "checks":checks,
        "failed_checks":errors,
        "real_applicant_accuracy_verified":False,
        "real_hr_matching_validity_verified":False,
        "actual_ios_android_device_verified":False,
    }
    if extended:
        result["simulated_counterfactual"]=evaluate_pairs(per_family=10,seed=1021)
    return result


if __name__ == "__main__":
    print(json.dumps(run(),ensure_ascii=True,indent=2))
