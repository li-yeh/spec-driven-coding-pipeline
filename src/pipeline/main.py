from __future__ import annotations

import argparse
from dataclasses import replace
import shutil
import time
from collections.abc import Sequence
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from pipeline import agy_runner, prep, prompts
from pipeline.config import (
    CONTROL_FILES,
    SPEC_PAGE_PREFIX,
    TEMP_DIRS,
    PipelineConfig,
    load_config,
    normalize_prompt_language,
    resolve_config_path,
)


def _unique_dest(parent: Path, name: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    dest = parent / name
    return parent / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}" if dest.exists() else dest


def _pick_model(models_cfg: dict, key: str, default_effort: str) -> tuple[str | None, str]:
    entry = models_cfg.get(key) or {}
    return entry.get("model"), entry.get("effort", default_effort)


def _cleanup_sandbox_artifacts(sandbox_root: Path) -> None:
    """Remove temporary pipeline control files, rendered visual pages, and _ai_tmp without touching user files."""
    for fname in CONTROL_FILES:
        fp = sandbox_root / fname
        if fp.exists():
            fp.unlink()
    for img in sandbox_root.glob(f"*{SPEC_PAGE_PREFIX}_*.png"):
        if img.is_file():
            img.unlink()
    for dname in TEMP_DIRS:
        dp = sandbox_root / dname
        if dp.is_dir():
            shutil.rmtree(dp, ignore_errors=True)


def _discover_spec_files(outer_drop_dir: Path) -> tuple[str, list[Path]]:
    """Prefer PDF specifications; fall back to Markdown specs (e.g., spec.md) if no PDF is present."""
    pdfs = sorted(outer_drop_dir.glob("*.pdf")) or sorted(outer_drop_dir.rglob("*.pdf"))
    if pdfs:
        return "pdf", pdfs

    md_candidates = (
        sorted(
            p for p in outer_drop_dir.glob("*.md")
            if p.name.lower() in {"spec.md", "specification.md"}
        )
        or sorted(outer_drop_dir.glob("*.md"))
        or sorted(outer_drop_dir.rglob("spec.md"))
    )
    if md_candidates:
        return "md", md_candidates

    return "none", []


def run_pipeline(outer_drop_dir: Path, cfg: PipelineConfig) -> None:
    print(f"\n{'=' * 66}\n[*] New task package detected: {outer_drop_dir.name}")
    if not prep.wait_until_stable(outer_drop_dir):
        print("[!] Drop folder is empty or timed out while stabilizing; skipping.")
        return

    spec_kind, spec_files = _discover_spec_files(outer_drop_dir)
    if not spec_files:
        print(f"[!] Invalid package (must contain at least one .pdf or spec.md): {outer_drop_dir.name}")
        return

    sandbox_root = cfg.sandbox_dir / outer_drop_dir.name

    # Stage 0: Reset sandbox and mirror full directory hierarchy (temporarily excluding PDFs)
    cfg.sandbox_dir.mkdir(parents=True, exist_ok=True)
    for item in cfg.sandbox_dir.iterdir():
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    excluded_pdfs = prep.copy_project_preserving_structure(outer_drop_dir, sandbox_root)

    if spec_kind == "pdf":
        if len(spec_files) == 1:
            clean_spec = prep.extract_and_simplify_pdf(spec_files[0], output_dir=sandbox_root)
        else:
            clean_spec = "\n\n".join(
                f"=== {p.relative_to(outer_drop_dir).as_posix()} ===\n"
                f"{prep.extract_and_simplify_pdf(p, output_dir=sandbox_root, page_prefix=f'{SPEC_PAGE_PREFIX}_doc{idx}')}"
                for idx, p in enumerate(spec_files, 1)
            )
    else:
        if len(spec_files) == 1:
            clean_spec = spec_files[0].read_text(encoding="utf-8")
        else:
            clean_spec = "\n\n".join(
                f"=== {p.relative_to(outer_drop_dir).as_posix()} ===\n{p.read_text(encoding='utf-8')}"
                for p in spec_files
            )

    (sandbox_root / "_CLEAN_SPEC.md").write_text(clean_spec, encoding="utf-8")
    (sandbox_root / "_FILE_TREE.txt").write_text(prep.build_file_tree(sandbox_root), encoding="utf-8")
    (sandbox_root / "_AVAILABLE_TOOLS.txt").write_text(
        prep.detect_local_tools(cfg.extra_tool_dirs), encoding="utf-8"
    )
    (sandbox_root / "_AVAILABLE_MODELS.txt").write_text(
        agy_runner.fetch_live_models(prefer_google_models=cfg.prefer_google_models),
        encoding="utf-8",
    )
    print(
        f"[OK] [Stage 0] Structure copied, spec prepared ({len(clean_spec)} chars), "
        f"live models & local tools indexed (prompt_language={cfg.prompt_language})."
    )

    lang = cfg.prompt_language
    runner_opts = {
        "prefer_google_models": cfg.prefer_google_models,
        "extra_tool_dirs": cfg.extra_tool_dirs,
    }

    try:
        # Stages 1 & 2: Dynamic planning and stateless plan/structure audit (auto + high)
        agy_runner.run_agy(
            sandbox_root,
            "Stage 1: Planning & Dynamic Model Selection",
            prompts.stage1_plan_prompt(cfg.archive_routes.keys(), lang=lang),
            effort="high",
            **runner_opts,
        )
        agy_runner.run_agy(
            sandbox_root,
            "Stage 2: Stateless Plan & Structure Audit",
            prompts.stage2_audit_plan_prompt(lang=lang),
            effort="high",
            **runner_opts,
        )

        # Load audited blueprint (original project layout remains untouched)
        plan = prep.load_plan_json(sandbox_root / "_PLAN.json")
        models_cfg = plan.get("models") or {}

        # Stage 4: Dynamic single-shot or interface-locked batched implementation
        if plan.get("execution_mode") == "BATCH_FAST" and plan.get("sub_tasks"):
            m_imp, e_imp = _pick_model(models_cfg, "implement", "high")
            if plan.get("skeleton_prompt"):
                agy_runner.run_agy(
                    sandbox_root,
                    "Stage 4a: Lock Multi-File Interface Skeleton",
                    prompts.stage4_skeleton_prompt(plan["skeleton_prompt"], lang=lang),
                    model=m_imp,
                    effort=e_imp,
                    **runner_opts,
                )
            m_w, e_w = _pick_model(models_cfg, "batch_worker", "medium")
            tasks = plan["sub_tasks"]
            for i, task in enumerate(tasks, 1):
                agy_runner.run_agy(
                    sandbox_root,
                    f"Stage 4b: Batch Worker ({i}/{len(tasks)})",
                    prompts.stage4_batch_worker_prompt(task, i, len(tasks), lang=lang),
                    model=m_w,
                    effort=e_w,
                    **runner_opts,
                )
        else:
            m_imp, e_imp = _pick_model(models_cfg, "implement", "high")
            agy_runner.run_agy(
                sandbox_root,
                "Stage 4: Single-Shot Core Implementation",
                prompts.stage4_single_impl_prompt(
                    plan.get("spec_summary", ""),
                    plan.get("implementation_prompt", ""),
                    lang=lang,
                ),
                model=m_imp,
                effort=e_imp,
                **runner_opts,
            )

        # Stage 5: Local execution & iterative debugging (escalate to strongest model on Round 2)
        test_cmd = plan.get("test_command", "")
        m_dbg, e_dbg = _pick_model(models_cfg, "debug", "medium")
        debug_out = agy_runner.run_agy(
            sandbox_root,
            "Stage 5 (Round 1): Local Build & Verification",
            prompts.stage5_debug_prompt(test_cmd, round_idx=1, lang=lang),
            model=m_dbg,
            effort=e_dbg,
            **runner_opts,
        )
        if "[TESTS: PASSED]" not in debug_out:
            m_esc, e_esc = _pick_model(models_cfg, "debug_escalation", "high")
            agy_runner.run_agy(
                sandbox_root,
                "Stage 5 (Round 2 Escalation): Deep Debug & Remediation",
                prompts.stage5_debug_prompt(test_cmd, round_idx=2, prev_log=debug_out, lang=lang),
                model=m_esc,
                effort=e_esc,
                **runner_opts,
            )

        # Stage 6: Goldfish stateless red-team final review
        m_gf, e_gf = _pick_model(models_cfg, "goldfish", "high")
        review_out = agy_runner.run_agy(
            sandbox_root,
            "Stage 6: Goldfish Stateless Red-Team Review",
            prompts.stage6_goldfish_prompt(lang=lang),
            model=m_gf,
            effort=e_gf,
            **runner_opts,
        )

        # Finalize: write review next to spec, clean scratch/control files, restore PDFs, and route
        review_dir = sandbox_root / spec_files[0].relative_to(outer_drop_dir).parent
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "AI_FINAL_REVIEW.md").write_text(review_out, encoding="utf-8")
        _cleanup_sandbox_artifacts(sandbox_root)
        prep.restore_excluded_files(outer_drop_dir, sandbox_root, excluded_pdfs)

        if "[STATUS: VERIFIED]" in review_out:
            domain = plan.get("domain", cfg.default_domain)
            dest_root = cfg.resolve_archive_dir(domain)
            final_dest = _unique_dest(dest_root, outer_drop_dir.name)
            shutil.move(str(sandbox_root), str(final_dest))
            shutil.move(str(outer_drop_dir), str(_unique_dest(cfg.processed_dir, outer_drop_dir.name)))
            print(f"[VERIFIED] Domain: {domain} | Archived deliverable to: {final_dest}")
        else:
            review_dest = _unique_dest(cfg.needs_review_dir, outer_drop_dir.name)
            shutil.move(str(sandbox_root), str(review_dest))
            print(f"[NEEDS REVIEW] Preserved full workspace at: {review_dest}")

    except Exception as e:
        print(f"[ERROR] Pipeline execution aborted: {e}")
        if sandbox_root.exists():
            # Preserve control artifacts on failure for debugging while restoring original PDFs
            prep.restore_excluded_files(outer_drop_dir, sandbox_root, excluded_pdfs)
            fail_dest = _unique_dest(cfg.needs_review_dir, f"{outer_drop_dir.name}_FAILED")
            shutil.move(str(sandbox_root), str(fail_dest))
            print(f"[PRESERVED] Failure snapshot saved to: {fail_dest}")


class DropHandler(FileSystemEventHandler):
    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.active: set[Path] = set()

    def on_created(self, event) -> None:
        src = Path(event.src_path)
        if src == self.cfg.watch_dir:
            return
        try:
            top = self.cfg.watch_dir / src.relative_to(self.cfg.watch_dir).parts[0]
        except Exception:
            return
        if not top.is_dir() or top in self.active:
            return
        self.active.add(top)
        try:
            run_pipeline(top, self.cfg)
        finally:
            self.active.discard(top)


def _apply_lang_override(cfg: PipelineConfig, lang_override: str | None) -> PipelineConfig:
    if not lang_override:
        return cfg
    return replace(cfg, prompt_language=normalize_prompt_language(lang_override))


def run_doctor(config_path: Path | None = None, lang_override: str | None = None) -> int:
    """Run environment diagnostics without starting the Watchdog observer."""
    print("=" * 64)
    print("Spec-Driven Autonomous Coding Pipeline — Environment Doctor")
    print("=" * 64)

    extra_tool_dirs: list[Path] = []

    # 1. Check config.yaml presence and YAML/schema validity
    target_cfg = resolve_config_path(config_path)
    if not target_cfg.is_file():
        print(f"[MISSING] config.yaml: Not found ({target_cfg})")
        print("          -> Copy template: cp config.example.yaml config.yaml")
        if lang_override:
            print(f"          CLI language override: prompt_language={normalize_prompt_language(lang_override)}")
    else:
        try:
            cfg = _apply_lang_override(load_config(target_cfg, warn_missing=False), lang_override)
            extra_tool_dirs = cfg.extra_tool_dirs
            print(f"[OK]      config.yaml: Valid ({cfg.config_path})")
            print(
                f"          watch_dir={cfg.watch_dir} | sandbox_dir={cfg.sandbox_dir} | "
                f"prompt_language={cfg.prompt_language}"
            )
        except ValueError as exc:
            print(f"[MISSING] config.yaml: Invalid format ({exc})")

    # 2. Check agy CLI availability in PATH
    agy_path = agy_runner.find_agy_binary()
    if agy_path:
        print(f"[OK]      agy CLI: {agy_path}")
    else:
        print("[MISSING] agy CLI: 'agy' executable not found in PATH")
        print("          -> Install and authenticate Antigravity CLI (agy), then ensure it is on PATH.")

    # 3. Check ~/.gemini/skills/goldfish-review/SKILL.md
    skill_path = Path.home() / ".gemini" / "skills" / "goldfish-review" / "SKILL.md"
    if skill_path.is_file():
        print(f"[OK]      goldfish-review skill: {skill_path}")
    else:
        print(f"[MISSING] goldfish-review skill: Not found at {skill_path}")
        print("          -> Copy template from: skills/goldfish-review/SKILL.md")

    # 4. Probe locally installed build/test tools
    tools_output = prep.detect_local_tools(extra_tool_dirs)
    if tools_output.startswith("("):
        print(f"[MISSING] Local build/test tools: {tools_output}")
    else:
        tools_inline = ", ".join(tools_output.splitlines())
        print(f"[OK]      Local tools detected: {tools_inline}")

    print("=" * 64)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="Spec-Driven Autonomous Coding Pipeline",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check config.yaml, agy CLI, Goldfish skill, and local build/test tools then exit.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a custom config.yaml file (overrides PIPELINE_CONFIG).",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Override prompt and review language for this run ('en' or 'zh-TW').",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.lang:
        try:
            args.lang = normalize_prompt_language(args.lang)
        except ValueError as exc:
            parser.error(str(exc))

    if args.doctor:
        return run_doctor(args.config, args.lang)

    cfg = _apply_lang_override(load_config(args.config, warn_missing=True), args.lang)
    cfg.watch_dir.mkdir(parents=True, exist_ok=True)
    cfg.sandbox_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"[READY] Spec-Driven Coding Pipeline started | watch_dir: {cfg.watch_dir} | "
        f"sandbox_dir: {cfg.sandbox_dir} | prompt_language: {cfg.prompt_language}"
    )

    for existing in sorted(p for p in cfg.watch_dir.iterdir() if p.is_dir()):
        run_pipeline(existing, cfg)

    observer = Observer()
    observer.schedule(DropHandler(cfg), str(cfg.watch_dir), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
