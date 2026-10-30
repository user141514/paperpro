"""Owned V3 candidate workflow; drafts and immutable runs share one store."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import secrets
from typing import Literal
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError, field_validator

from .adapter import from_text
from .engine import rebuild_report, run_diagnosis
from .narrative import add_ai_explanations
from .quality import validate_resume_for_diagnosis
from .schema import CandidateResume, DiagnosisRequest
from .workflow_store import TaskStore, WorkflowError, critical_values, encoded

router = APIRouter(prefix="/api/diagnosis/tasks", tags=["Candidate workflow"])
SECTIONS = {"match", "experience", "potential", "motivation", "verification"}
LIMIT = 10 * 1024 * 1024
COOKIE = "paperpro_owner"


def store() -> TaskStore:
    directory = os.environ.get("PAPERPRO_DATA_DIR")
    return TaskStore(Path(directory) if directory else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PaperPro" / "candidate")


def owner(request: Request, response: Response):
    token = request.cookies.get(COOKIE, "")
    if len(token) < 40 or len(token) > 100:
        token = secrets.token_urlsafe(32)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 365,
                            secure=request.url.scheme == "https")
    response.headers["Cache-Control"] = "no-store"
    return sha256(token.encode()).hexdigest()


class CreateText(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    privacy_consent: bool

    @field_validator("privacy_consent")
    @classmethod
    def consent(cls, value):
        if value is not True:
            raise ValueError("请明确同意本次解析与保存用途")
        return value


class SaveDraft(BaseModel):
    expected_revision: int = Field(ge=1)
    state: dict


class Operation(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)


class RunRequest(Operation):
    expected_revision: int = Field(ge=1)
    use_ai: bool = False
    ai_consent: bool = False
    ai_provider: Literal["deepseek", "configured"] = "deepseek"
    api_key: str | None = Field(default=None, max_length=1000, repr=False, exclude=True)


class Modify(BaseModel):
    expected_revision: int = Field(ge=1)
    action: Literal["adopt", "save", "complete", "reopen", "unadopt", "ignore", "restore"]
    text: str | None = Field(default=None, max_length=20_000)


class Restore(BaseModel):
    expected_revision: int = Field(ge=1)
    version_id: int = Field(ge=1)


def clean_state(value, task):
    allowed = {"resume", "target", "requirements", "enabled_sections", "as_of", "review_confirmed", "confirmed_fields", "requirements_confirmed", "step"}
    if set(value) - allowed or len(encoded(value)) > 250_000:
        raise WorkflowError(422, "草稿包含不支持的字段或内容过长")
    state = {**task["state"], **value}
    try:
        if state["resume"] is not None:
            resume = {**state["resume"], "source_text": task["source"]["text"], "source_sha256": task["source"]["sha256"]}
            state["resume"] = CandidateResume.model_validate(resume).model_dump()
        target = state["target"]
        if not isinstance(target, dict) or set(target) - {"role", "company", "job_description"}:
            raise ValueError()
        state["target"] = {key: target.get(key, "") for key in ("role", "company", "job_description")}
        if any(not isinstance(v, str) or len(v) > (12_000 if k == "job_description" else 140) for k, v in state["target"].items()):
            raise ValueError()
        enabled = state["enabled_sections"]
        if not isinstance(enabled, list) or any(not isinstance(x, str) or x not in SECTIONS for x in enabled) or len(set(enabled)) != len(enabled):
            raise ValueError()
        if not isinstance(state["requirements"], list) or len(state["requirements"]) > 40 or any(not isinstance(x, dict) for x in state["requirements"]):
            raise ValueError()
        requirement_keys = {"id", "factor_id", "label", "description", "weight", "enabled", "hard_gate", "source"}
        if any(set(item) - requirement_keys for item in state["requirements"]):
            raise ValueError()
        date.fromisoformat(state["as_of"])
        if any(type(state[x]) is not bool for x in ("review_confirmed", "requirements_confirmed")) or type(state["step"]) is not int or not 0 <= state["step"] <= 4:
            raise ValueError()
        confirmations = state.get("confirmed_fields", [])
        if not isinstance(confirmations, list) or len(confirmations) > 1000 or any(not isinstance(path, str) for path in confirmations):
            raise ValueError()
        known_paths = set(critical_values(state.get("resume"))) | set(critical_values(task["state"].get("resume")))
        if len(set(confirmations)) != len(confirmations) or set(confirmations) - known_paths:
            raise ValueError()
        state["confirmed_fields"] = confirmations
    except (ValueError, TypeError, KeyError):
        raise WorkflowError(422, "草稿格式无效；请检查字段类型、日期和模块设置") from None
    return state


@router.get("")
def list_tasks(identity=Depends(owner), repository=Depends(store)):
    return repository.listing(identity)


@router.post("", status_code=201)
def create_text(data: CreateText, identity=Depends(owner), repository=Depends(store)):
    if not data.text.strip():
        raise WorkflowError(422, "粘贴文本不能为空")
    return repository.create(identity, "粘贴文本", data.text.encode("utf-8"), "paste")


def validate_file(filename, content):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg"}:
        raise WorkflowError(415, "支持 PDF、Word（DOC/DOCX）与 PNG/JPG 文件")
    if not content:
        raise WorkflowError(422, "文件为空，请重新选择")
    if len(content) > LIMIT:
        raise WorkflowError(413, "单个文件不能超过 10 MB")
    valid = False
    try:
        if suffix == ".pdf" and b"%PDF-" in content[:1024]:
            import fitz
            with fitz.open(stream=content, filetype="pdf") as document:
                valid = document.page_count > 0 and not document.is_encrypted
        elif suffix == ".docx":
            with ZipFile(BytesIO(content)) as archive:
                valid = "word/document.xml" in archive.namelist() and sum(x.file_size for x in archive.infolist()) <= 50 * LIMIT
        elif suffix == ".doc":
            valid = content.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
        elif suffix in {".png", ".jpg", ".jpeg"}:
            from PIL import Image
            with Image.open(BytesIO(content)) as image:
                valid = image.format == ("PNG" if suffix == ".png" else "JPEG")
                image.verify()
    except (ValueError, OSError, BadZipFile, RuntimeError):
        valid = False
    if not valid:
        raise WorkflowError(422, "文件内容与扩展名不匹配、文件已损坏或无法读取")


@router.post("/upload", status_code=201)
async def create_upload(file: UploadFile = File(...), privacy_consent: bool = Form(...), identity=Depends(owner), repository=Depends(store)):
    if not privacy_consent:
        await file.close()
        raise WorkflowError(422, "请先同意本次解析与保存用途")
    filename = (file.filename or "resume").replace("\\", "/").split("/")[-1][:240]
    content = await file.read(LIMIT + 1)
    await file.close()
    await run_in_threadpool(validate_file, filename, content)
    return repository.create(identity, filename, content, "upload")


@router.get("/{task_id}")
def get_task(task_id: str, identity=Depends(owner), repository=Depends(store)):
    return repository.get(task_id, identity)


@router.patch("/{task_id}")
def save_task(task_id: str, data: SaveDraft, identity=Depends(owner), repository=Depends(store)):
    task = repository.get(task_id, identity)
    return repository.save(task_id, identity, data.expected_revision, clean_state(data.state, task))


@router.post("/{task_id}/parse")
async def parse_task(task_id: str, data: Operation, identity=Depends(owner), repository=Depends(store)):
    task = repository.get(task_id, identity)
    snapshot = {"document_version_id": task["document_version_id"], "source_sha256": task["source"]["sha256"]}
    if not repository.begin(task_id, identity, task["revision"], data.operation_id, "parse", snapshot):
        return repository.get(task_id, identity)
    def extract():
        if not repository.active(task_id, identity, data.operation_id):
            raise ValueError("解析已取消")
        source, content = repository.original(task_id, identity)
        if source["input_type"] == "paste":
            text = content.decode("utf-8")
            resume = from_text(text)
            return {"resume": resume.model_dump(), "source_text": text, "method": "paste", "warnings": [], "review_hints": []}
        from .api import parse_document
        return parse_document(source["filename"], content, should_cancel=lambda: not repository.active(task_id, identity, data.operation_id))
    try:
        parsed = await run_in_threadpool(extract)
        if not parsed.get("source_text", "").strip():
            raise ValueError("未提取到可读内容，请使用清晰图片或粘贴文本")
        return repository.finish_parse(task_id, identity, data.operation_id, parsed)
    except WorkflowError:
        raise
    except Exception:
        repository.fail(task_id, identity, data.operation_id, "解析未完成，请核对文件可读性后重试同一原件")
        raise WorkflowError(422, "解析未完成，请核对文件可读性后重试同一原件") from None


def diagnosis_input(task, data):
    state = task["state"]
    if not state["review_confirmed"] or not state["requirements_confirmed"]:
        raise WorkflowError(422, "请先完成关键字段核对与岗位要求确认")
    if set(critical_values(state.get("resume"))) - set(state.get("confirmed_fields", [])):
        raise WorkflowError(422, "还有关键字段待核对，请逐项或批量确认已核对内容")
    if not state["requirements"]:
        raise WorkflowError(422, "请先生成、核对并确认岗位要求")
    if data.use_ai and not data.ai_consent:
        raise WorkflowError(422, "使用第三方 AI 解读前必须明确同意数据发送")
    try:
        request = DiagnosisRequest.model_validate({**state, "use_ai": data.use_ai, "ai_consent": data.ai_consent,
            "ai_provider": data.ai_provider, "api_key": data.api_key})
        validate_resume_for_diagnosis(request.resume)
        date.fromisoformat(request.as_of)
        return request
    except (ValueError, TypeError, ValidationError):
        raise WorkflowError(422, "请检查简历内容、目标职位、岗位权重合计和已启用的模块") from None


async def execute(task_id, data, identity, repository, retry=None):
    task = repository.get(task_id, identity)
    request = diagnosis_input(task, data)
    previous = task["current_run"]
    if retry and (retry not in request.enabled_sections or not previous or previous["stale"] or not previous["report"]):
        raise WorkflowError(409, "当前模块不可重试；输入变化后请重新生成报告")
    snapshot = {**{key: task["state"][key] for key in ("resume", "target", "requirements", "enabled_sections", "as_of", "confirmed_fields")},
                "document_version_id": task["document_version_id"], "revision": task["revision"], "retry_module": retry,
                "rule_version": "candidate-v3-20261030"}
    if not repository.begin(task_id, identity, data.expected_revision, data.operation_id, "retry" if retry else "diagnosis", snapshot):
        return repository.get(task_id, identity)
    def generate():
        result = run_diagnosis(request.resume, request.target, enabled_sections=[retry] if retry else request.enabled_sections,
            as_of=request.as_of, requirements=request.requirements,
            on_section=lambda name, section: repository.module(task_id, data.operation_id, name, section),
            should_cancel=lambda: not repository.active(task_id, identity, data.operation_id))
        if retry and repository.active(task_id, identity, data.operation_id):
            sections = {**previous["report"]["dimensions"], retry: result["dimensions"][retry]}
            result = rebuild_report(request.resume, request.target, sections, request.as_of, requirements=request.requirements)
        if data.use_ai and repository.active(task_id, identity, data.operation_id):
            try:
                add_ai_explanations(result, request_api_key=data.api_key, provider=data.ai_provider)
            except (ValueError, RuntimeError):
                result.setdefault("meta", {}).update(ai_narrative="unavailable", ai_notice="AI 辅助解读未完成，已保留规则报告")
        result.setdefault("meta", {}).update(task_id=task_id, run_id=data.operation_id,
            document_version_id=task["document_version_id"], input_revision=task["revision"])
        return result
    try:
        report = await run_in_threadpool(generate)
        inherited = None
        if retry:
            before = {item["id"]: item for item in previous["report"].get("suggestions", [])}
            after = {item["id"]: item for item in report.get("suggestions", [])}
            def content(item):
                return {key: value for key, value in item.items() if key not in {"report_scope", "uncovered_modules"}}
            inherited = {}
            for key, modification in previous["modifications"].items():
                if key not in after or key not in before:
                    continue
                unaffected = retry not in before[key].get("source_modules", []) and content(before[key]) == content(after[key])
                inherited[key] = dict(modification) if unaffected else {**modification, "status": "needs_confirmation", "completed_at": None, "adopted_at": None}
        return repository.finish_run(task_id, identity, data.operation_id, report, modifications=inherited)
    except WorkflowError:
        raise
    except Exception:
        repository.fail(task_id, identity, data.operation_id, "诊断未完成，已保留输入与已完成的模块，可重试")
        raise WorkflowError(422, "诊断未完成，已保留输入与已完成的模块，可重试") from None


@router.post("/{task_id}/run")
async def run_task(task_id: str, data: RunRequest, identity=Depends(owner), repository=Depends(store)):
    return await execute(task_id, data, identity, repository)


@router.post("/{task_id}/retry/{module}")
async def retry_module(task_id: str, module: str, data: RunRequest, identity=Depends(owner), repository=Depends(store)):
    if module not in SECTIONS:
        raise WorkflowError(404, "未知诊断模块")
    return await execute(task_id, data, identity, repository, retry=module)


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, data: Operation, identity=Depends(owner), repository=Depends(store)):
    return repository.cancel(task_id, identity, data.operation_id)


@router.patch("/{task_id}/suggestions/{suggestion_id}")
def modify_suggestion(task_id: str, suggestion_id: str, data: Modify, identity=Depends(owner), repository=Depends(store)):
    return repository.modification(task_id, identity, data.expected_revision, suggestion_id, data.action, data.text)


@router.get("/{task_id}/history")
def history(task_id: str, identity=Depends(owner), repository=Depends(store)):
    return repository.history(task_id, identity)


@router.post("/{task_id}/restore")
def restore(task_id: str, data: Restore, identity=Depends(owner), repository=Depends(store)):
    return repository.restore(task_id, identity, data.expected_revision, data.version_id)


@router.get("/{task_id}/source")
def original(task_id: str, identity=Depends(owner), repository=Depends(store)):
    source, content = repository.original(task_id, identity)
    from urllib.parse import quote
    return Response(content, media_type="application/octet-stream", headers={"Cache-Control": "no-store",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(source['filename'])}"})


@router.delete("/{task_id}")
def delete(task_id: str, identity=Depends(owner), repository=Depends(store)):
    repository.delete(task_id, identity)
    return {"deleted": True}
