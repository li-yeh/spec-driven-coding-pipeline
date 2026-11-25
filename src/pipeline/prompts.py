from __future__ import annotations

from collections.abc import Iterable

from pipeline.config import (
    DEFAULT_ARCHIVE_ROUTES,
    DEFAULT_PROMPT_LANGUAGE,
    normalize_prompt_language,
)


def _use_zh(lang: str) -> bool:
    return normalize_prompt_language(lang) == "zh-TW"


def stage1_plan_prompt(
    domains: Iterable[str] | None = None,
    *,
    lang: str = DEFAULT_PROMPT_LANGUAGE,
) -> str:
    domain_list = list(domains) if domains is not None else list(DEFAULT_ARCHIVE_ROUTES.keys())
    domains_str = ", ".join(domain_list)

    if _use_zh(lang):
        return f"""
請閱讀當前目錄下的 `_CLEAN_SPEC.md`（規格書）、`_FILE_TREE.txt`（已過濾 IDE 雜訊的檔案清單）、`_AVAILABLE_TOOLS.txt`（本機已安裝的驗證工具）與 `_AVAILABLE_MODELS.txt`（當下可用的模型代號清單）。
若 `_CLEAN_SPEC.md` 內標註有 `_spec_page_*.png` 視覺輔助頁，請一併檢視對應圖檔，避免遺漏方框圖、時序圖或彩色強調標註。
**禁止修改、刪除或搬移任何既有檔案與目錄結構**，請在當前目錄建立純 JSON 檔案 `_PLAN.json`，格式如下：
{{
  "domain": "從 [{domains_str}] 中擇一",
  "spec_summary": "條列所有核心功能、介面定義、極性/格式規範與邊界條件",
  "execution_mode": "單檔高耦合(如狀態機/核心引擎)選 SINGLE_STRONG；多檔低耦合模組專案選 BATCH_FAST",
  "test_command": "僅從 _AVAILABLE_TOOLS.txt 已安裝的工具組合本機編譯與測試指令（注意檔案相對路徑）",
  "models": {{
    "implement":        {{"model": "從 _AVAILABLE_MODELS.txt 逐字挑選高推理代號，無合適則填 auto", "effort": "high"}},
    "batch_worker":     {{"model": "從 _AVAILABLE_MODELS.txt 逐字挑選輕量高速代號，無合適則填 auto", "effort": "medium"}},
    "debug":            {{"model": "從 _AVAILABLE_MODELS.txt 逐字挑選代號或 auto", "effort": "medium"}},
    "debug_escalation": {{"model": "從 _AVAILABLE_MODELS.txt 逐字挑選最強推理代號或 auto", "effort": "high"}},
    "goldfish":         {{"model": "從 _AVAILABLE_MODELS.txt 逐字挑選最強推理代號或 auto", "effort": "high"}}
  }},
  "implementation_prompt": "給 SINGLE_STRONG 模式的精確執行指令（寫明要原地修改/新增的檔案完整相對路徑、須保留的既有介面與註解、須避開的陷阱）",
  "skeleton_prompt": "僅 BATCH_FAST 模式需要：先鎖死各檔案介面/標頭檔/Port 簽章的指令（不寫實作）",
  "sub_tasks": ["僅 BATCH_FAST 模式需要：按相依順序切分的子 Prompt 陣列，每個子任務專注實作單一獨立檔案"]
}}
嚴格規則：`_PLAN.json` 必須為合法純 JSON（勿加 Markdown 標記）；所有 `model` 欄位值必須為 `_AVAILABLE_MODELS.txt` 中的單一純代號或 `"auto"`。
"""

    return f"""
Read `_CLEAN_SPEC.md` (specification), `_FILE_TREE.txt` (noise-filtered project file tree), `_AVAILABLE_TOOLS.txt` (installed local build/test tools), and `_AVAILABLE_MODELS.txt` (currently available model IDs) in the working directory.
If `_CLEAN_SPEC.md` references any rendered `_spec_page_*.png` visual pages, inspect those images as well so you do not miss block diagrams, timing diagrams, or color-highlighted constraints.
**Do NOT modify, delete, or move any existing files or directories.** Create a valid plain JSON file named `_PLAN.json` in the current directory with the following schema:
{{
  "domain": "Choose one from [{domains_str}]",
  "spec_summary": "Concise bullet summary of all core requirements, interfaces, polarity/format rules, and edge cases",
  "execution_mode": "Use SINGLE_STRONG for tightly coupled single-file cores (e.g., FSM/engine); use BATCH_FAST for loosely coupled multi-file modules",
  "test_command": "Local build/test command composed strictly from tools listed in _AVAILABLE_TOOLS.txt (using accurate relative paths)",
  "models": {{
    "implement":        {{"model": "Exact model ID from _AVAILABLE_MODELS.txt for high-reasoning implementation, or auto", "effort": "high"}},
    "batch_worker":     {{"model": "Exact lightweight/fast model ID from _AVAILABLE_MODELS.txt, or auto", "effort": "medium"}},
    "debug":            {{"model": "Exact model ID from _AVAILABLE_MODELS.txt, or auto", "effort": "medium"}},
    "debug_escalation": {{"model": "Exact strongest reasoning model ID from _AVAILABLE_MODELS.txt, or auto", "effort": "high"}},
    "goldfish":         {{"model": "Exact strongest reasoning model ID from _AVAILABLE_MODELS.txt, or auto", "effort": "high"}}
  }},
  "implementation_prompt": "Precise execution instructions for SINGLE_STRONG mode (exact relative paths to create/edit in place, existing interfaces/comments to preserve, pitfalls to avoid)",
  "skeleton_prompt": "BATCH_FAST only: instructions to lock cross-file interfaces, headers, or port signatures first without full implementation",
  "sub_tasks": ["BATCH_FAST only: dependency-ordered array of focused sub-prompts, each implementing one independent file"]
}}
Strict rules: `_PLAN.json` must be valid raw JSON (no Markdown fences). Every `model` value must match a single ID verbatim from `_AVAILABLE_MODELS.txt` or be `"auto"`.
"""


def stage2_audit_plan_prompt(*, lang: str = DEFAULT_PROMPT_LANGUAGE) -> str:
    if _use_zh(lang):
        return """
你是嚴苛的技術審查員。請忘記之前所有假設，逐條比對 `_CLEAN_SPEC.md`、`_FILE_TREE.txt`、`_AVAILABLE_MODELS.txt` 與剛產出的 `_PLAN.json`：
1. 【結構保護檢查】：核對實作計畫與 `_FILE_TREE.txt`，確保不會刪除、搬移、重新命名或重組任何既有資料夾與檔案，僅在原檔案路徑進行必要實作。
2. 【模型代號檢查】：確認 `models` 內所有代號皆逐字出現在 `_AVAILABLE_MODELS.txt`，否則改為 `"auto"`。
3. 【規格對齊檢查】：核對 `_CLEAN_SPEC.md` 所有要求（演算法、介面、極性、邊界條件、格式對齊與特殊字串），確保實作計畫完全覆蓋且未被舊範本註解誤導。
請直接原地修訂並覆寫合法的純 JSON 至 `_PLAN.json`。
"""

    return """
You are a strict independent technical auditor. Discard all prior assumptions and cross-check `_CLEAN_SPEC.md`, `_FILE_TREE.txt`, `_AVAILABLE_MODELS.txt`, and `_PLAN.json`:
1. [Structure Protection]: Verify against `_FILE_TREE.txt` that the plan never deletes, moves, renames, or restructures existing files or directories, and performs edits strictly in place.
2. [Model ID Validation]: Verify that every model ID in `models` appears verbatim in `_AVAILABLE_MODELS.txt`; replace any invalid entry with `"auto"`.
3. [Specification Alignment]: Verify that all requirements in `_CLEAN_SPEC.md` (algorithms, interfaces, polarities, edge cases, formatting, and exact tokens) are fully covered without being misled by stale starter comments.
Revise and overwrite `_PLAN.json` in place with valid raw JSON.
"""


def stage4_single_impl_prompt(
    spec_summary: str,
    impl_prompt: str,
    *,
    lang: str = DEFAULT_PROMPT_LANGUAGE,
) -> str:
    if _use_zh(lang):
        return f"""
請閱讀 `_CLEAN_SPEC.md` 並嚴格依下方已驗證藍圖完成程式碼實作：

【規格摘要】：
{spec_summary}

【實作指令】：
{impl_prompt}

要求：
1. 修改任何既有原始碼前，先複製一份同名的 `.bak` 備份。
2. **嚴格保留原本的資料夾與檔案結構**：嚴禁刪除、搬移或重新命名既有檔案與目錄；保留原本檔案的模組/函式介面名稱與原有註解，除非規格書明確要求更動。
3. **嚴禁修改任何既有的 Testbench、既定測試檔或黃金測資檔**（如 `*_tb.*`、`tb_*.*`、`test_*.*`、`.mem`/`.dat` 基準答案）。
4. 專注把邏輯寫乾淨正確，完成後即結束。
"""

    return f"""
Read `_CLEAN_SPEC.md` and implement the solution strictly according to the audited blueprint below:

[Specification Summary]
{spec_summary}

[Implementation Instructions]
{impl_prompt}

Requirements:
1. Before modifying any existing source file, create a `.bak` backup copy alongside it.
2. **Strictly preserve the original directory and file layout**: never delete, move, or rename existing files or folders; keep existing module/function signatures and comments unless explicitly changed by the specification.
3. **NEVER modify existing testbenches, predefined test suites, or golden test data** (e.g., `*_tb.*`, `tb_*.*`, `test_*.*`, `.mem`, `.dat`).
4. Focus on clean, correct logic and stop once implementation is complete.
"""


def stage4_skeleton_prompt(
    skeleton_prompt: str,
    *,
    lang: str = DEFAULT_PROMPT_LANGUAGE,
) -> str:
    if _use_zh(lang):
        return f"""
請閱讀 `_CLEAN_SPEC.md` 並先建立／鎖定專案的檔案結構與介面骨架：
{skeleton_prompt}
要求：修改既有檔案前先留存 `.bak` 備份；此步驟只需定死介面與簽章，切勿寫入完整商業邏輯；**嚴格維持原有目錄結構，嚴禁刪除既有檔案，且嚴禁修改任何既有的 Testbench、既定測試檔或黃金測資檔**。
"""

    return f"""
Read `_CLEAN_SPEC.md` and establish/lock the project interface skeleton first:
{skeleton_prompt}
Requirements: Back up any existing file to `.bak` before editing. Lock interfaces, headers, and signatures only without writing full business logic. **Strictly preserve the existing directory layout, never delete existing files, and NEVER modify existing testbenches, predefined test suites, or golden test data.**
"""


def stage4_batch_worker_prompt(
    task_prompt: str,
    idx: int,
    total: int,
    *,
    lang: str = DEFAULT_PROMPT_LANGUAGE,
) -> str:
    if _use_zh(lang):
        return f"""
請閱讀 `_CLEAN_SPEC.md` 與專案現有介面骨架，完成第 {idx}/{total} 個子任務：
{task_prompt}
要求：僅實作本子任務負責的檔案，嚴禁更動已鎖定的跨檔案介面簽章，**嚴禁刪除或搬移原有檔案與資料夾，且嚴禁修改任何既有的 Testbench、既定測試檔或黃金測資檔**；修改既有檔案前若尚無 `.bak` 請先備份。
"""

    return f"""
Read `_CLEAN_SPEC.md` and the locked interface skeleton, then complete sub-task {idx}/{total}:
{task_prompt}
Requirements: Implement only the file(s) assigned to this sub-task. Do not alter locked cross-file signatures. **Never delete or move existing files/directories, and NEVER modify existing testbenches, predefined test suites, or golden test data.** Create a `.bak` backup before editing an existing file if one does not already exist.
"""


def stage5_debug_prompt(
    test_cmd: str,
    round_idx: int,
    prev_log: str = "",
    *,
    lang: str = DEFAULT_PROMPT_LANGUAGE,
) -> str:
    if _use_zh(lang):
        retry_note = f"\n【上一輪未通過紀錄，請優先針對此問題排查】：\n{prev_log[-2000:]}\n" if prev_log else ""
        return f"""
請閱讀 `_CLEAN_SPEC.md`，在終端機實際編譯並執行測試驗證目前程式碼（第 {round_idx} 輪除錯）：
1. 建議執行指令：`{test_cmd or "請依 _AVAILABLE_TOOLS.txt 選用合適的本機編譯與測試工具"}`
2. **嚴禁修改任何既有的 Testbench、既定測試檔、驗收腳本或黃金測資檔**；若測試不通過，只能修正待測實作程式碼（DUT／原始碼）。
3. **嚴格保留原專案目錄結構**：若專案沒有測試檔或現有測試覆蓋不足，請一律將臨時測試檔與模擬產物（如 `sim.out`、`*.vcd`）建在專案根目錄下的 `_ai_tmp/` 資料夾內（例如 `_ai_tmp/tb_tmp.v` 或 `_ai_tmp/test_tmp.py`），絕不污染既有目錄，更不可刪除原專案內任何檔案。
4. 若編譯報錯、出現警告或實測結果與 `_CLEAN_SPEC.md` 不符，請直接修改待測程式碼重跑，直到全部通過。
5. 測試全數通過後，請清理 `_ai_tmp/` 內的暫存輸出檔（收尾管線也會自動移除整個 `_ai_tmp/`）。
{retry_note}
最後一行必須明確輸出 `[TESTS: PASSED]`（若無法解決則輸出 `[TESTS: FAILED]` 並簡述原因）。
"""

    retry_note = (
        f"\n[Previous Round Failure Log — Prioritize Fixing This]:\n{prev_log[-2000:]}\n"
        if prev_log
        else ""
    )
    return f"""
Read `_CLEAN_SPEC.md`, then build and run local verification tests against the current implementation (Debug Round {round_idx}):
1. Suggested command: `{test_cmd or "Select appropriate installed build/test tools from _AVAILABLE_TOOLS.txt"}`
2. **NEVER modify existing testbenches, predefined test suites, acceptance scripts, or golden test data.** If tests fail, fix only the implementation code under test (DUT / source code).
3. **Strictly preserve the original repository layout**: if no tests exist or coverage is insufficient, place any temporary test harnesses and build/simulation artifacts (e.g., `sim.out`, `*.vcd`) exclusively inside `_ai_tmp/` at the project root (e.g., `_ai_tmp/tb_tmp.v` or `_ai_tmp/test_tmp.py`). Never pollute existing directories or delete original files.
4. Fix any compilation errors, warnings, or behavior mismatches against `_CLEAN_SPEC.md` and re-run until all checks pass.
5. After all tests pass, clean up temporary outputs inside `_ai_tmp/` (the pipeline will also remove `_ai_tmp/` during finalization).
{retry_note}
Your final line MUST output `[TESTS: PASSED]` (or `[TESTS: FAILED]` with a brief root-cause explanation if unresolved).
"""


def stage6_goldfish_prompt(*, lang: str = DEFAULT_PROMPT_LANGUAGE) -> str:
    if _use_zh(lang):
        return """
你是一位冷酷、完全沒參與過前期開發的外部審查員（像金魚一樣沒有舊對話包袱）。請嚴格使用繁體中文，對照 `_CLEAN_SPEC.md` 審查專案內所有修改或新增的程式碼，並依序執行以下三階段：

## 階段一：抓取隱含假設（金魚視角）
忘記任何開發過程假設，只看程式碼與 `_CLEAN_SPEC.md`，盤點所有未驗證的脆弱假設與漏洞——特別檢查「測試能過但違反規格書、硬體不可合成（RTL 含 `#delay`、推論出 Latch、Reset 極性錯誤、未初始化訊號）、並發競態條件、記憶體洩漏、邊界溢位或輸出格式不對齊」。

## 階段二：紅隊對抗與自我推翻
針對階段一每個疑點，嘗試反駁並推翻它：
- 若在現有架構／型別／規格下不可能發生（誤報），直接丟棄。
- 若無法推翻（真實缺陷），列出具體觸發條件（PoC，若需撰寫臨時測試檔或模擬產物請一律放在 `_ai_tmp/` 內），直接原地修改**待測實作程式碼**（**嚴禁修改既有的 Testbench、既定測試檔、黃金測資檔，或刪除／搬移既有檔案與目錄結構**）並重跑一次測試確認無誤。

## 階段三：輸出精煉審查報告
僅列出無法推翻的真實問題與最終處理結果（含檔案與行號、違反的假設、觸發情境與修復摘要）。
若確認最終程式碼 100% 符合 `_CLEAN_SPEC.md` 且無任何殘留真實缺陷，請在回覆最後一行輸出 `[STATUS: VERIFIED]`。
"""

    return """
You are a ruthless, independent external code reviewer with zero memory of prior development conversations (Goldfish perspective). Review all modified or newly added code strictly against `_CLEAN_SPEC.md` in three phases:

## Phase 1: Surface Hidden Assumptions (Goldfish Perspective)
Drop all prior assumptions and inspect only the code and `_CLEAN_SPEC.md`. Inventory every unverified assumption or potential defect—specifically checking for passing tests that silently violate the spec, unsynthesizable RTL (`#delay`, inferred latches, reset polarity mismatches, uninitialized signals), race conditions, memory/resource leaks, boundary overflows, and output formatting mismatches.

## Phase 2: Adversarial Falsification & Targeted Remediation
Attempt to disprove every candidate issue from Phase 1:
- If it cannot occur under the actual architecture, types, or spec (false positive), discard it immediately.
- If it cannot be disproven (verified defect), provide a concrete trigger/PoC (placing any temporary test scripts or simulation artifacts exclusively inside `_ai_tmp/`), fix only the **implementation code under test** in place (**NEVER modify existing testbenches, predefined test suites, golden test data, or delete/move existing files and directories**), and re-run verification tests to confirm the fix.

## Phase 3: Concise Final Review Report
List only verified issues and their resolution (file path, line range, violated assumption, trigger scenario, and fix summary).
If the final codebase satisfies 100% of `_CLEAN_SPEC.md` with zero remaining verified defects, output `[STATUS: VERIFIED]` on the final line.
"""
