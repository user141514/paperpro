"""Synthetic field edits exercise real owned routes and real runner calls."""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import json
from random import Random
from uuid import uuid4

import pytest
from app.diagnosis import engine
from app.diagnosis.schema import CandidateResume, Target
from test_candidate_workflow import client, ready

MODULES = tuple(engine.RUNNERS)


def assert_fresh_equivalent(task):
    state = task["state"]
    report = task["current_run"]["report"]
    fresh = engine.run_diagnosis(CandidateResume.model_validate(state["resume"]), Target.model_validate(state["target"]),
        enabled_sections=state["enabled_sections"], requirements=state["requirements"], as_of=state["as_of"])
    for name in MODULES:
        actual = {k: v for k, v in report["dimensions"][name].items() if k != "version_info"}
        reference = {k: v for k, v in fresh["dimensions"][name].items() if k != "version_info"}
        assert actual == reference, name
    for name in ("suggestions", "interview_questions", "scope", "target", "requirements"):
        assert report[name] == fresh[name], name
    for name in ("input_snapshot_sha256", "reviewed_draft_sha256"):
        assert report["meta"][name] == fresh["meta"][name], name


def run(client, task, module=None):
    suffix = "/retry/" + module if module else "/run"
    response = client.post(f"/api/diagnosis/tasks/{task['id']}" + suffix,
                           json={"expected_revision": task["revision"], "operation_id": str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()


def edit(client, task, mutate):
    state = deepcopy(task["state"])
    mutate(state)
    url = f"/api/diagnosis/tasks/{task['id']}"
    response = client.patch(url, json={"expected_revision": task["revision"], "state": state})
    assert response.status_code == 200, response.text
    saved = response.json()
    saved["state"].update(review_confirmed=True, requirements_confirmed=True,
        confirmed_fields=[item["path"] for item in saved["quality"]["critical_fields"]])
    response = client.patch(url, json={"expected_revision": saved["revision"], "state": saved["state"]})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def calls(monkeypatch):
    counted = Counter()
    for name, runner in list(engine.RUNNERS.items()):
        def wrapper(*args, _name=name, _runner=runner, **kwargs):
            counted[_name] += 1
            return _runner(*args, **kwargs)
        monkeypatch.setitem(engine.RUNNERS, name, wrapper)
    return counted


def summary(state):
    state["resume"]["summary"] = "基于本人真实经历补充 Python 接口开发的职责说明。"


def duties(state):
    state["resume"]["experience"][0]["bullets"][0] += "，并交付接口运行说明。"


def dates(state):
    state["resume"]["experience"][0]["start_date"] = "2020-01"


def weights(state):
    active = [item for item in state["requirements"] if item["enabled"]]
    active[0]["weight"] += 1
    active[1]["weight"] -= 1


@pytest.mark.parametrize("mutate,expected", [
    (summary, {"match", "motivation", "verification"}),
    (duties, {"match", "potential", "motivation", "verification"}),
    (dates, {"match", "experience", "verification"}),
    (weights, {"match"}),
    (lambda s: s["target"].update(company="合成目标企业"), {"motivation"}),
    (lambda s: s["target"].update(role="数据工程师"), {"match", "motivation"}),
    (lambda s: s.update(as_of="2026-09-30"), {"match", "experience", "verification"}),
    (lambda s: s["resume"].update(phone="13800000000"), set()),
])
def test_only_affected_runners_execute_and_fresh_reference_agrees(client, calls, mutate, expected):
    original = run(client, ready(client))
    assert set(calls) == set(MODULES)
    calls.clear()
    changed = edit(client, original, mutate)
    plan = changed["current_run"]["recompute"]
    assert set(plan["recomputed"]) == expected
    assert set(plan["reused"]) == set(MODULES) - expected
    assert changed["current_run"]["stale"]
    updated = run(client, changed)
    assert calls == Counter({key: 1 for key in expected})
    report = updated["current_run"]["report"]
    assert set(report["meta"]["recompute"]["recomputed"]) == expected
    assert set(report["meta"]["recompute"]["reused"]) == set(MODULES) - expected
    assert report["meta"]["recompute"]["source_run_id"] == original["current_run"]["id"]
    assert_fresh_equivalent(updated)
    for name in MODULES:
        provenance = report["meta"]["module_provenance"][name]
        assert provenance["mode"] == ("computed" if name in expected else "reused")
        assert provenance["validated_revision"] == changed["revision"]


def test_module_disable_enable_does_not_recompute_siblings(client, calls):
    original = run(client, ready(client))
    calls.clear()
    disabled = edit(client, original, lambda s: s.update(enabled_sections=[x for x in MODULES if x != "potential"]))
    disabled = run(client, disabled)
    assert not calls
    assert disabled["current_run"]["report"]["dimensions"]["potential"]["status"] == "disabled"
    enabled = edit(client, disabled, lambda s: s.update(enabled_sections=list(MODULES)))
    enabled = run(client, enabled)
    assert calls == Counter({"potential": 1})
    assert set(enabled["current_run"]["report"]["meta"]["recompute"]["reused"]) == set(MODULES) - {"potential"}


def test_seeded_100_edit_sequence_matches_full_calculation(client, calls):
    """100 owned HTTP rechecks, with independent expected runner sets and fresh oracles."""
    task = run(client, ready(client))
    sequence = list(range(8)) * 12 + list(range(4))
    Random(1019).shuffle(sequence)
    expected_sets = [
        {"match", "motivation", "verification"},
        {"match", "potential", "motivation", "verification"},
        {"match", "experience", "verification"}, {"match"}, {"motivation"},
        {"match", "motivation"}, {"match", "experience", "verification"}, set(),
    ]
    total_executed = 0
    for index, kind in enumerate(sequence, 1):
        def mutate(state):
            if kind == 0:
                state["resume"]["summary"] = f"第{index}次模拟：根据真实职责补充 Python 数据接口经验。"
            elif kind == 1:
                state["resume"]["experience"][0]["bullets"][0] = f"负责 Python 接口、SQL 查询与报表维护；第{index}次模拟核对交付范围。"
            elif kind == 2:
                state["resume"]["experience"][0]["start_date"] = f"{2010 + index // 12}-{index % 12 + 1:02d}"
            elif kind == 3:
                active = [item for item in state["requirements"] if item["enabled"]]
                delta = 1 if active[1]["weight"] > 1 else -1
                active[0]["weight"] += delta
                active[1]["weight"] -= delta
            elif kind == 4:
                state["target"]["company"] = f"合成企业{index}"
            elif kind == 5:
                state["target"]["role"] = f"Python数据工程师{index}"
            elif kind == 6:
                state["as_of"] = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
            else:
                state["resume"]["phone"] = str(13800000000 + index)
        calls.clear()
        old_run = task["current_run"]["id"]
        changed = edit(client, task, mutate)
        expected = expected_sets[kind]
        assert set(changed["current_run"]["recompute"]["recomputed"]) == expected, (index, kind)
        task = run(client, changed)
        assert calls == Counter({name: 1 for name in expected}), (index, kind, calls)
        total_executed += sum(calls.values())
        meta = task["current_run"]["report"]["meta"]
        assert set(meta["recompute"]["recomputed"]) == expected
        assert meta["recompute"]["source_run_id"] == old_run
        assert not task["current_run"]["stale"]
        assert_fresh_equivalent(task)
    assert total_executed == sum(len(expected_sets[kind]) for kind in sequence)
    assert total_executed < 500


def complete(client, task, suggestion):
    url = f"/api/diagnosis/tasks/{task['id']}/suggestions/{suggestion['id']}"
    for action in ("adopt", "complete"):
        result = client.patch(url, json={"expected_revision": task["revision"], "action": action, "text": "已根据真实经历核实并修改"})
        assert result.status_code == 200, result.text
        task = result.json()
    return task


def test_only_affected_todos_reopen_and_history_stays_immutable(client):
    task = run(client, ready(client))
    report = task["current_run"]["report"]
    potential = next(item for item in report["suggestions"] if item["source_modules"] == ["potential"])
    match = next(item for item in report["suggestions"] if item["source_modules"] == ["match"])
    task = complete(client, complete(client, task, potential), match)
    old_run = task["current_run"]["id"]
    saved_potential = deepcopy(task["modifications"][potential["id"]])
    changed = edit(client, task, weights)
    assert changed["modifications"][potential["id"]] == saved_potential
    assert changed["modifications"][match["id"]]["status"] == "needs_confirmation"
    updated = run(client, changed)
    assert updated["modifications"][potential["id"]] == saved_potential
    reset = updated["modifications"][match["id"]]
    assert reset["status"] == "needs_confirmation" and reset["text"]
    assert reset["adopted_at"] is None and reset["completed_at"] is None
    assert len({item["id"] for item in updated["current_run"]["report"]["suggestions"]}) == len(updated["current_run"]["report"]["suggestions"])
    historical = next(item for item in client.get(f"/api/diagnosis/tasks/{task['id']}/history").json()["runs"] if item["id"] == old_run)
    assert historical["modifications"][match["id"]]["status"] == "completed"
    assert historical["modifications"][potential["id"]] == saved_potential


def alter_run(task, mutate):
    """Inject legacy/corrupt stored evidence into this test's isolated database."""
    from app.diagnosis.workflow import store
    with store().connect() as db:
        row = db.execute("SELECT snapshot,report FROM operations WHERE id=?", (task["current_run"]["id"],)).fetchone()
        snapshot, report = json.loads(row[0]), json.loads(row[1])
        mutate(snapshot, report)
        db.execute("UPDATE operations SET snapshot=?,report=? WHERE id=?", (json.dumps(snapshot), json.dumps(report), task["current_run"]["id"]))
        db.commit()


def test_legacy_without_saved_fingerprints_recomputes_once(client, calls):
    task = run(client, ready(client))
    alter_run(task, lambda snapshot, report: snapshot.pop("module_fingerprints"))
    current = client.get(f"/api/diagnosis/tasks/{task['id']}").json()
    assert current["current_run"]["stale"]
    assert set(current["current_run"]["recompute"]["recomputed"]) == set(MODULES)
    calls.clear()
    task = run(client, current)
    assert calls == Counter({name: 1 for name in MODULES})
    calls.clear()
    task = run(client, task)
    assert not calls
    assert set(task["current_run"]["report"]["meta"]["recompute"]["reused"]) == set(MODULES)


def test_invalid_cached_evidence_falls_back_to_one_real_runner(client, calls):
    task = run(client, ready(client))
    def corrupt(snapshot, report):
        report["dimensions"]["potential"]["supporting_signals"][0]["original"] = "不存在于当前简历的证据"
    alter_run(task, corrupt)
    calls.clear()
    task = run(client, task)
    assert calls == Counter({"potential": 1})
    assert task["current_run"]["report"]["meta"]["module_provenance"]["potential"]["mode"] == "computed"
    assert_fresh_equivalent(task)


def test_same_version_rule_content_change_invalidates_mutation_and_all_modules(client, calls, tmp_path, monkeypatch):
    from app.diagnosis import scoring
    task = run(client, ready(client))
    suggestion = task["current_run"]["report"]["suggestions"][0]
    old_version = scoring.load_rules()["version"]
    rules = scoring.load_rules()
    rules["date_policy"]["short_stint_months"] = 60
    rule_path = tmp_path / "changed-rules.json"
    rule_path.write_text(json.dumps(rules), encoding="utf-8")
    monkeypatch.setattr(scoring, "RULES_PATH", rule_path)
    url = f"/api/diagnosis/tasks/{task['id']}"
    current = client.get(url).json()
    assert current["current_run"]["stale"]
    assert client.get(url + "/export?kind=report&format=txt").status_code == 409
    assert client.patch(url + "/suggestions/" + suggestion["id"], json={"expected_revision": task["revision"], "action": "adopt", "text": "真实核实"}).status_code == 409
    calls.clear()
    task = run(client, current)
    assert calls == Counter({name: 1 for name in MODULES})
    assert task["current_run"]["report"]["meta"]["rules_version"] == old_version
    assert_fresh_equivalent(task)


def test_partial_normal_recheck_and_explicit_retry_only_execute_requested_work(client, calls, monkeypatch):
    original_potential = engine.RUNNERS["potential"]
    original_verification = engine.RUNNERS["verification"]
    def fail_potential(*args, **kwargs):
        calls["potential"] += 1
        raise ValueError("synthetic potential failure")
    def fail_verification(*args, **kwargs):
        calls["verification"] += 1
        raise ValueError("synthetic verification failure")
    monkeypatch.setitem(engine.RUNNERS, "potential", fail_potential)
    monkeypatch.setitem(engine.RUNNERS, "verification", fail_verification)
    task = run(client, ready(client))
    assert task["current_run"]["report"]["report_status"] == "partial"
    calls.clear()
    monkeypatch.setitem(engine.RUNNERS, "potential", original_potential)
    task = run(client, task, "potential")
    assert calls == Counter({"potential": 1})
    assert task["current_run"]["report"]["dimensions"]["verification"]["status"] == "error"
    calls.clear()
    monkeypatch.setitem(engine.RUNNERS, "verification", original_verification)
    task = run(client, task)
    assert calls == Counter({"verification": 1})
    assert task["current_run"]["report"]["report_status"] == "complete"


def test_restore_rechecks_actual_difference_not_all_modules(client, calls):
    original = run(client, ready(client))
    root = f"/api/diagnosis/tasks/{original['id']}"
    changed = run(client, edit(client, original, weights))
    restored = client.post(root + "/restore", json={"expected_revision": changed["revision"], "version_id": original["revision"]})
    assert restored.status_code == 200, restored.text
    ready_again = edit(client, restored.json(), lambda s: None)
    calls.clear()
    updated = run(client, ready_again)
    assert calls == Counter({"match": 1})
    assert updated["source"]["sha256"] == original["source"]["sha256"]
    assert_fresh_equivalent(updated)


def test_reused_export_uses_current_snapshot_and_labels_original_compute_date(client):
    original = run(client, ready(client))
    root = f"/api/diagnosis/tasks/{original['id']}"
    changed = edit(client, original, lambda state: state.update(as_of="2026-09-30"))
    assert client.get(root + "/export?kind=report&format=txt").status_code == 409
    old = client.get(root + f"/export?kind=report&format=txt&run_id={original['current_run']['id']}")
    assert old.status_code == 200
    updated = run(client, changed)
    exported = client.get(root + "/export?kind=report&format=txt")
    assert exported.status_code == 200
    text = exported.content.decode("utf-8-sig")
    assert "计算基准日：2026-09-30" in text
    assert "本次重算：岗位匹配、经历与时间、面试核查" in text
    assert "本次复用：发展潜力、求职针对性" in text
    assert "原计算基准日：" + original["state"]["as_of"] in text
    assert "本次核对基准日：2026-09-30" in text
    assert "原计算报告：" + original["current_run"]["id"] in text
    assert "报告 ID：" + updated["current_run"]["id"] in text
    again = client.get(root + f"/export?kind=report&format=txt&run_id={original['current_run']['id']}")
    assert again.content.decode("utf-8-sig").split("\n导出时间：")[0] == old.content.decode("utf-8-sig").split("\n导出时间：")[0]


def test_late_selective_run_cannot_publish_over_a_new_edit(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    original = run(client, ready(client))
    changed = edit(client, original, weights)
    root = f"/api/diagnosis/tasks/{original['id']}"
    entered, release = Event(), Event()
    runner = engine.RUNNERS["match"]
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return runner(*args, **kwargs)
    monkeypatch.setitem(engine.RUNNERS, "match", slow)
    operation = "synthetic-delayed-selective"
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(client.post, root + "/run", json={"expected_revision": changed["revision"], "operation_id": operation})
        try:
            assert entered.wait(5)
            newer = edit(client, client.get(root).json(), lambda state: state["target"].update(role="数据分析师"))
            assert newer["state"]["target"]["role"] == "数据分析师"
        finally:
            release.set()
        assert pending.result().status_code == 200
    current = client.get(root).json()
    assert current["state"]["target"]["role"] == "数据分析师"
    assert current["current_run"]["status"] == "cancelled"
    assert current["current_run"]["report"]["suggestions"] == []
    assert current["current_run"]["stale"]
    assert client.get(root + "/export?kind=report&format=txt").status_code == 409
    history = client.get(root + "/history").json()
    old = next(item for item in history["runs"] if item["id"] == original["current_run"]["id"])
    assert old["report"] == original["current_run"]["report"]


def test_rules_changing_during_selective_work_are_not_published(client, monkeypatch, tmp_path):
    from app.diagnosis import scoring
    original = run(client, ready(client))
    changed = edit(client, original, weights)
    rules = scoring.load_rules()
    rule_path = tmp_path / "changed-mid-run.json"
    rule_path.write_text(json.dumps(rules), encoding="utf-8")
    monkeypatch.setattr(scoring, "RULES_PATH", rule_path)
    runner = engine.RUNNERS["match"]
    def change_rules(*args, **kwargs):
        result = runner(*args, **kwargs)
        rules["date_policy"]["short_stint_months"] = 60
        rule_path.write_text(json.dumps(rules), encoding="utf-8")
        return result
    monkeypatch.setitem(engine.RUNNERS, "match", change_rules)
    root = f"/api/diagnosis/tasks/{changed['id']}"
    result = client.post(root + "/run", json={"expected_revision": changed["revision"], "operation_id": "rules-changed-mid-work"})
    assert result.status_code == 422
    current = client.get(root).json()
    assert current["current_run"]["status"] == "failed"
    assert not current["current_run"]["report"]
    assert not current["active_operation"]
    assert client.get(root + "/export?kind=report&format=txt").status_code == 422


def test_transient_rules_aba_cannot_change_an_operations_frozen_results(client, monkeypatch, tmp_path):
    """Even a same-version rule change restored before publication cannot mix calculations."""
    from app.diagnosis import scoring
    prepared = ready(client)
    def two_jobs(state):
        work = deepcopy(state["resume"]["experience"][0])
        work.update(start_date="2024-01", end_date="2024-02", heading="示例科技 Python工程师")
        other = deepcopy(work)
        other.update(start_date="2024-04", end_date="2024-05", company="示例数据公司", heading="示例数据公司 Python工程师")
        state["resume"]["experience"] = [work, other]
    prepared = edit(client, prepared, two_jobs)
    rules = scoring.load_rules()
    rule_path = tmp_path / "transient-rules.json"
    original_json = json.dumps(rules)
    rule_path.write_text(original_json, encoding="utf-8")
    monkeypatch.setattr(scoring, "RULES_PATH", rule_path)
    runner = engine.RUNNERS["experience"]
    def temporarily_change_rules(*args, **kwargs):
        changed = deepcopy(rules)
        changed["date_policy"]["gap_notice_days"] = 1
        rule_path.write_text(json.dumps(changed), encoding="utf-8")
        try:
            return runner(*args, **kwargs)
        finally:
            rule_path.write_text(original_json, encoding="utf-8")
    monkeypatch.setitem(engine.RUNNERS, "experience", temporarily_change_rules)
    task = run(client, prepared)
    assert task["current_run"]["report"]["dimensions"]["experience"]["gaps"] == []
    monkeypatch.setitem(engine.RUNNERS, "experience", runner)
    assert_fresh_equivalent(task)


def test_frozen_rules_are_thread_local_and_release_after_errors():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.diagnosis.scoring import frozen_rules, load_rules
    original = load_rules()
    barrier = Barrier(2)
    def worker(threshold):
        configured = deepcopy(original)
        configured["date_policy"]["gap_notice_days"] = threshold
        with frozen_rules(configured):
            barrier.wait(timeout=5)
            assert load_rules()["date_policy"]["gap_notice_days"] == threshold
            configured["date_policy"]["gap_notice_days"] = -1
            assert load_rules()["date_policy"]["gap_notice_days"] == threshold
        assert load_rules() == original
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, (1, 999)))
    with pytest.raises(ValueError):
        with frozen_rules({**original, "version": "test-only-frozen"}):
            raise ValueError("synthetic error")
    assert load_rules() == original
