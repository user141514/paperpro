"""Stateless user journey: parse/paste, review, goal, five outputs, selected export."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json

from fastapi.testclient import TestClient
from app.main import app
from app.diagnosis.schema import CandidateResume, CareerEntry
from app.diagnosis.scoring import evaluate_ordinal_benchmarks

client=TestClient(app,raise_server_exceptions=False)
TEXT=(
    "陈晓明\n求职意向：后端开发工程师\n专业技能\nPython,SQL,Docker,Git\n"
    "工作经历\n2022.07 - 2025.06  星辰科技 | 后端开发工程师\n"
    "- 开发 Python SQL 接口服务，维护 Docker 部署。\n"
    "- 优化 API 耗时 20%。\n"
    "项目经历\n订单服务系统\n- 使用 Python 构建服务API。\n"
    "教育背景\n2018.09 - 2022.06 本科计算机科学\n"
    "证书\nCET-6\n"
)


def _draft():
    result=client.post("/api/diagnosis/paste",json={"text":TEXT})
    assert result.status_code==200,result.text
    return result.json()


def _report():
    resume=_draft()["resume"]
    resume["summary"]="希望参与后端开发工程师岗位。"
    return client.post("/api/diagnosis/report",json={
        "resume":resume,
        "target":{"role":"后端开发工程师","company":"示例公司",
                  "job_description":"熟悉 Python SQL Docker Git，2年开发经验"},
        "as_of":"2026-10-19",
    })


def test_paste_returns_full_editable_schema_without_altering_evidence():
    x=_draft()
    assert x["sha256"]==sha256(TEXT.encode()).hexdigest()
    assert x["resume"]["source_sha256"]==x["sha256"]
    assert x["resume"]["source_text"]==TEXT
    assert x["resume"]["name"]=="陈晓明"
    assert x["resume"]["experience"]
    for key in ("company","role","start_date","end_date"):
        assert key in x["resume"]["experience"][0]
    for field in ("certificates","self_evaluation","education","projects","skills"):
        assert field in x["resume"]


def test_pasted_text_whitespace_rejected_and_empty_goal_rejected():
    assert client.post("/api/diagnosis/paste",json={"text":" \n"}).status_code==422
    res=client.post("/api/diagnosis/report",json={
        "resume":_draft()["resume"],
        "target":{"role":" ","company":" "},
    })
    assert res.status_code==422


def test_upload_recognizes_types_and_size_and_does_not_modify_bytes():
    assert client.post("/api/diagnosis/parse",files={"file":("file.exe",b"not valid","application/octet-stream")}).status_code==415
    assert client.post("/api/diagnosis/parse",files={"file":("file.docx",b"a"*(10*1024*1024+1))}).status_code==413
    from docx import Document
    doc=Document()
    doc.add_paragraph(TEXT)
    file=BytesIO()
    doc.save(file)
    original=file.getvalue()
    response=client.post("/api/diagnosis/parse",files={"file":("candidate.docx",original,"application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert response.status_code==200,response.text
    assert response.json()["sha256"]==sha256(original).hexdigest()
    assert file.getvalue()==original


def test_full_report_trace_and_evidence_and_all_five_sections():
    res=_report()
    assert res.status_code==200,res.text
    b=res.json()
    assert set(b["dimensions"])=={"match","experience","potential","motivation","verification"}
    assert b["meta"]["rules_version"]==client.get("/api/diagnosis/rules").json()["version"]
    assert b["meta"]["score_is_hiring_probability"] is False
    assert len(b["dimensions"]["match"]["requirements"])>=6
    assert all(v["status"]=="ok" for v in b["dimensions"].values())
    assert b["suggestions"]
    assert all(item["source_modules"] for item in b["suggestions"])
    for issue in b["dimensions"]["verification"]["issues"]:
        assert issue["location"] and issue["original"]


def test_report_disable_dimension_and_rerun_score_stability():
    data={"resume":_draft()["resume"],"target":{"role":"后端开发工程师"},"as_of":"2026-10-19"}
    values=[]
    for i in range(7):
        response=client.post("/api/diagnosis/report",json=data)
        assert response.status_code==200,response.text
        values.append(response.json()["dimensions"]["match"]["score"])
    assert len(set(values))==1
    data["enabled_sections"]=["match","verification"]
    report=client.post("/api/diagnosis/report",json=data).json()
    assert report["dimensions"]["experience"]["status"]=="disabled"
    assert report["dimensions"]["potential"]["status"]=="disabled"
    assert report["dimensions"]["match"]["status"]=="ok"


def test_selected_only_text_todo_and_interview_export():
    result=_report().json()
    suggestions=result["suggestions"]
    want=[suggestions[0]["id"], suggestions[-1]["id"]]
    res=client.post("/api/diagnosis/export",json={
        "report":result,"selected_ids":want,"kind":"todo","format":"txt",
    })
    assert res.status_code==200,res.text
    assert res.headers["x-selected-count"]=="2"
    content=res.content.decode("utf-8-sig")
    assert suggestions[0]["title"] in content
    assert suggestions[-1]["title"] in content
    assert all(x["title"] not in content for x in suggestions if x["id"] not in want)
    issue_questions=result["interview_questions"]
    assert issue_questions, "fixture includes unsupported metric 20%"
    sel=client.post("/api/diagnosis/export",json={
        "report":result,"selected_ids":[issue_questions[0]["id"]],
        "kind":"questions","format":"txt",
    })
    assert sel.status_code==200
    assert issue_questions[0]["check"] in sel.content.decode("utf-8-sig")
    assert client.post("/api/diagnosis/export",json={
        "report":result,"selected_ids":["invalid-id"],"format":"txt"
    }).status_code==422


def test_selected_todo_pdf_is_real_and_selected_count_is_exact():
    result=_report().json()
    selected=[result["suggestions"][0]]
    response=client.post("/api/diagnosis/export",json={
        "report":result,"selected_ids":[selected[0]["id"]],"format":"pdf",
    })
    assert response.status_code==200,response.text[:300]
    assert response.content[:4]==b"%PDF"
    assert response.headers["x-selected-count"]=="1"
    import pymupdf
    reader=pymupdf.open(stream=response.content,filetype="pdf")
    text="\n".join(page.get_text() for page in reader)
    assert selected[0]["title"] in text
    assert all(x["title"] not in text for x in result["suggestions"] if x["id"]!=selected[0]["id"])


def test_independent_section_failure_returns_other_results(monkeypatch):
    from app.diagnosis import engine
    def broken(*args,**kwargs):
        raise RuntimeError("SIMULATED DIMENSION FAILURE")
    monkeypatch.setitem(engine.RUNNERS,"potential",broken)
    result=_report()
    assert result.status_code==200
    sections=result.json()["dimensions"]
    assert sections["potential"]["status"]=="error"
    assert sections["match"]["status"]=="ok"
    assert sections["verification"]["status"]=="ok"


def test_invalid_switch_does_not_run_any_section():
    result=client.post("/api/diagnosis/report",json={
        "resume":_draft()["resume"],"target":{"role":"后端开发"},
        "enabled_sections":["match","unknown"],
    })
    assert result.status_code==422


def test_calibration_is_not_mislabeled_predictive_accuracy():
    b=evaluate_ordinal_benchmarks()
    assert b["criterion_validated"] is False
    assert b["scenario_count"]>=14
    assert b["pairwise_order_accuracy"]>=0.85


def test_optional_ai_requires_explicit_consent_even_if_user_supplied_key():
    payload={
        "resume":_draft()["resume"],
        "target":{"role":"后端开发工程师"},
        "use_ai":True, "api_key":"FAKE_TEST_ONLY",
        "ai_consent":False,
    }
    response=client.post("/api/diagnosis/report",json=payload)
    assert response.status_code==422
    assert "FAKE_TEST_ONLY" not in response.text


def test_ai_only_adds_interpretation_to_fixed_rules_not_score(monkeypatch):
    plain=_report().json()
    requests=[]
    class FakeReply:
        def raise_for_status(self): pass
        def json(self): return {"choices":[{"message":{"content":json.dumps({
            "experience":{"code":"timeline_review","evidence_paths":["experience.0.heading"]},
            "potential":{"code":"growth_evidence","evidence_paths":[]},
            "motivation":{"code":"jd_alignment","evidence_paths":[]},
        },ensure_ascii=False)}}]}
    class FakeHttp:
        def __init__(self,**kw): assert kw["follow_redirects"] is False
        def __enter__(self):return self
        def __exit__(self,*_):return None
        def post(self,url,**kw):requests.append((url,kw));return FakeReply()
    monkeypatch.setattr("app.diagnosis.narrative.httpx.Client",FakeHttp)
    payload={"resume":_draft()["resume"],
             "target":{"role":"后端开发工程师","company":"示例公司",
                       "job_description":"熟悉 Python SQL Docker Git，2年开发经验"},
             "as_of":"2026-10-19",
             "use_ai":True,"ai_consent":True,"api_key":"EPHEMERAL_TEST_ONLY","ai_provider":"deepseek"}
    result=client.post("/api/diagnosis/report",json=payload)
    assert result.status_code==200,result.text
    body=result.json()
    assert body["meta"]["ai_narrative"]=="completed"
    assert body["dimensions"]["match"]["score"]==plain["dimensions"]["match"]["score"]
    assert body["dimensions"]["experience"]["stability_score"]==plain["dimensions"]["experience"]["stability_score"]
    assert body["dimensions"]["experience"]["ai_commentary"].startswith("时间线")
    assert "experience.0.heading" in body["dimensions"]["experience"]["ai_commentary"]
    assert requests[0][0]=="https://api.deepseek.com/v1/chat/completions"
    assert requests[0][1]["json"]["messages"][0]["content"].count("candidate-rubric-0.3.0")>=1
    assert "EPHEMERAL_TEST_ONLY" not in result.text


def test_qualitative_ai_hallucination_is_not_exposed_as_authoritative_commentary(monkeypatch):
    # No Arabic numerals: the old token filter silently accepted this.
    invented="二〇二〇年进入腾讯，晋升总监，并获得博士学历。"

    class FakeReply:
        def raise_for_status(self): pass
        def json(self): return {"choices":[{"message":{"content":json.dumps({
            "experience_narrative": invented,
            "potential_narrative": invented,
            "motivation_narrative": invented,
        },ensure_ascii=False)}}]}

    class FakeHttp:
        def __init__(self,**kw): pass
        def __enter__(self): return self
        def __exit__(self,*_): return None
        def post(self,url,**kw): return FakeReply()

    monkeypatch.setattr("app.diagnosis.narrative.httpx.Client",FakeHttp)
    response=client.post("/api/diagnosis/report",json={
        "resume":_draft()["resume"],
        "target":{"role":"后端开发工程师"},
        "use_ai":True,"ai_consent":True,"api_key":"FAKE_TEST_ONLY",
    })
    assert response.status_code==200
    body=response.json()
    assert body["dimensions"]["match"]["status"]=="ok"
    assert body["meta"]["ai_narrative"]=="unavailable"
    assert invented not in response.text


def test_invalid_custom_provider_port_does_not_crash_the_report(monkeypatch, tmp_path):
    import app.settings as settings

    monkeypatch.setattr(settings, "SETTINGS_DIR", tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({
        "configured":{
            "api_key":"",
            "base_url":"https://example.invalid:bad/v1",
            "model":"custom-model"
        },
    }),encoding="utf-8")
    result=client.post("/api/diagnosis/report",json={
        "resume":_draft()["resume"],
        "target":{"role":"后端开发工程师"},
        "use_ai":True,
        "ai_consent":True,
        "ai_provider":"configured",
        "api_key":"EPHEMERAL_TEST_ONLY",
    })
    assert result.status_code==200,result.text
    body=result.json()
    assert body["meta"]["ai_narrative"]=="unavailable"
    assert body["dimensions"]["match"]["status"]=="ok"
    assert "EPHEMERAL_TEST_ONLY" not in result.text


def test_optional_ai_numeric_hallucination_falls_back_without_losing_report(monkeypatch):
    class FakeReply:
        def raise_for_status(self):pass
        def json(self):return {"choices":[{"message":{"content":json.dumps({
            "experience_narrative":"该候选人有 9999 年经验",
            "potential_narrative":"潜力高",
            "motivation_narrative":"匹配岗位",
        },ensure_ascii=False)}}]}
    class FakeHttp:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*_):return None
        def post(self,url,**kw):return FakeReply()
    monkeypatch.setattr("app.diagnosis.narrative.httpx.Client",FakeHttp)
    response=client.post("/api/diagnosis/report",json={
        "resume":_draft()["resume"],"target":{"role":"后端开发工程师"},
        "use_ai":True,"ai_consent":True,"api_key":"FAKE_TEST_ONLY"
    })
    assert response.status_code==200
    result=response.json()
    assert result["meta"]["ai_narrative"]=="unavailable"
    assert result["dimensions"]["match"]["status"]=="ok"
    assert "ai_commentary" not in result["dimensions"]["experience"]
