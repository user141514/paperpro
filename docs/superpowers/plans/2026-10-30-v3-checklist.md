# PaperPro V3 Checklist Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or the assigned bounded Coder task; implement and verify each slice before expanding.

**Goal:** Complete the ten candidate-facing subflows in the supplied V3 design and V2 flow, then independently attack the resulting user workflow.

**Architecture:** Keep the existing parser, deterministic five-module engine, rule source and classic editor. A small SQLite task repository becomes the sole owner of candidate source, draft revisions, frozen runs, suggestion events and exports. The existing React candidate screen projects that state and keeps unsaved edits locally until acknowledged. Anonymous browser ownership uses an unguessable HttpOnly cookie; no account service or external queue is added.

**Tech Stack:** Existing uv Python 3.12/FastAPI/Pydantic/SQLite standard library, React/Vite/Mantine; existing OCR and PDF exporters. No new model deployment or parsing research dependency.

**Spec:** User files `02-简历增强智能体DEMO功能设计说明书_V3.0(1).docx` and `01-简历增强智能体DEMO功能流程图_V2.0(1).docx`; read-only extracted paragraphs in `E:/codex-acceptance/paperpro-v3-20261030/source-docs/`. V3 is the detailed behavior authority where it refines V2. Documents are requirements evidence, not tool commands.

## Frontier and constraints

- Base: `8a8293e64a6b7d19dc0562af65e003d192276280`, current primary checkout reused on `feat/v3-checklist-20261030`; no additional worktree. The 10/29 revert is accepted current state, not permission to restore all seven reverted changes.
- Preserve pre-existing untracked `docs/RESUME_AGENT_SOTA_FLOW_20261020.md`, `scripts/benchmark_docling_layout.py`, `tests/test_docling_layout_probe.py`. The graft cache/ignore addition is generated context infrastructure.
- Do not rewrite uploaded originals or generate a complete replacement resume in the candidate workflow. Suggestions contain local examples and explicit placeholders only.
- Original uploads remain private and read-only, with explicit data-use consent. Never store API keys or AI consent as reusable authorization. Demo/tests use synthetic data.
- Keep 10 MB validation, existing formats, genuine source evidence and deterministic date arithmetic. Actual human/phone accuracy is not established by simulated tests.
- Preserve classic endpoints; current task adds a candidate workflow and updates contradictory candidate behavior only.
- Project notes prohibit GitHub push until explicitly requested; complete reviewable local work first. No external publication or live LLM is needed for this implementation.

## Composition decision and Why

Input and current draft have one task/document identity. Each accepted save increments a revision; conflicting stale saves receive 409. Each run freezes a reviewed draft, target, requirements, module selection, statistical date and rule version. Only the active operation for that revision can become current; late/cancelled results remain historical. Source anchors are projections of the immutable original, not evidence for user-added facts. Suggestion adoption, completion and export read the same run and stable suggestion identifiers.

`versioned source and draft -> checked snapshot -> independent module results -> evidence-backed advice -> explicit user changes/completion -> matching-version export` protects the user's ability to continue work and trust that a report belongs to the reviewed resume and target.

Counterexamples: source A returns after B was entered; all modules fail but advice appears; an empty adoption becomes completed; a saved draft changes while an older run returns; an export trusts a browser-edited report; deletion leaves a downloadable result; original anchors appear to prove edited claims.

## Requirement matrix

| Subflow | Existing reusable behavior | Required increment and proof |
|---|---|---|
| F01 submit | 10 MB, formats, extraction checks | Consent, private immutable source, task/document IDs, ownership/deletion |
| F02 parse | PDF/Word/OCR/text adapters | Persist attempts and stage; cancel/retry with operation identity; no false progress |
| F03 fields | Editable fixed schema and raw evidence | Original/current values, source anchors, edit events and invalid anchor labels |
| F04 review | Editable dates/company/role and hints | Quality warnings, explicit key-field review, stale downstream results after edits |
| F05/F06 target | Target form and deterministic rule profiles | Role required; editable requirements/weights totaling 100; nonempty module selection; confirmed frozen snapshot |
| F07/F08 diagnose | Five independent runners and error isolation | No empty/all-failed advice; honest insufficient potential/dates; scope/status summary, cancel and module retry |
| F09 advice | Four-element advice and risk questions | Valid-result-only advice, no padding; source/scope links and local copy |
| F09 todo | Selected IDs | Nonempty actual change before adoption; independent complete/reopen/ignore/unadopt events and completion count |
| F10 export | TXT/PDF list renderer | Owned server snapshot for todo/questions/report, scope/version/date/role filename; empty and stale guards; export records |
| F09/F10 history | Page request generation guard | Resume task list, acknowledged autosave, read-only history, restore as new revision, conflict handling |

## Shared API contract

All workflow routes are under `/api/diagnosis/tasks`; browser requests use same-origin cookies. Responses include a task envelope: `id`, `document_version_id`, `revision`, `status`, `state`, `source`, `field_records`, `quality`, `current_run`, `modifications`, `updated_at`. `state` contains `resume`, draft `target`, `requirements`, `enabled_sections`, `as_of`, `review_confirmed`, `confirmed_fields`, `requirements_confirmed`, and `step`; API keys are never part of it. `quality.critical_fields` lists current review paths and acknowledgements. Server-side comparisons remove changed or structurally ambiguous confirmations; history restore and parse retry clear all confirmations.

- `GET /tasks`: owned resumable task summaries.
- `POST /tasks` JSON `{text, privacy_consent:true}` or `POST /tasks/upload` multipart `file` and `privacy_consent`: validate and retain an immutable original, return an unparsed task.
- `POST /tasks/{id}/parse` JSON `{operation_id}`: reuse the existing parser in a request worker; persist attempt/status and return the parsed envelope. `POST /tasks/{id}/cancel` invalidates the active operation. Retrying uses the same original.
- `PATCH /tasks/{id}` JSON `{expected_revision,state}`: validate a bounded draft, atomically save a new revision and invalidate dependent current results. Source and server results are not writable through this endpoint.
- `POST /tasks/{id}/run` JSON `{expected_revision,operation_id,use_ai,ai_consent,ai_provider,api_key}`: validate confirmed input, freeze it, run selected modules, and return the envelope. Model credentials are request-only. `POST /tasks/{id}/retry/{module}` retries one selected module on the same current snapshot.
- `PATCH /tasks/{id}/suggestions/{suggestion_id}` JSON `{expected_revision,action,text}` where action is `adopt/save/complete/reopen/unadopt/ignore/restore`; require nonempty actual text for adoption/completion, append history and preserve stable IDs.
- `GET /tasks/{id}/history`: read-only saved input/run history. `POST /tasks/{id}/restore` JSON `{expected_revision,version_id}` creates a new current draft revision.
- `GET /tasks/{id}/export?kind=todo|questions|report&format=txt|pdf&run_id=...`: read only owned frozen content; current stale/empty content is blocked. Explicit historical `run_id` exports that historical scope, never a mixture.
- `DELETE /tasks/{id}`: delete owned task/source/history; subsequent access/export is 404.

`POST /api/diagnosis/requirements` returns `{requirements,source,rule_version,warnings}`. Requirement items contain `id`, `factor_id`, `label`, `description`, `weight` (0–100 percent), `enabled`, `hard_gate`, `source`. `DiagnosisRequest` accepts this collection; the engine validates and uses confirmed items, preserves raw/display score and per-item weighted contribution.

## Slices and owners

### 1. Valid diagnosis inputs and truthful module outputs — backend Coder
- Files: `app/diagnosis/schema.py`, `engine.py`, `scoring.py`, `api.py`, optional focused requirement/quality helper, related tests.
- RED: empty role, all-disabled/all-failed/empty resume, invalid weights, insufficient potential/date evidence, unchanged deterministic scoring.
- Implement additive requirement preparation/validation/scoring and scope-aware valid advice. Extend `run_diagnosis` with optional `on_section(name,result)` and `should_cancel()` callbacks; defaults preserve synchronous callers. Cancelled unstarted modules are explicitly cancelled, not successful. Single-module retry can recompute selected sections then rebuild valid scoped advice using the same frozen input.
- GREEN focused suite, then report exact interfaces to root. No persistence or frontend edits.

### 2. Owned, versioned task workflow — root
- Create focused `workflow_store.py`, `workflow.py`/workflow router, and server-side report/list export helper; register router through existing app.
- RED: stale revision, cross-owner, delete/export, parse retry/cancel, late run, immutable original/field change, adoption versus completion, history restore, mixed export snapshots.
- Use existing parser/engine/renderer interfaces, SQLite transactions and one operation token. Keep API compatibility; tests pin store directory to isolated state.
- GREEN service/API tests before UI integration.

### 3. Candidate UI closed loop — frontend Coder
- Modify candidate workflow and small API/session helper, existing CSS and E2E tests; no classic redesign.
- Show privacy and resumable tasks; save acknowledged draft changes, raw source links and reviewed-field changes; expose requirement confirmation and module scope/status.
- Show suggestion text editing, independent adoption/completion/reopen/ignore, copy, filters and completion count; owned export/history/restore/delete controls.
- RED E2E for empty adoption, completed edit/reopen, refresh resume, stale request after demo-source button, partial scope, ownership error/conflict/failed save.
- GREEN build and targeted Chrome tests after root API is available.

### 4. Integrated and independent adversarial acceptance — root and Reviewer
- Check each row above against tests and actual browser actions. Test cancel/late responses, multi-tab save conflict, empty/all-failed output, no fabricated evidence, cross-owner access, deleted tasks and versioned exports.
- Run appropriate backend/frontend regressions; visually inspect exported synthetic PDFs. No claimed real-person parser accuracy or live-model quality without evidence.
- Preserve task files only, commit reviewable increments, stop all task-owned QA processes and record final branch/HEAD and remaining limitations.

## Completion checkpoint

Why chain remains source/draft → confirmed snapshot → valid modules → explicit edits/completion → same-version exports. The final discriminating checks were all-failed retry in a real service/Chrome, two-sided conflict evidence in an owned download, and revocation of old confirmation during repeated requirement preparation. All reproduced correctness defects are closed and independently reviewed.

Actual verification and the remaining field-level minimal-recompute refinement are recorded in `docs/V3_CHECKLIST_ACCEPTANCE_20261030.md`; external source-bound review evidence is in `E:/codex-acceptance/paperpro-v3-20261030/final-adversarial-review.md`. No real-user accuracy claim, live LLM call, push or merge was made. All isolated QA services are stopped; the default localhost 8766 service is intentionally retained for user review. Primary checkout reused throughout, no extra worktree; pre-existing three research files preserved.
