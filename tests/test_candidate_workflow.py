"""V3 workflow acceptance uses isolated synthetic state, never the user's data."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.main import app

TEXT = """陈示例
邮箱 demo@example.test
工作经历
2021.01-2024.12 示例科技有限公司 Python开发工程师
负责Python数据接口与SQL查询，维护已有报表。
教育经历
2017.09-2021.06 示例大学 本科 计算机科学
技能
Python、SQL、Git
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERPRO_DATA_DIR", str(tmp_path))
    with TestClient(app) as result:
        yield result


def create(client):
    response = client.post("/api/diagnosis/tasks", json={"text": TEXT, "privacy_consent": True})
    assert response.status_code == 201, response.text
    return response.json()


def parsed(client):
    task = create(client)
    response = client.post(f"/api/diagnosis/tasks/{task['id']}/parse", json={"operation_id": "parse-test-1"})
    assert response.status_code == 200, response.text
    return response.json()


def ready(client):
    task = parsed(client)
    state = task["state"]
    state.update(target={"role": "Python开发工程师", "company": "", "job_description": ""},
                 review_confirmed=True, requirements_confirmed=True)
    result = client.post("/api/diagnosis/requirements", json={"target": state["target"]})
    assert result.status_code == 200, result.text
    state["requirements"] = result.json()["requirements"]
    response = client.patch(f"/api/diagnosis/tasks/{task['id']}", json={"expected_revision": task["revision"], "state": state})
    assert response.status_code == 200, response.text
    saved = response.json()
    saved["state"].update(review_confirmed=True, requirements_confirmed=True,
                          confirmed_fields=[item["path"] for item in saved["quality"].get("critical_fields", [])])
    response = client.patch(f"/api/diagnosis/tasks/{task['id']}", json={"expected_revision": saved["revision"], "state": saved["state"]})
    assert response.status_code == 200, response.text
    return response.json()


def generated(client):
    task = ready(client)
    response = client.post(f"/api/diagnosis/tasks/{task['id']}/run", json={"expected_revision": task["revision"], "operation_id": "run-test-1"})
    assert response.status_code == 200, response.text
    return response.json()


def test_consent_ownership_and_deleted_export(client):
    assert client.post("/api/diagnosis/tasks", json={"text": TEXT, "privacy_consent": False}).status_code == 422
    task = create(client)
    with TestClient(app) as other:
        assert other.get(f"/api/diagnosis/tasks/{task['id']}").status_code == 404
        assert other.delete(f"/api/diagnosis/tasks/{task['id']}").status_code == 404
    assert client.delete(f"/api/diagnosis/tasks/{task['id']}").status_code == 200
    assert client.get(f"/api/diagnosis/tasks/{task['id']}/export?kind=report&format=txt").status_code == 404


def test_original_field_history_and_save_conflict(client):
    task = parsed(client)
    before = task["source"]["sha256"]
    state = task["state"]
    state["resume"]["name"] = "用户更正名"
    result = client.patch(f"/api/diagnosis/tasks/{task['id']}", json={"expected_revision": task["revision"], "state": state})
    assert result.status_code == 200, result.text
    newer = result.json()
    assert newer["source"]["sha256"] == before
    field = next(x for x in newer["field_records"] if x["path"] == "name")
    assert field["original_value"] != field["current_value"] == "用户更正名"
    assert field["edited_by_user"] and field["value_origin"] == "user_corrected"
    assert client.patch(f"/api/diagnosis/tasks/{task['id']}", json={"expected_revision": task["revision"], "state": state}).status_code == 409


def test_adoption_and_completion_are_distinct_events(client):
    task = generated(client)
    sid = task["current_run"]["report"]["suggestions"][0]["id"]
    url = f"/api/diagnosis/tasks/{task['id']}/suggestions/{sid}"
    assert client.patch(url, json={"expected_revision": task["revision"], "action": "adopt", "text": "  "}).status_code == 422
    adopted = client.patch(url, json={"expected_revision": task["revision"], "action": "adopt", "text": "仅填写实际核实的修改"}).json()
    assert adopted["modifications"][sid]["status"] == "adopted"
    assert adopted["modifications"][sid]["completed_at"] is None
    done = client.patch(url, json={"expected_revision": adopted["revision"], "action": "complete", "text": "仅填写实际核实的修改"}).json()
    assert done["modifications"][sid]["status"] == "completed"
    assert done["modifications"][sid]["completed_at"]
    reopened = client.patch(url, json={"expected_revision": done["revision"], "action": "save", "text": "再次编辑的真实内容"}).json()
    assert reopened["modifications"][sid]["status"] == "adopted"
    assert reopened["modifications"][sid]["completed_at"] is None


def test_exports_frozen_report_and_history_after_change(client):
    task = generated(client)
    root = f"/api/diagnosis/tasks/{task['id']}"
    run_id = task["current_run"]["id"]
    assert client.get(root + "/export?kind=todo&format=txt").status_code == 422
    export = client.get(root + "/export?kind=report&format=txt")
    assert export.status_code == 200 and run_id in export.content.decode("utf-8-sig")
    state = task["state"]
    state["target"]["role"] = "数据分析师"
    changed = client.patch(root, json={"expected_revision": task["revision"], "state": state}).json()
    assert changed["current_run"]["stale"]
    assert client.get(root + "/export?kind=report&format=txt").status_code == 409
    assert client.get(root + f"/export?kind=report&format=txt&run_id={run_id}").status_code == 200
    history = client.get(root + "/history").json()
    assert history["runs"] and len(history["versions"]) >= 3
    restored = client.post(root + "/restore", json={"expected_revision": changed["revision"], "version_id": history["versions"][0]["version_id"]})
    assert restored.status_code == 200 and restored.json()["revision"] > changed["revision"]


def test_store_late_parse_stays_historical_and_conflicts_are_rejected(tmp_path):
    from app.diagnosis.workflow_store import TaskStore, WorkflowError
    store = TaskStore(tmp_path)
    task = store.create("owner", "文本", b"immutable source", "paste")
    snapshot = {"document_version_id": task["document_version_id"]}
    assert store.begin(task["id"], "owner", 1, "op1", "parse", snapshot)
    store.cancel(task["id"], "owner", "op1")
    result = store.finish_parse(task["id"], "owner", "op1", {"resume": {"name": "旧任务结果"}, "source_text": "old"})
    assert result["state"]["resume"] is None
    assert store.history(task["id"], "owner")["runs"][0]["status"] == "cancelled"
    state = result["state"]; state["target"]["role"] = "测试工程师"
    saved = store.save(task["id"], "owner", result["revision"], state)
    with pytest.raises(WorkflowError) as conflict:
        store.save(task["id"], "owner", result["revision"], state)
    assert conflict.value.status == 409
    assert store.original(task["id"], "owner")[1] == b"immutable source"
    assert store.get(task["id"], "owner")["revision"] == saved["revision"]


def test_store_source_edit_is_not_presented_as_original_evidence(tmp_path):
    from app.diagnosis.workflow_store import TaskStore
    store = TaskStore(tmp_path)
    task = store.create("owner", "文本", "原始名".encode(), "paste")
    store.begin(task["id"], "owner", 1, "parse", "parse", {})
    task = store.finish_parse(task["id"], "owner", "parse", {"resume": {"name": "原始名"}, "source_text": "原始名"})
    state = task["state"]; state["resume"]["name"] = "新增事实"
    task = store.save(task["id"], "owner", task["revision"], state)
    field = task["field_records"][0]
    assert field["original_value"] == "原始名" and field["edited_by_user"]
    assert field["anchor_status"] == "needs_review"
    assert field["source_anchor"]["start"] is None


def test_invalid_run_inputs_and_server_source_are_authoritative(client):
    task = ready(client)
    root = f"/api/diagnosis/tasks/{task['id']}"
    for update in ({"enabled_sections": []}, {"target": {"role": "", "company": "示例公司", "job_description": ""}},
                   {"review_confirmed": False}):
        state = {**task["state"], **update}
        task = client.patch(root, json={"expected_revision": task["revision"], "state": state}).json()
        assert client.post(root + "/run", json={"expected_revision": task["revision"], "operation_id": "bad"}).status_code == 422
    state = task["state"]
    state["resume"]["source_text"] = "不能覆盖原件"
    state["resume"]["source_sha256"] = "forged"
    saved = client.patch(root, json={"expected_revision": task["revision"], "state": state}).json()
    assert saved["state"]["resume"]["source_text"] == TEXT
    assert saved["state"]["resume"]["source_sha256"] == saved["source"]["sha256"]
    state = saved["state"]; state["api_key"] = "never-store-this"
    assert client.patch(root, json={"expected_revision": saved["revision"], "state": state}).status_code == 422


def test_partial_retry_keeps_siblings_and_old_report_immutable(client, monkeypatch):
    from app.diagnosis import engine
    original = engine.RUNNERS["potential"]
    def fail(*args):
        raise ValueError("injected failure")
    monkeypatch.setitem(engine.RUNNERS, "potential", fail)
    task = generated(client)
    old = task["current_run"]
    assert old["report"]["report_status"] == "partial"
    assert old["report"]["scope"]["failed"] == ["potential"]
    assert all("potential" not in x["source_modules"] for x in old["report"]["suggestions"])
    retained = next(item for item in old["report"]["suggestions"] if item["source_modules"] == ["match"])
    task = client.patch(f"/api/diagnosis/tasks/{task['id']}/suggestions/{retained['id']}",
                        json={"expected_revision": task["revision"], "action": "adopt", "text": "本人已核实的修改内容"}).json()
    monkeypatch.setitem(engine.RUNNERS, "potential", original)
    response = client.post(f"/api/diagnosis/tasks/{task['id']}/retry/potential",
                           json={"expected_revision": task["revision"], "operation_id": "retry-1"})
    assert response.status_code == 200, response.text
    new = response.json()["current_run"]
    assert new["report"]["report_status"] == "complete"
    assert new["modifications"][retained["id"]]["status"] == "adopted"
    assert response.json()["revision"] > task["revision"]
    assert client.patch(f"/api/diagnosis/tasks/{task['id']}/suggestions/{retained['id']}",
                        json={"expected_revision": task["revision"], "action": "complete"}).status_code == 409
    assert client.get(f"/api/diagnosis/tasks/{task['id']}/export?kind=todo").status_code == 200
    for name in ("match", "experience", "motivation", "verification"):
        assert new["report"]["dimensions"][name] == old["report"]["dimensions"][name]
    history = client.get(f"/api/diagnosis/tasks/{task['id']}/history").json()
    assert next(x for x in history["runs"] if x["id"] == old["id"])["report"]["report_status"] == "partial"


def test_all_failed_has_no_suggestions_or_export(client, monkeypatch):
    from app.diagnosis import engine
    def fail(*args):
        raise RuntimeError("injected, not user data")
    for name in engine.RUNNERS:
        monkeypatch.setitem(engine.RUNNERS, name, fail)
    task = generated(client)
    report = task["current_run"]["report"]
    assert report["report_status"] == "failed" and not report["suggestions"]
    assert not report["scope"]["can_generate_suggestions"]
    assert client.get(f"/api/diagnosis/tasks/{task['id']}/export").status_code == 422


def test_upload_checks_actual_format_and_size(client):
    for filename, data, status in (("resume.pdf", b"not a pdf", 422), ("resume.exe", b"MZ", 415),
                                   ("resume.docx", b"", 422), ("resume.png", b"x" * (10 * 1024 * 1024 + 1), 413)):
        result = client.post("/api/diagnosis/tasks/upload", files={"file": (filename, data)}, data={"privacy_consent": "true"})
        assert result.status_code == status, result.text
    assert client.get("/api/diagnosis/tasks").json() == []


def test_real_docx_retries_same_original_without_replacing_hash(client):
    from io import BytesIO
    from docx import Document
    document = Document()
    document.add_paragraph(TEXT)
    data = BytesIO(); document.save(data)
    task = client.post("/api/diagnosis/tasks/upload", files={"file": ("synthetic.docx", data.getvalue())}, data={"privacy_consent": "true"}).json()
    root = f"/api/diagnosis/tasks/{task['id']}"
    for operation in ("parse-1", "parse-2"):
        parsed = client.post(root + "/parse", json={"operation_id": operation})
        assert parsed.status_code == 200, parsed.text
        assert parsed.json()["source"]["sha256"] == task["source"]["sha256"]
        assert parsed.json()["source"]["text"].strip()
    assert client.get(root + "/source").content == data.getvalue()
    assert len(client.get(root + "/history").json()["runs"]) == 2


def test_cancelled_error_and_restart_cannot_leave_live_operations(tmp_path):
    from app.diagnosis.workflow_store import TaskStore
    store = TaskStore(tmp_path)
    task = store.create("owner", "text", b"example", "paste")
    store.begin(task["id"], "owner", 1, "op1", "parse", {})
    store.cancel(task["id"], "owner", "op1")
    store.fail(task["id"], "owner", "op1", "late failure")
    assert store.history(task["id"], "owner")["runs"][0]["status"] == "cancelled"
    store.begin(task["id"], "owner", 1, "op2", "parse", {})
    # Startup is the discriminating process boundary, not a new browser tab.
    store.recover_interrupted()
    resumed = store.get(task["id"], "owner")
    assert not resumed["active_operation"]
    assert resumed["status"] == "failed"


def test_late_run_and_navigation_save_do_not_mix_versions(tmp_path):
    from app.diagnosis.workflow_store import TaskStore
    store = TaskStore(tmp_path)
    task = store.create("owner", "text", b"original", "paste")
    store.begin(task["id"], "owner", 1, "op1", "diagnosis", {})
    state = task["state"]; state["step"] = 2
    task = store.save(task["id"], "owner", 1, state)
    assert task["active_operation"] == "op1"
    store.module(task["id"], "op1", "match", {"status": "ok"})
    store.cancel(task["id"], "owner", "op1")
    store.module(task["id"], "op1", "potential", {"status": "ok", "unaccepted": True})
    task = store.finish_run(task["id"], "owner", "op1", {"dimensions": {"potential": {"status": "ok"}}, "suggestions": [{"id": "late"}]})
    assert task["current_run"]["stale"]
    assert task["current_run"]["report"]["dimensions"] == {"match": {"status": "ok"}}
    assert not task["current_run"]["report"]["suggestions"]
    assert not task["current_run"]["report"]["scope"]["can_generate_suggestions"]


def test_ai_consent_and_credential_never_persist(client, monkeypatch):
    from app.diagnosis import workflow
    task = ready(client)
    root = f"/api/diagnosis/tasks/{task['id']}"
    call = {"expected_revision": task["revision"], "operation_id": "private-op", "use_ai": True,
            "api_key": "only-this-request-secret", "ai_consent": False}
    assert client.post(root + "/run", json=call).status_code == 422
    received = []
    monkeypatch.setattr(workflow, "add_ai_explanations", lambda report, **kwargs: received.append(kwargs))
    call["ai_consent"] = True
    assert client.post(root + "/run", json=call).status_code == 200
    assert received[0]["request_api_key"] == call["api_key"]
    assert call["api_key"] not in client.get(root).text + client.get(root + "/history").text


def test_http_late_parse_cannot_overwrite_saved_draft(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.diagnosis import workflow
    task = create(client)
    root = f"/api/diagnosis/tasks/{task['id']}"
    entered, release = Event(), Event()
    original = workflow.from_text
    def slow(text):
        entered.set()
        assert release.wait(10)
        return original(text)
    monkeypatch.setattr(workflow, "from_text", slow)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(client.post, root + "/parse", json={"operation_id": "slow-parse"})
        try:
            assert entered.wait(5)
            task = client.get(root).json()
            task["state"]["target"]["role"] = "新输入目标"
            changed = client.patch(root, json={"expected_revision": task["revision"], "state": task["state"]})
            assert changed.status_code == 200
        finally:
            release.set()
        assert pending.result().status_code == 200
    current = client.get(root).json()
    assert current["state"]["resume"] is None
    assert current["state"]["target"]["role"] == "新输入目标"
    assert client.get(root + "/history").json()["runs"][0]["status"] == "cancelled"


def test_http_late_report_keeps_new_target_and_refuses_current_export(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.diagnosis import workflow
    task = ready(client)
    root = f"/api/diagnosis/tasks/{task['id']}"
    entered, release = Event(), Event()
    original = workflow.run_diagnosis
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(workflow, "run_diagnosis", slow)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(client.post, root + "/run", json={"expected_revision": task["revision"], "operation_id": "slow-run"})
        try:
            assert entered.wait(5)
            task["state"]["target"]["role"] = "数据分析师"
            changed = client.patch(root, json={"expected_revision": task["revision"], "state": task["state"]})
            assert changed.status_code == 200
        finally:
            release.set()
        assert pending.result().status_code == 200
    current = client.get(root).json()
    assert current["state"]["target"]["role"] == "数据分析师"
    assert current["current_run"]["stale"]
    assert not current["current_run"]["report"]["suggestions"]
    assert client.get(root + "/export?kind=report&format=txt").status_code == 409


def test_cleared_field_keeps_original_and_current_empty_record(client):
    task = parsed(client)
    assert task["state"]["resume"]["name"]
    old = task["state"]["resume"]["name"]
    task["state"]["resume"]["name"] = ""
    changed = client.patch(f"/api/diagnosis/tasks/{task['id']}", json={"expected_revision": task["revision"], "state": task["state"]}).json()
    field = next(item for item in changed["field_records"] if item["path"] == "name")
    assert field["original_value"] == old and field["current_value"] == ""
    assert field["edited_by_user"] and field["anchor_status"] == "needs_review"


def test_key_fields_have_independent_confirmation_and_changed_field_is_reopened(client):
    task = ready(client)
    root = f"/api/diagnosis/tasks/{task['id']}"
    required = task["quality"]["critical_fields"]
    assert required and all(item["confirmed"] for item in required)
    path = "experience.0.company"
    state = task["state"]
    state["confirmed_fields"].remove(path)
    state["review_confirmed"] = True
    task = client.patch(root, json={"expected_revision": task["revision"], "state": state}).json()
    assert path in task["quality"]["missing_confirmation"]
    assert not task["state"]["review_confirmed"]
    assert client.post(root + "/run", json={"expected_revision": task["revision"], "operation_id": "unconfirmed"}).status_code == 422
    state = task["state"]
    state["confirmed_fields"].append(path); state["review_confirmed"] = True
    task = client.patch(root, json={"expected_revision": task["revision"], "state": state}).json()
    previously = set(task["state"]["confirmed_fields"])
    state = task["state"]; state["resume"]["experience"][0]["company"] = "用户核实的新公司"
    changed = client.patch(root, json={"expected_revision": task["revision"], "state": state}).json()
    assert set(changed["state"]["confirmed_fields"]) == previously - {path}
    assert changed["quality"]["missing_confirmation"] == [path]


def test_confirmed_field_can_be_cleared_or_removed_without_stale_confirmation_blocking_save(client):
    task = ready(client)
    root = f"/api/diagnosis/tasks/{task['id']}"
    state = task["state"]
    state["resume"]["name"] = ""
    state["resume"]["experience"] = []
    response = client.patch(root, json={"expected_revision": task["revision"], "state": state})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert "name" not in saved["state"]["confirmed_fields"]
    assert not any(path.startswith("experience.") for path in saved["state"]["confirmed_fields"])
    assert not saved["state"]["review_confirmed"]
