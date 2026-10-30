from __future__ import annotations

from contextlib import asynccontextmanager
from io import BytesIO
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .enhancer import ai_enhance, local_enhance
from .exporter import make_docx, make_pdf
from .models import EnhanceRequest, ExportRequest
from .parser import MAX_UPLOAD_BYTES, extract_file, parse_resume
from .settings import SettingsError, resolve_provider
from .diagnosis.api import router as diagnosis_router
from .diagnosis.workflow import router as workflow_router, store as candidate_store
from .diagnosis import workflow_export  # Registers owned snapshot export on workflow_router.
from .diagnosis.workflow_store import WorkflowError


@asynccontextmanager
async def lifespan(app):
    candidate_store().recover_interrupted()
    yield


app = FastAPI(title="PaperPro Resume Studio", version="0.1.0", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
app.include_router(diagnosis_router)
app.include_router(workflow_router)


@app.exception_handler(WorkflowError)
async def workflow_error(request, error: WorkflowError):
    return JSONResponse(status_code=error.status, content={"detail": error.message}, headers={"Cache-Control": "no-store"})


@app.exception_handler(RequestValidationError)
async def validation_without_secret_echo(request, error: RequestValidationError):
    # FastAPI's default error includes invalid request input, possibly API keys.
    return JSONResponse(status_code=422, content={"detail": "请求参数缺失或格式错误，请检查输入内容"})


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "paperpro", "local_only": True}


@app.get("/api/config")
def config():
    try:
        configured = resolve_provider("configured")
        deepseek = resolve_provider("deepseek")
    except SettingsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ai_available": bool(configured.api_key),
        "deepseek_ai_available": bool(deepseek.api_key),
        "ocr_engine": "RapidOCR (Chinese + English), Tesseract English fallback",
        "accepted_extensions": [".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg"],
        "max_upload_mb": 12,
        "template": "PaperPro Classic A4",
        "private_by_default": True,
    }


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    name = Path(file.filename or "").name
    extension = Path(name).suffix.lower()
    if extension not in {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=415, detail="仅支持 PDF / Word / PNG / JPG 文件")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件不能超过 12 MB")
    try:
        text, warnings, method = extract_file(name, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TypeError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    draft = parse_resume(text)
    if not draft.name:
        warnings.append("未能可靠识别姓名，请在编辑区手动填写")
    if not draft.experience and not draft.education and not draft.projects:
        warnings.append("未检测到常见履历分区，请核对原文并手动调整")
    return {"filename": name, "method": method, "resume": draft.model_dump(), "source_text": text, "warnings": warnings}


@app.post("/api/enhance")
def enhance(request: EnhanceRequest):
    if request.use_ai:
        try:
            selected = resolve_provider(request.provider, request.api_key)
        except SettingsError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not selected.api_key:
            raise HTTPException(status_code=400, detail="请在 settings.local.json 或网页中配置该服务商的 API Key")
        try:
            result, changes = ai_enhance(
                request.resume, api_key=selected.api_key, provider=selected.provider,
                target_role=request.target_role, job_description=request.job_description,
                configured_base_url=selected.base_url, configured_model=selected.model,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        mode = "ai"
    else:
        result, changes = local_enhance(request.resume)
        mode = "local"
    return {
        "resume": result.model_dump(), "changes": changes, "mode": mode,
        "warnings": [
            "AI 的定性措辞仍可能偏离事实，下载前请对照原文核实。"
        ] if mode == "ai" else [
            "本地模式只整理文字格式，不会调用外部 AI 服务。"
        ],
    }


@app.post("/api/export")
def export_document(request: ExportRequest, format: Literal["docx", "pdf"] = Query(...)):
    draft = request.resume
    if not draft.name.strip() or not (
        draft.summary.strip() or draft.skills or draft.experience or draft.projects or draft.education or draft.additional
    ):
        raise HTTPException(status_code=422, detail="请填写姓名及至少一项履历内容后再导出")
    if len(str(draft.model_dump())) > 100_000:
        raise HTTPException(status_code=413, detail="简历内容过长")
    try:
        docx = make_docx(draft)
        if format == "docx":
            content = docx
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            content = make_pdf(draft, docx)
            mime = "application/pdf"
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"导出失败：{type(exc).__name__}") from exc

    return StreamingResponse(
        BytesIO(content),
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="paperpro_resume.{format}"',
            "Cache-Control": "no-store",
        },
    )


dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if dist.is_dir() and (dist / "index.html").is_file():
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/")
    def index():
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/favicon.svg")
    def favicon():
        return FileResponse(dist / "favicon.svg", media_type="image/svg+xml")

    @app.get("/{path:path}")
    def frontend_fallback(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})
else:
    @app.get("/")
    def index_unbuilt():
        return JSONResponse({"message": "Frontend not built. Run npm install && npm run build in frontend/."})
