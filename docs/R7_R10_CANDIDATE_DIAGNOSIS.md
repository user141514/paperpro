# R7–R10: Candidate Resume Diagnosis (2026-10-19)

> Historical R7–R10 checkpoint. The user-supplied V3 design and V2 flow on 2026-10-30 now govern the candidate workflow: role is required, advice is evidence-limited rather than padded to eight, and SQLite owns resumable drafts, runs, adoption/completion and exports. Current contract and acceptance: [V3 checklist](V3_CHECKLIST_ACCEPTANCE_20261030.md). The older stateless/branch statements below describe the 10/19 implementation only. Current task branch is `feat/v3-checklist-20261030`; the instruction not to push until explicitly requested still applies.

## Problem and objective
Extend existing PaperPro from resume cleanup into a candidate-facing five-dimension diagnosis. Input is a reviewed, editable resume plus a role and/or company. Output is an evidence-linked diagnosis, suggestions (>=8, each location/problem/action/example), interview follow-up questions, and a selected-only todo list downloadable as PDF/TXT.

## Reference and limits
- 8m54s HR product video supplied 2026-10-19. The source UI is a *batch HR dashboard*, not a candidate flow. Borrow its navy side rail, spacious white cards, layered summary→table→detail design and status colors. Do not import its bulk list, hiring decisions, applicant ranking or claims of backend capabilities.
- User's R7–R10 message is the feature contract. No authoritative 美太 HR five-output rule implementation was found under accessible E:/company_work project roots. Therefore rubric values and weights are **declared provisional configurable conventions**, not a claim of identical production HR scores. The five category names/shape are aligned; exact numeric parity needs the HR rule owner to provide their source.
- No permissioned 20-real-resume QA corpus is currently available. Do not claim R7-1 >=90% or R8-2 photo >=85% until those sets are explicitly reviewed. No physical iOS/Android device in this Windows setup; Playwright mobile emulation is only partial evidence.

## User journey / states
1 Upload: PDF/DOC/DOCX/PNG/JPEG <=10 MB, or paste text; SHA256 raw evidence fingerprint; progress messages. Upload must not change raw bytes.
2 Review: fixed structured schema with name/contact, education, experience (company, role, start/end), projects, skills, certificates, self-evaluation, additional; every field editable.
3 Target: role and/or company required; optional pasted JD; role autocomplete based on known strings. Empty role+company = no next action.
4 Report: source-based 5-block HR-perspective diagnosis with independently selectable sections, deterministic match coefficients/weights, purely computed employment timeline, provenance/version/time. The AI narrative (when voluntarily configured+authorized) sees only the computed figures and rule table; cannot invent dates. A failed section returns its own status and does not suppress the other four.
5 Action: >=8 prioritized suggestions, each four required fields; issue→interview question; user selects specific suggestions and exports TXT/PDF. No rewriting entire original resume.

Back/forward retains state. New file or meaningful edit invalidates a previous report. The classic resume editing flow remains available at /classic; the new candidate flow is / or /diagnosis.

## Engineering model and invariant
**Objects:** immutable upload bytes (not stored) → extracted source text/hash → human-corrected profile → target → deterministic rule-engine report → human-selected suggestion IDs → todo export.
**Authority:** app/parser.py owns extraction; app/diagnosis/schema.py owns structured input contract; app/diagnosis/rules.json is the only source of thresholds, keyword sets and scoring rules; app/diagnosis/engine.py owns calculations; /api/diagnosis/* owns validation/export; frontend/src/CandidateDiagnosisApp.jsx owns wizard state. app/settings.py remains sole credential owner.
**Invariant:** no source bytes are modified; no fabricated employment dates, company facts or metrics; absence of evidence must be marked as "简历未体现", not proof of incompetence; score is reproducible for the same normalized input/rules version; suggestions and issues point to visible reviewed field paths; TODO export contains selected IDs only; toggles and partial failures never remove unrelated completed sections.

## Testing and acceptance strategy
- Parser API tests: supported file kinds, 10MB cutoff, text pasting, SHA fingerprint, editable key fields and unchanged original.
- Rule engine unit: 0–1 coefficients, weights, >=6 items, same input => same score; gap days, overlap and total employment periods checked manually on known dates; 5 outputs, three potential evidence entries, 8 four-field suggestions, selection check.
- Endpoint smoke: upload/paste→review→target→diagnostics→selected PDF/TXT and interview questions; disabled dimension fails independently.
- Browser Chrome: upload, edit, target disabled when blank, 5-stage backward movement, report all dimensions, 8 suggestions, export selected; invalid file and no hanging state >10sec.
- Source evidence validation and independent adversarial stage review. Do not claim production calibrated match scores or target-company private knowledge without JD/company data.

## Phase plan
- P0-A: schema+parser adapter+paste endpoint with tests.
- P0-B: deterministic common rule source and complete 5-section report with tests.
- P0-C: Mantine new candidate wizard, video-derived visual hierarchy, responsive use and actual browser smoke.
- P1-D: optional DeepSeek narrative bound to computed facts and same rule table; independent failure containment.
- P1-E: model adversarial tests, long docs, edge cases, user-data QA gates. Current deterministic and Chrome regression evidence exists; real HR outcomes and sample-quality gates remain outstanding.

## 2026-10-19 checkpoint
- Candidate flow at `/` and legacy editor at `/classic`, with source hash and human-controlled exports.
- Related employment months computed only from dated role/duty evidence, using the union of calendar months (no overlapping double-count).
- Asynchronous diagnosis results are invalidated by target/resume edits or navigation back; stale results cannot override newer user intentions.
- Role-specific routing and negative evidence tests prevent generic engineering aliases and explicit negations from inflating weights. Employment duration and role families are tested against civil engineering, software and data roles; ambiguous claims remain insufficient rather than affirmative evidence.
- Optional AI authority is limited to selecting `narrative_codes` and existing `evidence_paths` from rules.json; all displayed narration is rendered locally, and invalid provider URLs or unsupported claims fail closed to deterministic output.
- Input-generation generations invalidate when target, résumé or pasted source changes; enabled-section checkbox event values are captured synchronously. HR label duplicate checks ignore contact-only changes.
- Added rule version 0.3.0 synthetic counterfactual validation: 1,680 pairs over 3 fixed seeds × 4 job families × 7 invariants × 20 JD variations; all expected monotonicity/invariance constraints pass. New failures actually found and fixed: duplicate project claims, duplicate work periods boosting project score, and Git JD keyword missing from the shared factor vocabulary. This is not external HR validity.
- Core backend/diagnosis and 25 Chrome E2E tests green as of 2026-10-19. Full Python suite ran to completion with 90% coverage but emitted legacy Windows Word COM RPC exceptions; this remains a platform observation, not a claim of fault-free native COM operation.
- Watchdog registration was attempted via controlled API; its observed state is `connected=false`, `persistent_turn_identity_unavailable` and must not be portrayed as live supervision.
- Extended R7/R8 simulated format QA: 20 DOCX/PDF ×13 fields => 260/260; 4 synthetic scan images ×13 fields => 49/52 after safe OCR text normalization. Actual iOS/Android gallery hardware remains unvalidated; see docs/SYNTHETIC_PARSER_QA.md.
- R7-5/R7-6 advice now separates actual evidence gaps (`需要修正`) from optional improvements (`可选深化`). A fully dated, well-evidenced résumé no longer receives unsupported allegations of missing dates or metric baselines; exports retain each advice category. At least 8 suggestions and no rewriting of the original file remain enforced.
- R7-2 PDF 工作职位几何关系经过红→绿实验：同行三段文本能提出候选，但独立外部样本中的唯一候选与 GT 不一致，故彻底禁止自动写入角色或参与评分。只返回 `review_hints` 并让用户在第二步明确采纳/忽略；未经采纳的提示不得出现在角色或年限中。本轮继续固定了有类型的数据接口 `WorkRelationHint`，包括 `experience.N.role` 的字段归属、PDF 页码、三个归一化边界框、未经校准的 `confidence` 等级与缺失的独立语义核查信号。测试见 `tests/test_work_relation_geometry.py` 和 `frontend/e2e/candidate.spec.js`，外部反例审计见 `scripts/profile_work_relation_gates.py`。外部 20 份 PDF 的固定结构化基准保持 167/276（60.51%），没有虚报提升。
- R7-1/R8 实验性关系监督进度：建立独立外部 GT 到原生 PDF 文字行对齐、公司/职位关系样本构造、固定测试集屏障。非重叠开发池 21–40 为 69 组（33 正/36 对照），固定挑战集为 70 组（32 正/38 对照）；两组中无需训练的几何排序已在这些 GT 唯一锚点条件下达到全部可比较角色 Top-1，CPU 线性参数化实验无额外收益，未保存/部署。不能以此替代 PDF→结构化字段的外部 167/276（60.51%）基准。详见 docs/RELATION_SUPERVISION_20261019.md。下一最小任务是**不带 GT 的职位/公司文本候选召回与误报验证**，不得让未核实内容进入评分。
- R7-1 新增无 GT 的 PDF 原生文字行字段候选实验，不更改正式解析/评分。开发池 21–40：职位候选 GT 原文覆盖 34/45、公司 36/46；冻结挑战集：职位 27/50、公司 29/49，相对开发池显著退化。该方法被判定为不可部署，未从不存在的 GT 中推断错误负例。源码与边界：`app/diagnosis/native_candidate_lines.py`、`scripts/benchmark_native_candidate_lines.py`、`docs/NATIVE_FIELD_CANDIDATES_20261019.md`。后续应采用独立 GT 唯一文本锚点 + 版式结构特征训练字段发现器，使用新的未见样本评价，不针对原冻结挑战集调词表。
- R7/R8 实验层补齐独立 GT 行/片段监督：整行 CPU 分类器以 15 PDF 与扩展 35 PDF 训练，两者在 5 份开发验证里均弱于不训练的词表基线（职位 5/13 对 10/13，扩展公司 9/14 对 10/14；需核对行 80 对 33），预定门禁拒绝读取新冻结测试集 41–60，不推广模型。定位上游原因是同一 PDF 行内的公司与职位被整行互斥标签丢弃；新字符区间标注在原训练 21–35 的 15 份 PDF 上使可保留职位锚点 14→24、公司 18→28，共额外 20 个正向标注，不生成未经 GT 确认的负样本。详见 docs/LINE_FIELD_SPAN_SUPERVISION_20261019.md；产品实际外部解析基准仍 167/276（60.51%）。
- 本轮继续 R7-1/R8 字符片段提议器：使用独立 GT 正向字符区间学习字段后缀、字符结构及边界；在推理时只读取 PDF bytes，返回可追溯的 unverified 片段。原开发验证 36–40 的 5 份 PDF：职位完整字段精确命中 4/13，公司 9/14、人工候选 18 项；旧规则整行 GT 包含率职位 10/13、公司 10/14，候选 33 项。按预先锁定的门禁判定失败，不读取新冻结集 41–60、不修改生产解析/评分。详见 docs/GT_BLIND_SPAN_PROPOSER_20261019.md。再次调整词表、数据窗口或阈值容易过拟合，下一步应转向独立复核的片段边界数据与部分标注序列建模，而非继续局部筛选。
- R7/R8 下一步纠偏：实现 `app/diagnosis/partial_bio.py`，将独立 GT 的字段正例转为可训练前校验的部分 BIO 序列；严格保留 UNKNOWN 与显式 O 的区别。训练 21–35 的 15 份公开合成 PDF 实测 601 原生行、9,706 个字符，其中 477 个（4.91%）有独立 GT 正例、9,229 个（95.09%）未知，已知背景 O=0；可保留正向片段 62 个（职位 24/公司 28/学校 10）。因此不启动常规完整监督 BIO/CRF、不触碰验证及冻结集、不部署模型。统计脚本 `scripts/benchmark_partial_bio.py`、回归 `tests/test_partial_bio.py`、方法文档 `docs/PARTIAL_BIO_SUPERVISION_20261019.md`。后续必须先得到明确的非实体监督或合法的部分标签学习目标，而不是为 95% 未标注字符伪造背景负例。
- 部分 BIO 后续最小步：依据公开合成 GT 的 `basicInfo.personalEmail/phoneNumber`，只对格式合法、原文字面唯一出现、且不与任何职位/公司/学校 GT 片段冲突的联系方式，补充来源可追溯的背景 `O`；所有未确认字符继续 UNKNOWN。固定训练 15 PDF 实测正向字符 477、合法 `O` 346（邮箱 14、电话 12 个片段）、UNKNOWN 8,883，总监督覆盖 823/9,706（8.48%），不存在伪造背景负样本；本轮没有训练/部署，也未读取开发和冻结集。详细见 docs/PARTIAL_BIO_SUPERVISION_20261019.md。
- 最新 R7/R8 研究端已实现精确部分 BIO 条件边际似然、已知标签 masked CE 和退化解反例（`app/diagnosis/partial_bio_objective.py`）：15 PDF 中已知正向 477 字符、已知联系背景 O 346 字符、UNKNOWN 8,883 字符；全 O/全职位已知错误分别 477/799，而“记住已知标签、未知全 O / 未知全职位”的两种相反策略都零错误且部分损失近零，证明不能用低训练损失验证未知位置。训练、模型部署、新冻结挑战集均未开启。命令 `python -m scripts.benchmark_partial_bio_objective`，详细见 `docs/PARTIAL_BIO_OBJECTIVE_20261019.md`。
- 最新 R7/R8 训练监督扩展：在已核实联系方式 `O` 的基础上，从**独立 GT 姓名及完整有效的任职起止年月**提取严格字面唯一、非嵌套、与目标字段不冲突的非目标字符片段。15 份训练 PDF 的正向字符仍为 477，可信背景 O 从 346→**535**（共 60 片段：邮箱 14、电话 12、姓名 11、起始年月 14、终止年月 9），UNKNOWN 从 8,883→**8,694**，总已观测覆盖 **1,012/9,706（10.43%）**；重复/缺失/仅年份/至今/冲突字段均弃权，不读取冻结集或训练模型。再跑部分 BIO 退化压力测试，全职位错误 799→**988**，两种 UNKNOWN 上相反的记忆策略仍近零损失，故可辨识性不足、生产推广门禁继续关闭。证据在 `docs/PARTIAL_BIO_SUPERVISION_20261019.md` 及 `docs/PARTIAL_BIO_OBJECTIVE_20261019.md`。
- WorkBlock 下一核心工程步骤：新增 `app/diagnosis/workblock_regions.py`，基于原生 PDF 文本行坐标、明确章节标题与保守平行栏位定义不自动确认的工作经历区域。开发训练 21–35 的 15 份外部合成 PDF（独立 GT 公司—职位配对 32 组）实测：WorkBlock 同块共现 17/32、起止年月也匹配 16/32；旧解析 Entry 原文同段 19/32、旧真正 company+role 字段同条均正确仅 10/32。WorkBlock 独有补回 4 组，但也漏掉旧解析 6 组；原文区域候选并集 23/32，不等于自动字段解析准确率。独立开发对照不足以放行生产；冻结集和正式评分/上传均未改。相关代码、测试和失败门禁在 `docs/WORKBLOCK_REGION_DEV_20261019.md`。下一步按同源多版式样本比较成熟区域解析引擎，拒绝继续堆积日期正则。
- 本轮成熟版式引擎实际对照：不用 uv add，而在隔离 overlay 中运行与 PyMuPDF 1.28.2 匹配的 PyMuPDF4LLM 1.28.2，以第三方 JSON 的版式区域、页码和行坐标构建候选 WorkBlock；仅在先前开发池 21–35 的 15 PDF / 32 组独立 GT 上评价，同块公司—职位覆盖 **9/32**，低于现有原生坐标 WorkBlock 17/32 和旧 Entry 原文 19/32。该适配器不推广、未改正式上传或五维评分，36–40 / 41–60 / 历史固定 20 PDF 均未读取。PyMuPDF4LLM 当天的 2.0 是空兼容包；1.28.2 属于 AGPL/商业双许可，当前不随产品分发。详情见 docs/LAYOUT_ENGINE_ISOLATED_20261019.md。下一步应进行真正的 Docling CPU 区域识别对照，而不是再次堆积关键词。
- PyMuPDF4LLM JSON→WorkBlock 损失归因：15 份开发 PDF 的 32 组独立 GT 配对中，模型原文保留 29 组，旧章节适配却仅保留同块 9 组。把未知排版标题作为非强制截断的离线消融可恢复至 17 组，但无一超过原生 PyMuPDF 的 17 组，且 27 候选中 11 个缺少 GT 配对支持。该消融未达发布门槛，默认旧安全策略不变、不改生产，详见 docs/LAYOUT_ENGINE_ISOLATED_20261019.md。
- No external DeepSeek expense was incurred for this development slice; do not push GitHub until explicitly requested.

Do not push GitHub until explicitly requested. Use branch feat/r7-r10-candidate-diagnostics.
