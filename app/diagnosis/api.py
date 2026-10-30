"""Candidate-facing, stateless diagnosis API.

All original uploads are read in memory; no persistence and no user-file writes.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from typing import Literal, TypedDict

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.exporter import make_docx, make_pdf
from app.models import Resume
from app.parser import extract_file
from .adapter import convert_resume, from_text
from .engine import run_diagnosis
from .narrative import add_ai_explanations
from .pdf_layout import augment_missing_fields_from_pdf
from .work_relation import propose_existing_work_relations
from .schema import DiagnosisRequest, PasteRequest, RequirementsRequest, SelectionRequest
from .requirements import prepare_requirements
from .scoring import load_rules

router = APIRouter(prefix="/api/diagnosis")
LIMIT_BYTES = 10 * 1024 * 1024
FORMATS = {".pdf",".doc",".docx",".png",".jpg",".jpeg"}


class ParsedResumeResponse(TypedDict):
    status: str
    filename: str
    method: str
    sha256: str
    resume: dict
    source_text: str
    warnings: list[str]
    review_hints: list[dict]


@router.get("/rules")
def rules():
    # The same source used by code and future model explanation prompts.
    rubric=load_rules()
    return {
        "version":rubric["version"],
        "factors":[{"id":x["id"],"label":x["label"]} for x in rubric["factors"]],
        "profiles":{key:{"weights":v["weights"]} for key,v in rubric["profiles"].items()},
        "thresholds":rubric["thresholds"],
        "status":rubric["status"],
        "caveat":rubric["limits"],
    }


@router.post("/parse")
async def parse_uploaded(file: UploadFile = File(...)):
    suffix=Path(file.filename or "").suffix.lower()
    if suffix not in FORMATS:
        raise HTTPException(status_code=415,detail="支持 PDF、Word（DOC/DOCX）及 PNG/JPG，或直接粘贴文本")
    original=await file.read(LIMIT_BYTES+1)
    await file.close()
    if len(original)>LIMIT_BYTES:
        raise HTTPException(status_code=413,detail="单个文件不能超过 10 MB，请压缩后重试")
    if not original:
        raise HTTPException(status_code=422,detail="文件为空，请重新选择")
    try:
        return parse_document(file.filename or "resume"+suffix, original)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


def parse_document(filename: str, content: bytes, should_cancel=None) -> ParsedResumeResponse:
    """One synchronous extraction primitive for HTTP and owned task workers."""
    def check_cancelled():
        if should_cancel and should_cancel():
            raise ValueError("解析已取消")

    suffix=Path(filename).suffix.lower()
    if suffix not in FORMATS:
        raise ValueError("支持 PDF、Word（DOC/DOCX）及 PNG/JPG，或直接粘贴文本")
    if len(content)>LIMIT_BYTES:
        raise ValueError("单个文件不能超过 10 MB")
    checksum=sha256(content).hexdigest()
    check_cancelled()
    text,warnings,method=extract_file(filename,content)
    check_cancelled()
    # Source SHA is of the exact uploaded bytes, not re-serialized content.
    from app.parser import parse_resume
    draft=convert_resume(parse_resume(text),raw_text=text,fingerprint=checksum)
    review_hints=[]
    if suffix==".pdf" and method=="pdf-text":
        check_cancelled()
        try:
            draft,additional=augment_missing_fields_from_pdf(
                draft,content,method=method,
            )
            if additional:
                warnings.append(
                    "检测到多栏排版：已从原文中辅助定位缺失的"
                    + "、".join("姓名" if x=="name" else "教育背景" for x in additional)
                    + "；请在校对页核实，不会自动更改原 PDF。"
                )
        except (ValueError,OSError,TypeError):
            # The old deterministic parser is still the source of truth.
            warnings.append("多栏辅助识别未完成；已保留常规解析结果，请人工核对。")
        check_cancelled()
        try:
            review_hints=propose_existing_work_relations(
                draft,content,method=method,
            )
            if review_hints:
                warnings.append(
                    f"有 {len(review_hints)} 条公司/职位的排版关联候选；"
                    "它们未经核实，不参与评分，请在校对页决定是否采纳。"
                )
        except (ValueError,OSError,TypeError):
            warnings.append("职位排版提示未完成；已保留原有经历字段，请人工核对。")
    check_cancelled()
    return {"status":"ok","filename":Path(filename).name,
            "method":method,"sha256":checksum,"resume":draft.model_dump(),
            "source_text":text,"warnings":warnings,"review_hints":review_hints}


@router.post("/paste")
def paste_text(data: PasteRequest):
    if not data.text.strip():
        raise HTTPException(status_code=422,detail="粘贴文本不能为空")
    # Source fingerprint documents the original UTF-8 bytes of the text.
    draft=from_text(data.text)
    return {"status":"ok","filename":"粘贴文本",
            "method":"paste","sha256":draft.source_sha256,
            "resume":draft.model_dump(),"source_text":data.text,"warnings":[]}


@router.post("/report")
def generate_report(request: DiagnosisRequest):
    if request.use_ai and not request.ai_consent:
        raise HTTPException(status_code=422,detail="使用第三方 AI 解读前必须明确同意数据发送")
    try:
        report=run_diagnosis(
            request.resume,request.target,
            enabled_sections=request.enabled_sections,
            as_of=request.as_of,
            requirements=request.requirements,
        )
        if request.use_ai:
            try:
                add_ai_explanations(
                    report,request_api_key=request.api_key,
                    provider=request.ai_provider,
                )
            except (ValueError, RuntimeError) as exc:
                # Do not let one optional provider destroy deterministic output.
                report["meta"]["ai_narrative"]="unavailable"
                report["meta"]["ai_notice"]="AI 辅助解读未完成；五维规则报告已保留。请检查服务商配置。"
        return report
    except (ValueError, OSError, KeyError) as exc:
        # No user data or provider secrets in responses.
        raise HTTPException(status_code=422,detail="简历或诊断参数无效，请补充可分析的履历并检查日期、能力项与配置") from exc


@router.post("/requirements")
def requirements(request: RequirementsRequest):
    return prepare_requirements(request.target)


def _selected_items(payload: SelectionRequest) -> list[dict]:
    if payload.kind not in {"todo","questions"}:
        raise HTTPException(status_code=422,detail="未知的导出清单类型")
    if payload.format not in {"txt","pdf"}:
        raise HTTPException(status_code=422,detail="仅支持 PDF 与文本 TXT")
    items=payload.report.get("suggestions" if payload.kind=="todo" else "interview_questions",[])
    if not isinstance(items,list):
        raise HTTPException(status_code=422,detail="报告清单格式无效")
    by_id={x["id"]:x for x in items if isinstance(x,dict) and isinstance(x.get("id"),str)}
    if len(by_id)!=len(items) or len(set(payload.selected_ids))!=len(payload.selected_ids):
        raise HTTPException(status_code=422,detail="选择清单包含重复或非法项目")
    if not payload.selected_ids or any(x not in by_id for x in payload.selected_ids):
        raise HTTPException(status_code=422,detail="请勾选需要导出的清单项目")
    if len(str(payload.report)) > 240_000:
        raise HTTPException(status_code=413,detail="清单内容过长")
    return [by_id[id] for id in payload.selected_ids]


@router.post("/export")
def export_selected(payload: SelectionRequest):
    chosen=_selected_items(payload)
    lines=[]
    for index,item in enumerate(chosen,1):
        if payload.kind=="todo":
            title=str(item.get("title","优化建议"))
            lines.append(
                f"{index}. [{item.get('priority','中')}] {title}\n"
                f"位置：{item.get('location','')}\n"
                f"原文：{item.get('original','')}\n"
                + (f"对照位置：{item['related_location']}\n"
                   f"对照原文：{item.get('related_original','')}\n"
                   if item.get("related_location") else "")
                + f"建议类别：{item.get('assessment','需要修正')}\n"
                f"{'优化机会' if item.get('assessment')=='可选深化' else '问题'}：{item.get('problem','')}\n"
                f"建议：{item.get('action','')}\n"
                f"示例（不得视为真实经历）：{item.get('example','')}\n"
            )
        else:
            lines.append(
                f"{index}. 核查点：{item.get('check','')}\n"
                f"建议提问：{item.get('question','')}\n"
                f"想确认什么：{item.get('purpose','')}\n"
            )
    heading="PaperPro 优化待办清单" if payload.kind=="todo" else "PaperPro 面试核查清单"
    body=heading+"\n仅导出用户勾选项目，不代表对经历真实性的定性。\n\n"+"\n".join(lines)
    if payload.format=="txt":
        content=body.encode("utf-8-sig")
        media="text/plain; charset=utf-8"
    else:
        doc=Resume(name=heading,summary="仅导出已勾选条目；内容为需人工核对的建议。",
                   additional=[line for line in body.splitlines()[3:] if line.strip()])
        try:
            word=make_docx(doc)
            content=make_pdf(doc,word)
        except Exception as exc:
            raise HTTPException(status_code=500,detail="PDF 生成未完成，请先尝试文本导出") from exc
        media="application/pdf"
    kind="todo" if payload.kind=="todo" else "interview_questions"
    ext=payload.format
    return StreamingResponse(
        BytesIO(content),
        media_type=media,
        headers={"Content-Disposition":f'attachment; filename="paperpro_{kind}.{ext}"',
                 "Cache-Control":"no-store","X-Selected-Count":str(len(chosen))},
    )
