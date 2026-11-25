# Spec-Driven Autonomous Coding Pipeline

**English** | [繁體中文](README.zh-TW.md)

A **spec-driven**, 6-stage autonomous coding and stateless red-team review pipeline built on **Python Watchdog**, **PyMuPDF visual detection**, and **Antigravity CLI (`agy`)**. Drop a project folder containing a technical specification (`.pdf` or `spec.md`), and the pipeline automates specification ingestion, dynamic model routing, plan auditing, implementation, local build/test verification, stateless review, and domain-based archiving inside an isolated sandbox.

---

## Key Features

- **6-Stage Sandbox Isolation**: Executes every task inside a clean `active_sandbox/` workspace, preserving the full repository hierarchy while strictly forbidding edits to existing testbenches, predefined test suites, or golden test data.
- **Generic PDF Visual Element Detection**: Uses `pymupdf` to scan every specification page for **raster images**, **vector graphics** (block diagrams, timing waveforms, tables), and **colored emphasis text**, selectively rendering only visual pages to `_spec_page_*.png` while whitespace-compressing text-only pages.
- **Dynamic Model Routing with `auto` Fallback**: Queries `agy models` live on each run and assigns stage-appropriate reasoning models and effort levels. If a dynamically selected model fails, execution automatically retries with `agy` built-in `auto`.
- **Stateless Red-Team Review (Goldfish Review)**: Launches fresh, memoryless review processes in Stage 2 (blueprint audit) and Stage 6 (final code review) to eliminate confirmation bias, producing `AI_FINAL_REVIEW.md` via assumption extraction, adversarial falsification, and targeted remediation.
- **Bilingual Prompt Switching (`en` / `zh-TW`)**: Switch all 6 stage prompts and review reports between English and Traditional Chinese with a single `prompt_language` setting in `config.yaml`.
- **Externalized Config & Environment Diagnostics**: Manage all paths and archive routes via `config.yaml` (or `PIPELINE_CONFIG`), and verify your setup in one command with `python -m pipeline --doctor`.

---

## 6-Stage Architecture

```text
dropzone/<task_folder>/      (Contains .pdf or spec.md plus any project hierarchy)
         │
         ▼
[Stage 0] Sandbox Initialization & Snapshot (prep.py)
         ├─ Reset active_sandbox/ and copy full layout (temporarily excluding .pdf)
         ├─ Extract & compress spec via PyMuPDF; render visual pages to _spec_page_*.png
         └─ Generate _CLEAN_SPEC.md / _FILE_TREE.txt / _AVAILABLE_TOOLS.txt / _AVAILABLE_MODELS.txt
         │
         ▼
[Stage 1] Planning & Dynamic Model Selection (agy auto, effort=high)
         └─ Emit structured _PLAN.json (domain, execution_mode, test_command, stage models)
         │
         ▼
[Stage 2] Stateless Plan & Structure Audit (agy auto, effort=high)
         └─ Fresh process verifies layout safety, valid model IDs, and spec coverage
         │
         ▼
[Stage 4] Adaptive Implementation (creates .bak backups; never modifies existing tests)
         ├─ SINGLE_STRONG : Single-shot high-reasoning pass for tightly coupled cores
         └─ BATCH_FAST    : 4a locks cross-file interfaces → 4b implements sub-tasks sequentially
         │
         ▼
[Stage 5] Local Build & Iterative Debugging (scratch tests isolated under _ai_tmp/)
         ├─ Round 1 : Run verification command using debug model
         └─ Round 2 : Auto-escalate to debug_escalation model if [TESTS: PASSED] is absent
         │
         ▼
[Stage 6] Goldfish Stateless Red-Team Review
         └─ Surface assumptions → disprove false positives & fix verified defects → AI_FINAL_REVIEW.md
         │
         ▼
[Archive] Clean control files, _spec_page_*.png, and _ai_tmp/; restore original .pdf files
         ├─ Contains [STATUS: VERIFIED] → Archive by domain via archive_routes; move drop to processed_drops/
         └─ Unverified or aborted       → Preserve full workspace in needs_review/ for manual handoff
```

---

## Design Trade-offs

### 1. Coupling-Aware Execution: `SINGLE_STRONG` vs. `BATCH_FAST`
- **Tightly coupled cores** (such as RTL finite-state machines or concurrent synchronization engines) exhibit dense cross-line invariants where splitting work across turns risks state-transition or lock-ordering bugs. `SINGLE_STRONG` delegates the entire core to a single high-reasoning pass.
- **Loosely coupled multi-file projects** suffer from output truncation and context dilution in one-shot prompts. `BATCH_FAST` locks headers/interfaces first in Stage 4a, then dispatches lightweight workers per file in Stage 4b—balancing correctness, latency, and token cost.

### 2. Stateless Review & Path-Boundary Guardrails Before Deletion
- Long multi-turn coding sessions accumulate confirmation bias, increasing the risk of code that passes shallow tests while violating subtle spec clauses. Spawning a stateless **Goldfish Review** process drops prior conversation history and challenges every assumption from scratch.
- For cleanup utilities (`safe_clean_junk`), strict guardrails reject empty patterns, wildcards (`*`, `*.*`), parent traversal (`..`), and absolute paths, protect all `CONTROL_FILES`, and enforce `Path.resolve().is_relative_to(root)` to block symlink escapes outside the sandbox.
- `_FILE_TREE.txt` filters IDE caches and logs **non-destructively** rather than deleting workspace files, guaranteeing the archived deliverable retains its exact original structure.

### 3. Visual-Selective PDF Extraction via `pymupdf`
- Rendering every page of a long specification to images inflates multimodal token usage and latency, whereas plain text extraction (`pypdf`) misses architectural diagrams, timing charts, and color-coded warnings.
- Using `pymupdf` to inspect each page locally for raster images, vector paths, and non-grayscale text spans lets the pipeline render **only** visually meaningful pages to PNG while compressing plain-text pages (gracefully falling back to `pypdf` if `pymupdf` is unavailable).

---

## Project Structure

```text
spec-driven-coding-pipeline/
├── src/pipeline/
│   ├── __init__.py
│   ├── __main__.py        # Enables `python -m pipeline`
│   ├── main.py            # Watchdog observer, sandbox orchestration, CLI (--doctor)
│   ├── prep.py            # PDF visual detection & compression, file tree, tool probing, safe cleanup
│   ├── agy_runner.py      # Headless agy CLI wrapper, live model discovery, auto fallback
│   ├── prompts.py         # Domain-agnostic 6-stage prompts with en / zh-TW switching
│   └── config.py          # YAML config loader with env override and safe defaults
├── skills/
│   └── goldfish-review/
│       └── SKILL.md       # Stage 6 stateless red-team review skill template
├── tests/
│   ├── test_prep.py       # Structure copy, file tree, sandbox boundary cleanup, PyMuPDF visual detection
│   ├── test_config.py     # YAML loading, env precedence, schema validation, fallback behavior
│   └── test_prompts.py    # Bilingual prompt switching and guardrail verification
├── examples/
│   └── token_bucket_demo/
│       └── spec.md        # Self-contained demo spec (Thread-Safe Token Bucket Rate Limiter)
├── scripts/
│   └── start.bat          # Minimal Windows launcher using local .venv
├── config.example.yaml    # Sanitized configuration template
├── pyproject.toml         # PEP 621 project metadata (Python >= 3.12)
├── .gitignore
├── LICENSE                # MIT License
├── README.md              # English documentation
└── README.zh-TW.md        # Traditional Chinese documentation
```

---

## Quick Start

### 1. Install Dependencies
Requires **Python >= 3.12** and an authenticated **Antigravity CLI (`agy`)**:

```bash
uv sync --extra dev
```

### 2. Create Local Configuration
Copy the template to `config.yaml` (ignored by Git so personal paths stay local):

```bash
# macOS / Linux / Git Bash
cp config.example.yaml config.yaml

# Windows PowerShell
Copy-Item config.example.yaml config.yaml
```

Set `prompt_language: "en"` (default) or `prompt_language: "zh-TW"` in `config.yaml` to permanently choose the language for agent prompts and `AI_FINAL_REVIEW.md`. You can also override it for a single run via `--lang`:

```bash
# Run with Traditional Chinese prompts & review output (overrides config.yaml)
uv run python -m pipeline --lang zh-TW

# Run with English prompts & review output
uv run python -m pipeline --lang en
```

You can also point to an alternate config file via `PIPELINE_CONFIG=/path/to/config.yaml` or `--config`.

### 3. Install the Goldfish Review Skill (Recommended)
Copy the included skill template into your local Gemini skills directory:

```bash
# macOS / Linux
mkdir -p ~/.gemini/skills/goldfish-review
cp skills/goldfish-review/SKILL.md ~/.gemini/skills/goldfish-review/SKILL.md

# Windows PowerShell
New-Item -ItemType Directory -Force "$HOME\.gemini\skills\goldfish-review" | Out-Null
Copy-Item skills\goldfish-review\SKILL.md "$HOME\.gemini\skills\goldfish-review\SKILL.md"
```

### 4. Run Environment Diagnostics (`--doctor`)
Verify your configuration, `agy` binary, Goldfish skill, and local build/test toolchain before launching:

```bash
uv run python -m pipeline --doctor
```

### 5. Launch the Pipeline & Try the Demo
Before the first run, open `agy` once inside your configured `sandbox_dir` to trust the folder, then start the pipeline:

```bash
uv run python -m pipeline
# Or via the installed entry point:
uv run spec-pipeline
```

On Windows, you may also run `scripts\start.bat`.

To test the pipeline end-to-end, copy the included demo task into `dropzone/`:

```bash
cp -r examples/token_bucket_demo dropzone/token_bucket_demo
```

---

## Running Unit Tests

```bash
uv run pytest
```

---

## Roadmap

- [x] 6-stage sandboxed pipeline with dynamic `agy models` routing
- [x] Stateless review (`/goldfish`) & PDF visual element detection
- [ ] Integrate local Ollama (3B) for log compression and pre-filtering
- [ ] Add GitHub Actions CI for automated `pytest` checks
- [ ] Fine-tune a lightweight local router model for strict JSON planning

---

## License

Released under the [MIT License](LICENSE).
