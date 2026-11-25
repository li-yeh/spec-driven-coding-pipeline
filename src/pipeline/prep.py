from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from pipeline.config import CONTROL_FILES, SPEC_PAGE_PREFIX, TEMP_DIRS

# Candidate local CLI compilers, simulators, linters, and test runners probed in Stage 0/5
LOCAL_CLI_TOOLS: list[str] = [
    "iverilog", "vvp", "verilator",
    "gcc", "g++", "make", "cmake",
    "python", "pytest", "ruff", "mypy",
    "wsl", "docker",
]

# Filtered only when generating _FILE_TREE.txt; original project files are never physically deleted
IGNORED_DIR_SUFFIXES = (".runs", ".cache", ".sim", ".ip_user_files", ".gen", ".hw", ".hbs")
IGNORED_DIR_NAMES = {"__pycache__", ".git", ".Xil", "node_modules", ".venv"} | TEMP_DIRS
IGNORED_FILE_SUFFIXES = (".jou", ".log", ".bak")

# Minimum RGB channel spread to classify text as colored (excludes black/gray/white)
_COLOR_CHROMA_THRESHOLD = 30
# Minimum bounding-box dimension (points) for substantive vector shapes
_VECTOR_BOX_MIN_PT = 5.0
# Minimum multi-segment vector count to classify drawings as a diagram/table
_VECTOR_MIN_SHAPES = 3


def wait_until_stable(folder: Path, timeout: int = 20) -> bool:
    """Debounce incoming drops by waiting until file sizes stop changing."""
    start = time.time()
    last_snap: dict[str, int] = {}
    while time.time() - start < timeout:
        snap = {}
        for p in folder.rglob("*"):
            if p.is_file():
                try:
                    snap[str(p)] = p.stat().st_size
                except OSError:
                    continue
        if snap and snap == last_snap:
            return True
        last_snap = snap
        time.sleep(1.5)
    return bool(last_snap)


def _normalize_page_text(raw: str) -> list[str]:
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.splitlines()]
    return [ln for ln in lines if ln]


def _is_colored_rgb(color_int: int) -> bool:
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    return (max(r, g, b) - min(r, g, b)) > _COLOR_CHROMA_THRESHOLD


def detect_page_visual_elements(page: Any) -> list[str]:
    """Detect raster images, vector graphics, and colored highlight text on a PyMuPDF page."""
    reasons: list[str] = []

    # 1. Raster images
    try:
        if page.get_images(full=True):
            reasons.append("images")
    except Exception:
        pass

    # 2. Vector graphics (block diagrams, timing waveforms, flowcharts, tables)
    try:
        drawings = page.get_drawings() or []
        substantial_shapes = 0
        has_area_shape = False
        for d in drawings:
            rect = d.get("rect")
            if rect is None:
                continue
            width = abs(float(rect.width))
            height = abs(float(rect.height))
            if width >= _VECTOR_BOX_MIN_PT and height >= _VECTOR_BOX_MIN_PT:
                has_area_shape = True
                substantial_shapes += 1
            elif width >= _VECTOR_BOX_MIN_PT or height >= _VECTOR_BOX_MIN_PT:
                # Ignore isolated header/footer rules while keeping multi-segment tables/waveforms
                substantial_shapes += 1
        if has_area_shape or substantial_shapes >= _VECTOR_MIN_SHAPES:
            reasons.append("vector_graphics")
    except Exception:
        pass

    # 3. Colored emphasis text (non-grayscale RGB spans such as red warnings or blue notes)
    try:
        text_dict = page.get_text("dict") or {}
        found_color = False
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if not (span.get("text") or "").strip():
                        continue
                    color = span.get("color")
                    if isinstance(color, int) and _is_colored_rgb(color):
                        found_color = True
                        break
                if found_color:
                    break
            if found_color:
                break
        if found_color:
            reasons.append("colored_text")
    except Exception:
        pass

    return reasons


def _extract_pdf_with_pypdf(pdf_path: Path) -> str:
    """Text-only fallback extractor using pypdf when PyMuPDF is unavailable."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for i, page in enumerate(reader.pages, 1):
        lines = _normalize_page_text(page.extract_text() or "")
        if lines:
            pages.append(f"--- Page {i} ---\n" + "\n".join(lines))
    return "\n\n".join(pages)


def extract_and_simplify_pdf(
    pdf_path: Path,
    output_dir: Path | None = None,
    page_prefix: str = SPEC_PAGE_PREFIX,
    render_dpi: int = 150,
) -> str:
    """
    Extract and whitespace-compress PDF text to minimize downstream token consumption.
    When PyMuPDF is installed, also detects raster images, vector graphics, and colored text;
    if `output_dir` is given, renders only pages containing visual elements to PNG files.
    """
    try:
        try:
            import pymupdf as fitz  # type: ignore[import-not-found]
        except ImportError:
            import fitz  # type: ignore[import-not-found]
    except ImportError:
        return _extract_pdf_with_pypdf(pdf_path)

    pages: list[str] = []
    with fitz.open(str(pdf_path)) as doc:
        for i, page in enumerate(doc, 1):
            lines = _normalize_page_text(page.get_text("text") or "")
            visual_reasons = detect_page_visual_elements(page)

            visual_note = ""
            if visual_reasons:
                reason_str = ", ".join(visual_reasons)
                if output_dir is not None:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    img_name = f"{page_prefix}_{i}.png"
                    pix = page.get_pixmap(dpi=render_dpi)
                    pix.save(str(output_dir / img_name))
                    visual_note = f"[Visual Content Detected: {reason_str} -> see {img_name}]"
                else:
                    visual_note = f"[Visual Content Detected: {reason_str}]"

            if lines or visual_note:
                body_parts = []
                if visual_note:
                    body_parts.append(visual_note)
                if lines:
                    body_parts.append("\n".join(lines))
                pages.append(f"--- Page {i} ---\n" + "\n".join(body_parts))

    return "\n\n".join(pages)


def copy_project_preserving_structure(src_dir: Path, dst_dir: Path) -> list[Path]:
    """
    Copy the full task directory hierarchy into the sandbox while temporarily excluding
    PDF files (avoiding redundant raw PDF reads by agents). Returns excluded PDF paths.
    """
    src_root = src_dir.resolve()
    excluded_pdfs: list[Path] = []

    def _ignore_pdfs(current_dir: str, names: list[str]) -> set[str]:
        cur = Path(current_dir)
        ignored: set[str] = set()
        for name in names:
            p = cur / name
            if p.is_file() and p.suffix.lower() == ".pdf":
                excluded_pdfs.append(p.resolve().relative_to(src_root))
                ignored.add(name)
        return ignored

    shutil.copytree(src_root, dst_dir, ignore=_ignore_pdfs)
    return sorted(excluded_pdfs)


def restore_excluded_files(src_dir: Path, dst_dir: Path, rel_paths: list[Path]) -> None:
    """Restore excluded PDFs to their exact original relative paths during finalization."""
    for rel in rel_paths:
        src = src_dir / rel
        dst = dst_dir / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _is_tree_noise(rel_path: Path) -> bool:
    for part in rel_path.parts[:-1]:
        if part in IGNORED_DIR_NAMES or part.endswith(IGNORED_DIR_SUFFIXES):
            return True
    name = rel_path.name
    if name in CONTROL_FILES:
        return True
    if name.startswith(f"{SPEC_PAGE_PREFIX}_") and name.lower().endswith(".png"):
        return True
    return name.lower().endswith(IGNORED_FILE_SUFFIXES)


def build_file_tree(work_dir: Path) -> str:
    """List relevant source/config/test files with sizes, filtering IDE noise non-destructively."""
    rows = []
    for p in sorted(work_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(work_dir)
        if _is_tree_noise(rel):
            continue
        rows.append(f"{rel.as_posix()} ({p.stat().st_size / 1024:.1f} KB)")
    return "\n".join(rows)


def detect_local_tools(extra_dirs: list[Path] | None = None) -> str:
    """Probe locally installed CLI build/test tools so planned commands stay executable."""
    search_path = os.environ.get("PATH", "")
    candidate_dirs = list(extra_dirs or [])
    default_iverilog = Path(r"C:\iverilog\bin")
    if os.name == "nt" and default_iverilog.is_dir():
        candidate_dirs.append(default_iverilog)

    for tool_dir in candidate_dirs:
        if tool_dir.is_dir() and str(tool_dir).lower() not in search_path.lower():
            search_path = f"{tool_dir}{os.pathsep}{search_path}"

    found = [tool for tool in LOCAL_CLI_TOOLS if shutil.which(tool, path=search_path)]
    return "\n".join(found) if found else "(No standard CLI build/test tools detected)"


def load_plan_json(plan_path: Path) -> dict[str, Any]:
    """Parse _PLAN.json while tolerating occasional Markdown code fences."""
    text = plan_path.read_text(encoding="utf-8").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    return json.loads(text)


def safe_clean_junk(work_dir: Path, globs: list[str]) -> int:
    """Remove sandbox-scoped junk matching vetted globs while blocking traversal and protecting control files."""
    root = work_dir.resolve()
    removed = 0
    for pattern in globs:
        pat = (pattern or "").strip()
        if not pat or pat in {"*", "*.*", ".", "..", "/", "\\"} or ".." in pat:
            continue
        if Path(pat).is_absolute():
            continue
        for target in list(root.rglob(pat)):
            if not target.exists() or target == root or target.name in CONTROL_FILES:
                continue
            # Prevent symlink or path-resolution escapes outside the sandbox root
            if not target.resolve().is_relative_to(root):
                continue
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                removed += 1
            except OSError:
                pass
    return removed
