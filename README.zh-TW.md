# Spec-Driven Autonomous Coding Pipeline

[English](README.md) | **繁體中文**

一套以**技術規格書為單一真實來源（Spec-Driven）**的 6 階段自主開發與無狀態紅隊審查管線。結合 **Python Watchdog**、**PyMuPDF 視覺元素偵測** 與 **Antigravity CLI (`agy`)**，將「讀規格 → 動態規劃 → 結構審計 → 程式碼實作 → 真機驗證除錯 → 無狀態失憶審查 → 分類歸檔」自動化為可重複、可審計、具沙盒防護的本機工作流。

---

## 核心特色

- **6 階段沙盒隔離工作流**：所有任務於獨立的 `active_sandbox/` 內執行，完整保留原始目錄結構，並嚴格禁止修改既有的 Testbench、既定測試檔與黃金測資檔。
- **通用 PDF 視覺元素偵測與壓縮**：透過 `pymupdf` 掃描規格書 PDF，精準辨識**點陣圖（images）**、**向量圖形／方框／時序圖（vector graphics）**與**彩色強調文字（colored text）**，僅對包含關鍵視覺資訊的頁面輸出 `_spec_page_*.png` 供多模態檢視，其餘純文字頁則壓縮空白降本。
- **動態模型抓取與 `auto` 容災退回**：每次執行即時呼叫 `agy models` 取得帳號當下可用模型清單，依各階段複雜度動態指派推理模型與 `effort`；若指定模型呼叫失敗，自動退回 `agy` 內建 `auto` 重試，避免單點中斷。
- **無狀態失憶審查（Goldfish Review）**：在階段 2（藍圖審計）與階段 6（終極紅隊審查）啟動全新無記憶進程，剝除前期開發的確認偏誤，透過「抓取隱含假設 → 紅隊自我推翻 → 僅修復無法推翻的真實缺陷」三階段輸出 `AI_FINAL_REVIEW.md`。
- **中英雙語 Prompt 一鍵切換**：透過 `config.yaml` 中的 `prompt_language`（`"en"` / `"zh-TW"`），自由切換 6 階段 Prompt 與終極審查報告語言。
- **設定外置與一鍵環境健檢**：所有路徑與歸檔領域皆由 `config.yaml` 管理，並內建 `python -m pipeline --doctor` 快速檢查設定、CLI、Skill 與本機編譯／測試工具鏈。

---

## 6 階段架構流程圖

```text
dropzone/<task_folder>/      (內含規格書 .pdf 或 spec.md，以及任意層級專案原始碼)
         │
         ▼
[Stage 0] 沙盒初始化與環境快照 (prep.py)
         ├─ 清空 active_sandbox/，100% 保留目錄結構複製專案（暫排 .pdf，收尾還原）
         ├─ PyMuPDF 解析規格書：壓縮純文字 + 偵測向量圖/圖片/彩色文字並渲染關鍵頁
         └─ 產生 _CLEAN_SPEC.md / _FILE_TREE.txt / _AVAILABLE_TOOLS.txt / _AVAILABLE_MODELS.txt
         │
         ▼
[Stage 1] 專案規劃與動態選型 (agy auto, effort=high)
         └─ 產出結構化藍圖 _PLAN.json（領域分類、執行模式、測試指令、各階段模型配置）
         │
         ▼
[Stage 2] 失憶安全與結構保護審查 (agy auto, effort=high)
         └─ 獨立新進程核對 _PLAN.json：防止破壞既有結構、驗證模型代號與規格覆蓋度
         │
         ▼
[Stage 4] 動態實作（修改前先留存 .bak 備份，嚴禁修改既有 Testbench / 測試檔）
         ├─ SINGLE_STRONG：單發高推理模型實作高耦合核心模組
         └─ BATCH_FAST   ：4a 先鎖定跨檔介面骨架 → 4b 依相依順序分批實作子任務
         │
         ▼
[Stage 5] 真機編譯與迭代除錯（臨時測試與模擬產物統一隔離於 _ai_tmp/）
         ├─ Round 1：以 debug 模型實跑驗證指令
         └─ Round 2：若輸出不含 [TESTS: PASSED]，自動升級 debug_escalation 深度修復
         │
         ▼
[Stage 6] Goldfish 無狀態終極紅隊審查
         └─ 盤點隱含假設 → 紅隊推翻誤報並原地修復真實缺陷 → 產出 AI_FINAL_REVIEW.md
         │
         ▼
[Archive] 清理控制檔、_spec_page_*.png 與 _ai_tmp/，並精確還原原 .pdf
         ├─ 含 [STATUS: VERIFIED] → 依 domain 歸檔至 archive_routes，原包移入 processed_drops/
         └─ 未通過或異常中斷       → 完整現場保留至 needs_review/，供人工無縫接手
```

---

## Design Trade-offs

### 1. 為何依耦合度區分 `SINGLE_STRONG` 與 `BATCH_FAST`？
- **高耦合單檔／核心引擎（如硬體 RTL FSM、併發排程核心）**跨行狀態依賴極強，拆檔實作反而容易造成狀態機轉換或鎖序不一致，因此採用 `SINGLE_STRONG` 交由單次高推理模型全局通盤實作。
- **多檔低耦合模組專案**若全塞入單次對話，容易出現長輸出截斷與上下文稀釋；採用 `BATCH_FAST` 先於階段 4a 鎖死標頭檔／介面簽章，再於階段 4b 以輕量高速模型逐檔實作，在正確性、執行速度與 Token 成本之間取得平衡。

### 2. 為何在物理刪檔與收尾前加入失憶審查與路徑白名單防護？
- 單一長對話容易累積「確認偏誤」（模型傾向相信自己剛寫的程式碼沒問題），透過無狀態的 **Goldfish Review** 強制清空歷史脈絡，能有效攔截「測試碰巧通過卻違反規格書」的隱性缺陷。
- 針對清理工具 `safe_clean_junk()`，採用嚴格的路徑白名單檢查：拒絕空值、`*`、`*.*`、`..` 與絕對路徑，保護所有 `CONTROL_FILES`，並透過 `Path.resolve().is_relative_to(root)` 阻擋符號連結（symlink）或異常路徑逃逸出沙盒。
- 管線在階段 0 建置 `_FILE_TREE.txt` 時僅「邏輯過濾」IDE 快取與日誌雜訊，不物理刪除原始專案目錄，確保收尾歸檔的專案結構 100% 可直接還原開啟。

### 3. 為何透過 `pymupdf` 偵測向量圖與彩色文字兼顧精準度與 Token 成本？
- 若將整份數十頁 PDF 全部轉圖餵給多模態模型，視覺 Token 成本與延遲會急遽上升；若只用純文字抽取（`pypdf`），又會遺漏系統方框圖、時序波形圖或規格書中以紅／藍字標記的關鍵限制。
- 本管線透過 `pymupdf` 在本地毫秒級檢查每一頁的點陣圖、幾何向量路徑與非灰階彩色文字，**僅將含視覺元素的頁面輸出為 PNG 並在 `_CLEAN_SPEC.md` 標註頁碼**，純文字頁則進行空白壓縮，同時兼顧規格零遺漏與極低 Token 開銷（若未安裝 `pymupdf`，亦能自動降級回 `pypdf` 純文字抽取）。

---

## 快速上手

### 1. 安裝相依套件（建議使用 `uv`）
需要 **Python >= 3.12** 與已登入的 **Antigravity CLI (`agy`)**：

```bash
uv sync --extra dev
```

### 2. 建立本機設定檔
從範本複製一份 `config.yaml`（此檔案已被 `.gitignore` 排除，不會誤推至遠端）：

```bash
# macOS / Linux / Git Bash
cp config.example.yaml config.yaml

# Windows PowerShell
Copy-Item config.example.yaml config.yaml
```

### 選擇 AI 指令與審查報告語言（支援英文 / 繁體中文）
下載後有兩種方式可以切換語言（優先順序：**指令列 `--lang` > `config.yaml` > 預設 `en`**）：

1. **永久設定**：打開 `config.yaml`，將 `prompt_language` 改成 `"zh-TW"`（繁體中文）或 `"en"`（英文）。
2. **臨時切換**：不用改設定檔，啟動時直接加上 `--lang` 參數即可：

```bash
# 這次執行改用繁體中文 Prompt 與繁體中文審查報告
uv run python -m pipeline --lang zh-TW

# 這次執行改用英文 Prompt 與英文審查報告
uv run python -m pipeline --lang en
```

亦可用環境變數 `PIPELINE_CONFIG` 或 `--config` 指定設定檔位置。

### 3. 安裝 Goldfish 審查技能範本（建議）
```bash
# macOS / Linux
mkdir -p ~/.gemini/skills/goldfish-review
cp skills/goldfish-review/SKILL.md ~/.gemini/skills/goldfish-review/SKILL.md

# Windows PowerShell
New-Item -ItemType Directory -Force "$HOME\.gemini\skills\goldfish-review" | Out-Null
Copy-Item skills\goldfish-review\SKILL.md "$HOME\.gemini\skills\goldfish-review\SKILL.md"
```

### 4. 執行環境健檢 (`--doctor`)
```bash
uv run python -m pipeline --doctor
```

### 5. 啟動管線並執行示範任務
首次使用前，請先在沙盒目錄啟動一次 `agy` 完成資料夾信任，隨後即可啟動監聽：

```bash
uv run python -m pipeline
# 或使用安裝後的 CLI 入口點
uv run spec-pipeline
```

Windows 使用者亦可直接執行 `scripts\start.bat`。接著將示範任務複製進 `dropzone/` 即可測試完整流程：

```bash
cp -r examples/token_bucket_demo dropzone/token_bucket_demo
```

---

## 執行單元測試

```bash
uv run pytest
```

---

## Roadmap

- [x] 6 階段沙盒隔離管線與動態 `agy models` 模型路由
- [x] 無狀態紅隊審查（`/goldfish`）與 PDF 視覺元素偵測
- [ ] 整合本機 Ollama（3B）進行日誌壓縮與前置雜訊過濾
- [ ] 加入 GitHub Actions CI 自動執行 `pytest` 測試檢查
- [ ] 微調輕量級本機路由模型，產出嚴格合規的 JSON 規劃藍圖

---

## License

本專案採用 [MIT License](LICENSE) 釋出。
