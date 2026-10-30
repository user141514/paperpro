# PaperPro · Resume Studio — Minimum Product Contract

> This is the classic editor contract. The candidate workflow added later is governed by the user-supplied 2026-10-30 V3 design and V2 flow, tracked in [V3 checklist](docs/V3_CHECKLIST_ACCEPTANCE_20261030.md). It adds explicitly consented local task persistence, reviewed target requirements, separate adoption/completion, version history and frozen report/list export. The classic editor's stateless/no-database boundary below does not prohibit that authorized candidate workflow.

## User goal
Create a local web agent at E:\company_work\paperpro. Upload a PDF, Word document (.docx/.doc), or scanned PNG/JPEG; extract evidence; review and improve the writing; generate a consistent professional resume in Word and PDF.

## User flow
1. Drop one supported file (<=12 MiB); keep originals untouched.
2. Extract text directly from PDF/DOCX, run OCR for scans and image-only PDF pages.
3. Structure the candidate's facts into editable name/contact/profile/skills/work/projects/education/other sections. Show the source text and warnings so omitted or misread evidence is recoverable.
4. Improve clarity with local safe cleanup by default. Optional external AI rewriting is explicit opt-in, with a user-supplied or provider-specific environment API key. The user can select DeepSeek (official deepseek-flash) or the configured OpenAI-compatible service. The chosen provider must never receive a different provider's server-side key. AI may suggest rewriting summaries/bullet wording but suggestions require explicit individual approval before changing the draft; identity, employers, schools, dates, qualifications and numeric claims remain protected.
5. Review an A4 fixed-format preview, then download DOCX and PDF. No resume data is saved by the server.

## Boundaries
- Exactly one fixed professional template (no template gallery, accounts, job scraping, database, vector store, agents orchestration, queue or background processing).
- Local-first: bind to localhost, do not send personal data to third parties without explicit request and a configured key. Read shareable settings.json and gitignored settings.local.json with explicit precedence; never commit a real key.
- Fail closed on unsupported/corrupt/oversize input, missing OCR or failed export. Never silently claim AI enhancement when no AI request was made.
- Preserve unknown, uncategorized text in editable 'Additional details' and raw evidence rather than discard it.
- Word is installed on this Windows host; use Microsoft Word for DOC conversion and DOCX-to-PDF when available; document a PDF fallback if COM fails.
- A generated resume is a **draft** until the user checks it against the source.

## Claim, model, invariant, counterexamples
**Claim:** One valid upload can result in a fact-reviewed, fixed-layout Word/PDF resume.
**Model:** Upload (untrusted bytes) → parse/OCR (raw evidence) → structured editable resume (draft) → optional controlled rewrite → fixed template renderer → download.
**Invariant:** No output exports a field not present in the current reviewed draft; extraction failure must not look like successful extraction; original stays unchanged; AI cannot change protected fields or add new numbers.
**Counterexamples:** Image-only PDF where native extraction is empty; Chinese PNG without Chinese OCR; DOCX with tables; resume with no section headings; corrupted ZIP posing as DOCX; malicious PDF; AI injects a new percentage; Word COM is installed but cannot be automated; layout spills onto second page.

## Acceptance
- Unit: section parsing (Chinese + English), preservation of unknown lines, protected fields/number checks, file validation.
- Smoke: DOCX→extract→enhance→DOCX/PDF; PNG OCR; PDF native and scanned.
- Integration: live FastAPI calls and actual browser upload/editor/preview/download, Word/PDF open and contain expected content.
- Full: responsive UI, error paths, file size and type limits, privacy/security, no hallucinated facts, regressions.
- Independent adversarial review after milestones; main agent adjudicates findings before implementing them.

## Technology
Python 3.12 + uv + FastAPI + python-docx + PyMuPDF + RapidOCR/Tesseract + pywin32 + reportlab fallback; React/Vite with Mantine and Tabler Icons. UI strings Chinese; technical docs in English.
