"""Private candidate task revisions. SQLite is the only acceptance authority."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .dependencies import module_fingerprints, recompute_plan


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class WorkflowError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def input_key(state):
    return encoded({k: state.get(k) for k in ("resume", "target", "requirements", "enabled_sections", "as_of")})


def path_value(value, path):
    try:
        for key in path.split("."):
            value = value[int(key)] if isinstance(value, list) else value[key]
        return value
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def flattened(value, path="", include_blank=False):
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in {"source_text", "source_sha256"}:
                yield from flattened(item, f"{path}.{key}".strip("."), include_blank)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from flattened(item, f"{path}.{index}", include_blank)
    elif isinstance(value, str) and (include_blank or value.strip()):
        yield path, value


def field_records(source, original, current):
    text = source.get("text", "")
    initial = dict(flattened(original or {}))
    present = dict(flattened(current or {}, include_blank=True))
    result = []
    structural_change = any(len((original or {}).get(k, [])) != len((current or {}).get(k, []))
                            for k in ("experience", "education", "projects"))
    for path in dict.fromkeys([key for key, value in present.items() if value.strip()] + list(initial)):
        value = present.get(path, "")
        old = initial.get(path, "")
        unique = bool(old) and text.count(old) == 1
        start = text.find(old) if unique else -1
        changed = value != old
        anchor_status = "valid" if unique and not changed else "needs_review"
        if structural_change and path.split(".")[0] in {"experience", "education", "projects"}:
            anchor_status = "needs_review"
        result.append({"path": path, "original_value": old, "current_value": value,
            "value_origin": "user_added" if not old else "user_corrected" if changed else "parsed",
            "edited_by_user": changed, "anchor_status": anchor_status,
            "source_anchor": {"document_version_id": source["document_version_id"], "excerpt": old,
                "paragraph_id": text[:start].count("\n") + 1 if start >= 0 else None,
                "start": start if anchor_status == "valid" else None,
                "end": start + len(old) if anchor_status == "valid" else None}})
    return result


def critical_values(resume):
    """Review scored facts; absent optional contact details do not block a user."""
    result = {path: value for path, value in flattened(resume or {})
              if path.split(".")[0] not in {"phone", "email", "location", "links"}}
    for index, entry in enumerate((resume or {}).get("experience", [])):
        for name in ("company", "role", "start_date", "end_date"):
            result[f"experience.{index}.{name}"] = entry.get(name, "")
    return result


def quality(state):
    from .quality import review_quality
    from .schema import CandidateResume
    result = review_quality(CandidateResume.model_validate(state["resume"]) if state.get("resume") else None)
    confirmed = set(state.get("confirmed_fields", []))
    required = critical_values(state.get("resume"))
    return {**result, "version": "candidate-quality-v3-1", "analysable": not result["blockers"],
            "critical_fields": [{"path": path, "current_value": value, "confirmed": path in confirmed} for path, value in required.items()],
            "missing_confirmation": [path for path in required if path not in confirmed]}


class TaskStore:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "candidate-tasks.sqlite3"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, document_id TEXT NOT NULL,
              source TEXT NOT NULL, original BLOB NOT NULL, original_resume TEXT,
              state TEXT NOT NULL, revision INTEGER NOT NULL, input_revision INTEGER NOT NULL,
              status TEXT NOT NULL, active_operation TEXT, current_run TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS versions (
              task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
              revision INTEGER NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(task_id,revision));
            CREATE TABLE IF NOT EXISTS operations (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
              kind TEXT NOT NULL, input_revision INTEGER NOT NULL, revision INTEGER NOT NULL,
              status TEXT NOT NULL, snapshot TEXT NOT NULL, modules TEXT NOT NULL DEFAULT '{}',
              report TEXT, modifications TEXT NOT NULL DEFAULT '{}', error TEXT,
              created_at TEXT NOT NULL, finished_at TEXT);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
              run_id TEXT, suggestion_id TEXT, action TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS exports (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
              run_id TEXT NOT NULL, kind TEXT NOT NULL, format TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def write(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def owned(self, db, task_id, owner):
        task = db.execute("SELECT * FROM tasks WHERE id=? AND owner=?", (task_id, owner)).fetchone()
        if task is None:
            raise WorkflowError(404, "任务不存在或无访问权限")
        return task

    def expected(self, task, revision):
        if task["revision"] != revision:
            raise WorkflowError(409, "已有较新保存版本；当前编辑已保留，请核对差异后重新保存")

    def event(self, db, task_id, action, payload, run_id=None, suggestion_id=None):
        db.execute("INSERT INTO events(task_id,run_id,suggestion_id,action,payload,created_at) VALUES(?,?,?,?,?,?)",
                   (task_id, run_id, suggestion_id, action, encoded(payload), stamp()))

    def create(self, owner, filename, original, input_type):
        identity, document = str(uuid4()), str(uuid4())
        now = stamp()
        source = dict(filename=filename, text="", method="pending", input_type=input_type,
                      sha256=sha256(original).hexdigest(), document_version_id=document,
                      warnings=[], review_hints=[])
        state = dict(resume=None, target={"role": "", "company": "", "job_description": ""},
                     requirements=[], enabled_sections=["match", "experience", "potential", "motivation", "verification"],
                     as_of=now[:10], review_confirmed=False, confirmed_fields=[], requirements_confirmed=False, step=0)
        with self.write() as db:
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,1,1,'unparsed',NULL,NULL,?,?)",
                (identity, owner, document, encoded(source), original, None, encoded(state), now, now))
            db.execute("INSERT INTO versions VALUES(?,1,?,?,?)", (identity, encoded(state), "创建并授权解析", now))
            self.event(db, identity, "consent", {"purpose": "本人主动发起的解析、诊断与导出", "accepted": True})
        return self.get(identity, owner)

    def envelope(self, db, task):
        state, source = json.loads(task["state"]), json.loads(task["source"])
        run = db.execute("SELECT * FROM operations WHERE id=? AND kind!='parse'", (task["current_run"],)).fetchone()
        current = self.run_view(run, task) if run else None
        modifications = current["modifications"] if current else {}
        review = quality(state)
        review["warnings"].extend({"path": "source", "message": str(message)} for message in source.get("warnings", []))
        return {"id": task["id"], "document_version_id": task["document_id"], "revision": task["revision"],
                "status": task["status"], "active_operation": task["active_operation"], "state": state,
                "source": source, "field_records": field_records(source, json.loads(task["original_resume"] or "null"), state.get("resume")),
                "quality": review, "current_run": current, "modifications": modifications,
                "updated_at": task["updated_at"]}

    def run_view(self, run, task=None):
        snapshot, report = json.loads(run["snapshot"]), json.loads(run["report"] or "null")
        state = json.loads(task["state"]) if task is not None else snapshot
        inputs = {**state, "document_version_id": task["document_id"] if task is not None else snapshot.get("document_version_id", "")}
        plan = recompute_plan(snapshot, inputs, (report or {}).get("dimensions", {}))
        if run["status"] == "running" and snapshot.get("recompute"):
            plan = snapshot["recompute"]
        fingerprints = module_fingerprints(inputs)
        changed_modules = {name for name in state.get("enabled_sections", [])
                           if snapshot.get("module_fingerprints", {}).get(name) != fingerprints[name]}
        changed_modules.update(set(snapshot.get("enabled_sections", [])) - set(state.get("enabled_sections", [])))
        stale = task is not None and (run["input_revision"] != task["input_revision"] or run["status"] == "cancelled" or bool(changed_modules))
        modifications = json.loads(run["modifications"])
        if stale:
            suggestions = {item["id"]: item for item in (report or {}).get("suggestions", [])}
            for key, value in modifications.items():
                suggestion = suggestions.get(key, {})
                changed_source = any(path_value(snapshot.get("resume"), suggestion[path]) != path_value(state.get("resume"), suggestion[path])
                                     for path in ("location", "related_location") if suggestion.get(path))
                if (not suggestion.get("source_modules") or changed_modules.intersection(suggestion["source_modules"])
                        or changed_source or run["status"] == "cancelled"):
                    modifications[key] = {**value, "status": "needs_confirmation"}
        return {"id": run["id"], "operation_id": run["id"], "status": run["status"], "revision": run["revision"],
                "snapshot": snapshot, "report": report,
                "module_status": json.loads(run["modules"]), "stale": stale, "modifications": modifications,
                "recompute": plan, "affected_modules": plan["recomputed"],
                "created_at": run["created_at"], "finished_at": run["finished_at"], "error": run["error"]}

    def get(self, task_id, owner):
        with self.connect() as db:
            return self.envelope(db, self.owned(db, task_id, owner))

    def original(self, task_id, owner):
        with self.connect() as db:
            task = self.owned(db, task_id, owner)
            return json.loads(task["source"]), bytes(task["original"])

    def listing(self, owner):
        with self.connect() as db:
            return [{"id": row["id"], "revision": row["revision"], "status": row["status"],
                     "filename": json.loads(row["source"])["filename"],
                     "role": json.loads(row["state"]).get("target", {}).get("role", ""), "updated_at": row["updated_at"]}
                    for row in db.execute("SELECT * FROM tasks WHERE owner=? ORDER BY updated_at DESC", (owner,))]

    def save(self, task_id, owner, revision, state, reason="用户保存", force=False):
        with self.write() as db:
            task = self.owned(db, task_id, owner)
            self.expected(task, revision)
            previous = json.loads(task["state"])
            before, after = critical_values(previous.get("resume")), critical_values(state.get("resume"))
            requested = state.get("confirmed_fields", [])
            structural = {key for key in ("experience", "education", "projects", "skills", "certificates", "additional")
                          if len((previous.get("resume") or {}).get(key, [])) != len((state.get("resume") or {}).get(key, []))}
            state["confirmed_fields"] = [path for path in requested if path in after and path in before
                and before[path] == after[path] and path.split(".")[0] not in structural]
            if set(after) - set(state["confirmed_fields"]):
                state["review_confirmed"] = False
            changed = force or input_key(previous) != input_key(state)
            if changed:
                if previous.get("resume") != state.get("resume"):
                    state["review_confirmed"] = False
                if any(previous.get(k) != state.get(k) for k in ("target", "requirements")):
                    state["requirements_confirmed"] = False
            now = stamp()
            if changed and task["active_operation"]:
                db.execute("UPDATE operations SET status='cancelled',finished_at=? WHERE id=?", (now, task["active_operation"]))
            db.execute("UPDATE tasks SET state=?,revision=revision+1,input_revision=input_revision+?,status=?,active_operation=?,updated_at=? WHERE id=?",
                       (encoded(state), int(changed), ("review" if state.get("resume") else "unparsed") if changed else task["status"],
                        None if changed else task["active_operation"], now, task_id))
            db.execute("INSERT INTO versions VALUES(?,?,?,?,?)", (task_id, revision + 1, encoded(state), reason, now))
            self.event(db, task_id, "save", {"revision": revision + 1, "reason": reason})
            if set(previous.get("confirmed_fields", [])) != set(state["confirmed_fields"]):
                self.event(db, task_id, "confirm_fields", {"paths": state["confirmed_fields"], "revision": revision + 1})
        return self.get(task_id, owner)

    def begin(self, task_id, owner, revision, operation, kind, snapshot):
        with self.write() as db:
            task = self.owned(db, task_id, owner)
            self.expected(task, revision)
            prior = db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
            if prior:
                if prior["task_id"] != task_id or prior["snapshot"] != encoded(snapshot) or prior["kind"] != kind:
                    raise WorkflowError(409, "操作 ID 已用于另一份输入")
                return False
            if task["active_operation"]:
                raise WorkflowError(409, "当前任务仍在处理，可先取消再重试")
            db.execute("INSERT INTO operations(id,task_id,kind,input_revision,revision,status,snapshot,created_at) VALUES(?,?,?,?,?,'running',?,?)",
                       (operation, task_id, kind, task["input_revision"], revision, encoded(snapshot), stamp()))
            db.execute("UPDATE tasks SET active_operation=?,status=?,current_run=CASE WHEN ?='parse' THEN current_run ELSE ? END,updated_at=? WHERE id=?",
                       (operation, "parsing" if kind == "parse" else "running", kind, operation, stamp(), task_id))
        return True

    def active(self, task_id, owner, operation):
        with self.connect() as db:
            row = db.execute("SELECT active_operation FROM tasks WHERE id=? AND owner=?", (task_id, owner)).fetchone()
            return bool(row and row[0] == operation)

    def module(self, task_id, operation, name, result):
        with self.write() as db:
            op = db.execute("SELECT modules FROM operations WHERE id=? AND task_id=?", (operation, task_id)).fetchone()
            task = db.execute("SELECT active_operation FROM tasks WHERE id=?", (task_id,)).fetchone()
            if op and task and task[0] == operation:
                modules = json.loads(op[0]); modules[name] = result
                db.execute("UPDATE operations SET modules=? WHERE id=?", (encoded(modules), operation))

    def finish_parse(self, task_id, owner, operation, parsed):
        with self.write() as db:
            task = self.owned(db, task_id, owner)
            accepted = task["active_operation"] == operation
            db.execute("UPDATE operations SET status=?,report=?,finished_at=? WHERE id=? AND task_id=?",
                       ("completed" if accepted else "cancelled", encoded(parsed), stamp(), operation, task_id))
            if accepted:
                state, source = json.loads(task["state"]), json.loads(task["source"])
                state.update(resume=parsed["resume"], review_confirmed=False, confirmed_fields=[], requirements_confirmed=False, step=1)
                source.update(text=parsed.get("source_text", ""), method=parsed.get("method", "parsed"),
                              warnings=parsed.get("warnings", []), review_hints=parsed.get("review_hints", []))
                now = stamp()
                db.execute("UPDATE tasks SET state=?,source=?,original_resume=COALESCE(original_resume,?),revision=revision+1,input_revision=input_revision+1,status='review',active_operation=NULL,updated_at=? WHERE id=?",
                           (encoded(state), encoded(source), encoded(parsed["resume"]), now, task_id))
                db.execute("INSERT INTO versions VALUES(?,?,?,?,?)", (task_id, task["revision"] + 1, encoded(state), "解析完成", now))
        return self.get(task_id, owner)

    def finish_run(self, task_id, owner, operation, report, modifications=None):
        with self.write() as db:
            task = self.owned(db, task_id, owner)
            accepted = task["active_operation"] == operation
            status = report.get("report_status", "complete") if accepted else "cancelled"
            if not accepted:
                saved = db.execute("SELECT modules,snapshot FROM operations WHERE id=? AND task_id=?", (operation, task_id)).fetchone()
                sections = json.loads(saved[0]) if saved else {}
                enabled = json.loads(saved[1]).get("enabled_sections", []) if saved else []
                completed = [name for name, section in sections.items() if section.get("status") == "ok"]
                failed = [name for name, section in sections.items() if section.get("status") == "error"]
                cancelled = [name for name in enabled if name not in completed + failed]
                for name in cancelled:
                    sections[name] = {"status": "cancelled", "conclusion": "已取消，未发布后续处理结果"}
                scope = {"status": "cancelled", "enabled": enabled, "completed": completed, "failed": failed,
                         "cancelled": cancelled, "pending": [],
                         "disabled": [name for name, section in sections.items() if section.get("status") == "disabled"],
                         "can_generate_suggestions": False}
                report = {**report, "dimensions": sections, "scope": scope, "can_generate_suggestions": False,
                          "suggestions": [], "interview_questions": [], "report_status": "cancelled"}
            db.execute("UPDATE operations SET status=?,report=?,modules=?,finished_at=? WHERE id=? AND task_id=?",
                       (status, encoded(report), encoded(report.get("dimensions", {})), stamp(), operation, task_id))
            if accepted:
                state = json.loads(task["state"]); state["step"] = 3
                now = stamp()
                if modifications is not None:
                    db.execute("UPDATE operations SET modifications=? WHERE id=?", (encoded(modifications), operation))
                db.execute("UPDATE tasks SET active_operation=NULL,status=?,state=?,revision=revision+1,updated_at=? WHERE id=?",
                           (status, encoded(state), now, task_id))
                db.execute("INSERT INTO versions VALUES(?,?,?,?,?)", (task_id, task["revision"] + 1, encoded(state), "诊断结果已保存", now))
        return self.get(task_id, owner)

    def fail(self, task_id, owner, operation, message):
        with self.write() as db:
            task = self.owned(db, task_id, owner)
            db.execute("UPDATE operations SET status=CASE WHEN status='cancelled' THEN status ELSE 'failed' END,error=?,finished_at=? WHERE id=? AND task_id=?", (message, stamp(), operation, task_id))
            if task["active_operation"] == operation:
                db.execute("UPDATE tasks SET active_operation=NULL,status='failed',updated_at=? WHERE id=?", (stamp(), task_id))

    def recover_interrupted(self):
        """Called once at single-process server startup, never when a tab opens."""
        with self.write() as db:
            now = stamp()
            db.execute("UPDATE operations SET status='failed',error=?,finished_at=? WHERE status='running'",
                       ("服务已重启，本次处理已中断；已保存的输入仍可继续或重试", now))
            db.execute("UPDATE tasks SET status='failed',active_operation=NULL,updated_at=? WHERE active_operation IS NOT NULL", (now,))

    def cancel(self, task_id, owner, operation=None):
        with self.write() as db:
            task = self.owned(db, task_id, owner)
            active = task["active_operation"]
            if active and operation and active != operation:
                raise WorkflowError(409, "该操作已经变化，请刷新当前处理状态")
            if active:
                db.execute("UPDATE operations SET status='cancelled',finished_at=? WHERE id=?", (stamp(), active))
                db.execute("UPDATE tasks SET active_operation=NULL,status='cancelled',updated_at=? WHERE id=?", (stamp(), task_id))
                self.event(db, task_id, "cancel", {"operation_id": active})
        return self.get(task_id, owner)

    def modification(self, task_id, owner, revision, suggestion_id, action, text):
        with self.write() as db:
            task = self.owned(db, task_id, owner); self.expected(task, revision)
            op = db.execute("SELECT * FROM operations WHERE id=?", (task["current_run"],)).fetchone()
            if not op or not op["report"] or op["status"] in {"running", "cancelled", "failed"} or self.run_view(op, task)["stale"]:
                raise WorkflowError(409, "建议依据已变化，请重新检查后再操作")
            report = json.loads(op["report"])
            suggestion = next((x for x in report.get("suggestions", []) if x["id"] == suggestion_id), None)
            if not suggestion:
                raise WorkflowError(404, "建议不存在")
            modifications = json.loads(op["modifications"])
            item = modifications.get(suggestion_id, {"status": "pending", "text": "", "completed_at": None, "adopted_at": None})
            if action not in {"adopt", "save", "complete", "reopen", "unadopt", "ignore", "restore"}:
                raise WorkflowError(422, "未知待办操作")
            value = text.strip() if text is not None else item["text"]
            if action in {"adopt", "complete"} and not value:
                raise WorkflowError(422, "请先填写非空的实际修改内容")
            if action == "complete" and item["status"] not in {"adopted", "completed"}:
                raise WorkflowError(422, "请先采纳并完成实际修改，再标记完成")
            before = dict(item)
            if action == "adopt": item.update(status="adopted", adopted_at=stamp(), completed_at=None, text=value)
            elif action == "complete": item.update(status="completed", completed_at=stamp(), text=value)
            elif action in {"reopen", "save"}:
                item.update(text=value, completed_at=None, status="adopted" if item.get("adopted_at") and value else "pending")
            elif action == "unadopt": item.update(status="pending", adopted_at=None, completed_at=None)
            elif action == "ignore": item.update(status="ignored", completed_at=None)
            else: item.update(status="pending", completed_at=None, adopted_at=None)
            item["updated_at"] = stamp()
            modifications[suggestion_id] = item
            db.execute("UPDATE operations SET modifications=? WHERE id=?", (encoded(modifications), op["id"]))
            db.execute("UPDATE tasks SET revision=revision+1,updated_at=? WHERE id=?", (stamp(), task_id))
            self.event(db, task_id, action, {"before": before, "after": item}, op["id"], suggestion_id)
        return self.get(task_id, owner)

    def history(self, task_id, owner):
        with self.connect() as db:
            self.owned(db, task_id, owner)
            versions = [{"version_id": str(v["revision"]), "revision": v["revision"], "state": json.loads(v["state"]),
                         "created_at": v["created_at"], "reason": v["reason"]}
                        for v in db.execute("SELECT * FROM versions WHERE task_id=? ORDER BY revision DESC", (task_id,))]
            runs = [self.run_view(op) for op in db.execute("SELECT * FROM operations WHERE task_id=? ORDER BY created_at DESC", (task_id,))]
            events = [{**dict(row), "payload": json.loads(row["payload"])} for row in db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,))]
            exports = [dict(row) for row in db.execute("SELECT * FROM exports WHERE task_id=? ORDER BY created_at DESC", (task_id,))]
            return {"versions": versions, "runs": runs, "events": events, "exports": exports}

    def export_run(self, task_id, owner, run_id=None):
        with self.connect() as db:
            task = self.owned(db, task_id, owner)
            op = db.execute("SELECT * FROM operations WHERE id=? AND task_id=? AND kind!='parse'",
                            (run_id or task["current_run"], task_id)).fetchone()
            if op is None or not op["report"]:
                raise WorkflowError(422, "请先完成至少一个诊断模块")
            if not run_id and self.run_view(op, task)["stale"]:
                raise WorkflowError(409, "当前输入已变化；请重新诊断或明确选择历史报告导出")
            if op["status"] in {"running", "failed", "cancelled"}:
                raise WorkflowError(422, "该次处理没有可导出的有效报告")
            return self.run_view(op)

    def export_record(self, task_id, owner, run_id, kind, format, status, export_id=None):
        identity = export_id or str(uuid4())
        with self.write() as db:
            self.owned(db, task_id, owner)
            if export_id:
                db.execute("UPDATE exports SET status=? WHERE id=? AND task_id=?", (status, identity, task_id))
            else:
                db.execute("INSERT INTO exports VALUES(?,?,?,?,?,?,?)", (identity, task_id, run_id, kind, format, status, stamp()))
        return identity

    def restore(self, task_id, owner, revision, version):
        with self.connect() as db:
            self.owned(db, task_id, owner)
            row = db.execute("SELECT state FROM versions WHERE task_id=? AND revision=?", (task_id, version)).fetchone()
            if row is None: raise WorkflowError(404, "历史版本不存在")
            state = json.loads(row[0]); state.update(review_confirmed=False, confirmed_fields=[], requirements_confirmed=False)
        return self.save(task_id, owner, revision, state, reason=f"恢复历史版本 {version}", force=True)

    def delete(self, task_id, owner):
        with self.write() as db:
            self.owned(db, task_id, owner)
            db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
