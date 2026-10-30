"""Exports are rendered from an owned frozen run, never client-supplied JSON."""
from __future__ import annotations

from io import BytesIO
import html
from pathlib import Path
import re
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, Response

from .workflow import owner, router, store
from .workflow_store import WorkflowError, stamp

NAMES = {"match": "岗位匹配", "experience": "经历与时间", "potential": "发展潜力", "motivation": "求职针对性", "verification": "面试核查"}
HEADINGS = {"todo": "优化待办清单", "questions": "面试准备清单", "report": "诊断报告"}
LABELS = {"status": "状态", "path": "字段位置", "original": "原文", "signal": "信号", "evidence": "依据",
          "label": "要求", "description": "说明", "weight": "权重（%）", "coefficient": "匹配系数", "contribution": "分数贡献",
          "effective_weight": "有效权重", "base_weight": "基础权重", "evidence_refs": "证据", "company": "公司",
          "role": "职位", "start_date": "开始日期", "end_date": "结束日期", "months": "月数", "reason": "待核实原因",
          "location": "位置", "severity": "优先程度", "check": "核查点", "question": "准备问题", "purpose": "核实目的",
          "action": "行动", "title": "事项", "assessment": "建议类别", "problem": "问题", "example": "局部示例",
          "related_location": "对照位置", "related_original": "对照原文", "source_modules": "依据模块"}
LABELS.update(start="开始", end="结束", days="天数", priority="优先程度", source="来源", confidence="证据充分程度",
              hard_gate="硬门槛", gaps="待补充项", gap="待补充项", coefficient_reason="系数说明", basis="判断依据")
STATUS = {"ok": "成功", "disabled": "已关闭", "error": "失败", "cancelled": "已取消", "pending": "待处理"}


def text_value(value, depth=0):
    if isinstance(value, dict):
        return "\n".join(f"{'  ' * depth}{LABELS.get(key, key)}：{text_value(item, depth + 1)}" for key, item in value.items()
                         if key not in {"source_text", "source_sha256", "api_key", "id", "factor_id", "source_anchor", "excerpt", "summary", "report_scope", "uncovered_modules", "target", "issue_id", "weight_unit", "base_weight", "effective_weight", "enabled"} and item is not None)
    if isinstance(value, list):
        return "\n".join(f"{'  ' * depth}- {text_value(item, depth + 1)}" for item in value)
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return str(round(value, 4))
    labels = {**NAMES, **STATUS, "generic_model": "通用岗位模型", "user_jd": "用户提供的 JD"}
    return labels.get(str(value), str(value))


def module_lines(name, section):
    result = [NAMES.get(name, name) + "（" + STATUS.get(section.get("status"), "未完成") + "）",
              section.get("conclusion") or section.get("summary", "")]
    fields = {
        "match": {"display_score": "显示得分", "raw_score": "原始得分", "score_kind": "分数含义", "calibration_warning": "依据边界", "requirements": "逐项要求、贡献与证据"},
        "experience": {"months_total": "完整任职月数", "known_months_total": "已知任职月数", "unknown_date_entries": "日期待核实的经历数", "timeline": "时间线", "gaps": "待核实空档", "overlaps": "待核实重叠", "career_progression": "职业发展证据", "interpretation_boundary": "解释边界"},
        "potential": {"rating": "证据评级", "evidence_count": "支撑证据数", "signals": "观察项", "supporting_signals": "可定位的支撑证据", "weakness": "待补充项"},
        "motivation": {"rating": "针对性评级", "rationale": "解释", "evidence": "定位依据", "suggestion": "表达建议"},
        "verification": {"issues": "待核查事项"},
    }
    for key, label in fields.get(name, {}).items():
        if key in section:
            value = section[key]
            result.extend([label + "：", "未知，需核实" if value is None else text_value(value)])
    result.extend(str(x) for x in section.get("limitations", []))
    version = section.get("version_info", {})
    result.append(f"模块规则：{version.get('rules_version', '未执行')}；基准日：{version.get('as_of', '未执行')}")
    return result + [""]


def export_text(run, kind):
    report, snapshot = run["report"], run["snapshot"]
    dimensions = {name: report["dimensions"][name] for name in NAMES if name in report.get("dimensions", {})}
    valid = [name for name, section in dimensions.items() if isinstance(section, dict) and section.get("status") == "ok"]
    if not valid:
        raise WorkflowError(422, "没有成功的诊断模块，不能生成建议或报告导出")
    meta = report.get("meta", {})
    lines = [f"PaperPro {HEADINGS[kind]}", f"目标职位：{snapshot['target']['role']}",
             f"目标公司：{snapshot['target'].get('company') or '未指定'}", f"报告 ID：{run['id']}",
             f"原件版本：{snapshot['document_version_id']}", f"输入版本：{snapshot['revision']}",
             f"生成时间：{run['finished_at']}", f"计算基准日：{snapshot['as_of']}",
             f"规则版本：{meta.get('rules_version') or snapshot['rule_version']}",
             "有效范围：" + "、".join(NAMES.get(name, name) for name in valid),
             "未覆盖模块：" + ("、".join(f"{NAMES.get(name, name)}（{STATUS.get(section.get('status'), '未完成')}）" for name, section in dimensions.items() if name not in valid) or "无"),
             "本内容用于个人改进与面试准备；缺失信息需要补充核实，不能据此认定本人不具备相关能力。", ""]
    count = 0
    if kind == "todo":
        for item in report.get("suggestions", []):
            modification = run["modifications"].get(item["id"], {})
            if modification.get("status") not in {"adopted", "completed"} or not modification.get("text", "").strip():
                continue
            count += 1
            lines.extend([f"{count}. {item.get('title', '优化建议')}（{'已完成' if modification['status'] == 'completed' else '已采纳，待完成'}）",
                          f"位置：{item.get('location', '')}", f"原文：{item.get('original', '')}",
                          *([f"对照位置：{item['related_location']}", f"对照原文：{item.get('related_original', '')}"] if item.get("related_location") else []),
                          f"问题：{item.get('problem', '')}",
                          f"行动：{item.get('action', '')}", f"局部示例（需核实）：{item.get('example', '')}",
                          f"我的实际修改：{modification['text']}", f"采纳时间：{modification.get('adopted_at')}",
                          f"完成时间：{modification.get('completed_at') or '尚未完成'}", ""])
        if not count:
            raise WorkflowError(422, "请先填写实际修改并采纳至少一条建议，再导出待办")
    elif kind == "questions":
        for count, item in enumerate(report.get("interview_questions", []), 1):
            lines.extend([f"{count}. 核查点：{item.get('check', '')}", f"准备问题：{item.get('question', '')}",
                          f"核实目的：{item.get('purpose', '')}", ""])
        if not count:
            raise WorkflowError(422, "本次没有可导出的面试准备项")
    else:
        for name, section in dimensions.items():
            lines.extend(module_lines(name, section))
        lines.extend(["优化建议（局部示例，不构成完整替换简历）", text_value(report.get("suggestions", [])), "面试准备", text_value(report.get("interview_questions", []))])
        count = len(valid)
    text = "\n".join(lines)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[电话已隐藏]", text)
    return text, count


def workflow_pdf(text):
    """A report layout with real wrapping; it never looks like a rewritten resume."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    if any(ord(char) > 0xFFFF for char in text):
        raise ValueError("请用 TXT 保留罕见字符")
    font = "STSong-Light"
    fontfile = Path("C:/Windows/Fonts/simhei.ttf")
    if fontfile.exists():
        font = "PaperProReport"
        if font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font, str(fontfile)))
    elif font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(font))
    style = ParagraphStyle("report", fontName=font, fontSize=9, leading=14, wordWrap="CJK", textColor=colors.HexColor("#334155"))
    title = ParagraphStyle("title", parent=style, fontSize=18, leading=25, spaceAfter=16)
    heading = ParagraphStyle("heading", parent=style, fontSize=12, leading=18, spaceBefore=10, spaceAfter=6, keepWithNext=True)
    output, story = BytesIO(), []
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            story.append(Spacer(1, 6)); continue
        selected = title if index == 0 else heading if line.startswith(tuple(NAMES.values())) or line.startswith(("优化建议（", "面试准备")) else style
        story.append(Paragraph(html.escape(line), selected))
    document = SimpleDocTemplate(output, title="PaperPro 诊断与改进材料", author="", leftMargin=48, rightMargin=48, topMargin=42, bottomMargin=42)
    document.build(story)
    return output.getvalue()


@router.get("/{task_id}/export")
def export_task(task_id: str, kind: Literal["todo", "questions", "report"] = "report", format: Literal["txt", "pdf"] = "txt",
                run_id: str | None = None, identity=Depends(owner), repository=Depends(store)):
    run = repository.export_run(task_id, identity, run_id)
    text, count = export_text(run, kind)
    text += "\n导出时间：" + stamp()
    export_id = repository.export_record(task_id, identity, run["id"], kind, format, "pending")
    try:
        if format == "txt":
            content, media = text.encode("utf-8-sig"), "text/plain; charset=utf-8"
        else:
            content, media = workflow_pdf(text), "application/pdf"
    except Exception:
        repository.export_record(task_id, identity, run["id"], kind, format, "failed", export_id)
        raise WorkflowError(500, "PDF 生成未完成，已保存导出记录；可以先导出 TXT") from None
    # Recheck ownership after rendering: deletion during a slow PDF conversion wins.
    repository.export_record(task_id, identity, run["id"], kind, format, "succeeded", export_id)
    role = re.sub(r'[\\/:*?"<>|\r\n]', "_", run["snapshot"]["target"]["role"])[:70]
    filename = f"paperpro_{role}_{run['created_at'][:10]}_v{run['revision']}_r{run['id'][:8]}_e{export_id[:8]}_{kind}.{format}"
    return Response(content, media_type=media, headers={"Cache-Control": "no-store", "X-Selected-Count": str(count),
        "Content-Disposition": f"attachment; filename=paperpro_{kind}.{format}; filename*=UTF-8''{quote(filename)}"})
