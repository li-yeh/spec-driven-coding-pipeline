from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline import prep
from pipeline.config import CONTROL_FILES


def test_copy_preserve_structure_and_restore_pdfs(tmp_path: Path) -> None:
    src = tmp_path / "task_pkg"
    (src / "sub" / "proj.cache").mkdir(parents=True)
    (src / "Spec.pdf").write_bytes(b"%PDF-1.4\n")
    (src / "sub" / "keep.v").write_text("module top; endmodule\n", encoding="utf-8")
    (src / "sub" / "proj.cache" / "tmp.dat").write_text("cached", encoding="utf-8")
    (src / "sub" / "tool.log").write_text("log", encoding="utf-8")

    dst = tmp_path / "sandbox" / "task_pkg"
    excluded = prep.copy_project_preserving_structure(src, dst)

    assert excluded == [Path("Spec.pdf")]
    assert not (dst / "Spec.pdf").exists()
    assert (dst / "sub" / "keep.v").is_file()
    assert (dst / "sub" / "proj.cache" / "tmp.dat").is_file()

    prep.restore_excluded_files(src, dst, excluded)
    assert (dst / "Spec.pdf").is_file()
    assert (dst / "Spec.pdf").read_bytes() == b"%PDF-1.4\n"


def test_build_file_tree_filters_noise_and_control_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "src" / "main.py.bak").write_text("backup\n", encoding="utf-8")
    (tmp_path / "proj.cache").mkdir()
    (tmp_path / "proj.cache" / "noise.bin").write_text("x", encoding="utf-8")
    (tmp_path / "_ai_tmp").mkdir()
    (tmp_path / "_ai_tmp" / "scratch.py").write_text("tmp", encoding="utf-8")
    (tmp_path / "build.log").write_text("log", encoding="utf-8")
    (tmp_path / "_CLEAN_SPEC.md").write_text("spec", encoding="utf-8")
    (tmp_path / "_spec_page_1.png").write_bytes(b"png")

    tree = prep.build_file_tree(tmp_path)

    assert "src/main.py" in tree
    assert "main.py.bak" not in tree
    assert "proj.cache" not in tree
    assert "_ai_tmp" not in tree
    assert "build.log" not in tree
    assert "_CLEAN_SPEC.md" not in tree
    assert "_spec_page_1.png" not in tree


def test_load_plan_json_plain_and_fenced(tmp_path: Path) -> None:
    plain_file = tmp_path / "plain.json"
    plain_file.write_text('{"domain": "GENERAL", "ok": true}', encoding="utf-8")
    assert prep.load_plan_json(plain_file) == {"domain": "GENERAL", "ok": True}

    fenced_file = tmp_path / "fenced.json"
    fenced_file.write_text('```json\n{"domain": "ALGORITHMS", "count": 3}\n```', encoding="utf-8")
    assert prep.load_plan_json(fenced_file) == {"domain": "ALGORITHMS", "count": 3}


def test_safe_clean_junk_removes_matching_and_protects_boundaries(tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_secret = outside_dir / "precious.tmp"
    outside_secret.write_text("do not delete", encoding="utf-8")

    sandbox = tmp_path / "sandbox"
    (sandbox / "sub").mkdir(parents=True)
    (sandbox / "sub" / "junk.tmp").write_text("remove me", encoding="utf-8")
    (sandbox / "keep.py").write_text("keep me", encoding="utf-8")

    for ctrl in CONTROL_FILES:
        (sandbox / ctrl).write_text("control", encoding="utf-8")

    # Unsafe wildcards, parent traversal, and absolute paths must be rejected
    removed_blocked = prep.safe_clean_junk(
        sandbox,
        ["*", "*.*", ".", "..", "/", "\\", "../outside/*.tmp", str(outside_secret)],
    )
    assert removed_blocked == 0
    assert outside_secret.is_file()
    assert (sandbox / "keep.py").is_file()

    # Pipeline control files must remain protected even when matched explicitly
    removed_ctrl = prep.safe_clean_junk(sandbox, ["_PLAN.json", "_CLEAN_SPEC.md"])
    assert removed_ctrl == 0
    for ctrl in CONTROL_FILES:
        assert (sandbox / ctrl).is_file()

    # Valid scoped glob removes only sandbox junk
    removed_valid = prep.safe_clean_junk(sandbox, ["*.tmp"])
    assert removed_valid == 1
    assert not (sandbox / "sub" / "junk.tmp").exists()
    assert (sandbox / "keep.py").is_file()
    assert outside_secret.is_file()


def test_safe_clean_junk_blocks_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "escape.tmp"
    outside_file.write_text("safe", encoding="utf-8")

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    link_path = sandbox / "escape.tmp"

    try:
        os.symlink(outside_file, link_path)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not permitted in this environment")

    removed = prep.safe_clean_junk(sandbox, ["*.tmp"])
    assert removed == 0
    assert outside_file.is_file()


def test_extract_and_simplify_pdf_visual_detection_with_fitz(tmp_path: Path) -> None:
    try:
        fitz = pytest.importorskip("pymupdf")
    except pytest.skip.Exception:
        fitz = pytest.importorskip("fitz")

    pdf_path = tmp_path / "sample_spec.pdf"
    out_dir = tmp_path / "rendered"

    doc = fitz.open()
    try:
        # Page 1: plain black text only (should not emit a rendered PNG)
        p1 = doc.new_page()
        p1.insert_text((72, 72), "Page 1   Plain    Black Text", color=(0, 0, 0))

        # Page 2: vector rectangle (should trigger vector_graphics)
        p2 = doc.new_page()
        p2.insert_text((72, 72), "Page 2 Architecture Diagram", color=(0, 0, 0))
        p2.draw_rect(fitz.Rect(72, 100, 220, 180), color=(0, 0, 0), width=1.5)

        # Page 3: red emphasis text (should trigger colored_text)
        p3 = doc.new_page()
        p3.insert_text((72, 72), "CRITICAL: Active-low reset!", color=(1, 0, 0))

        # Page 4: embedded raster image (should trigger images)
        p4 = doc.new_page()
        p4.insert_text((72, 72), "Page 4 Waveform Image", color=(0, 0, 0))
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 16, 16), 0)
        pix.clear_with(200)
        p4.insert_image(fitz.Rect(72, 100, 120, 148), pixmap=pix)

        doc.save(str(pdf_path))
    finally:
        doc.close()

    extracted = prep.extract_and_simplify_pdf(pdf_path, output_dir=out_dir, render_dpi=72)

    # Whitespace compression check
    assert "Page 1 Plain Black Text" in extracted
    assert not (out_dir / "_spec_page_1.png").exists()

    # Vector graphics, colored text, and raster image pages must be detected and rendered
    assert "vector_graphics" in extracted
    assert (out_dir / "_spec_page_2.png").is_file()

    assert "colored_text" in extracted
    assert (out_dir / "_spec_page_3.png").is_file()

    assert "images" in extracted
    assert (out_dir / "_spec_page_4.png").is_file()
