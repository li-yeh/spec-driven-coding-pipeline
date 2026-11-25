from __future__ import annotations

import pytest

from pipeline import prompts


@pytest.mark.parametrize("lang", ["en", "zh-TW"])
def test_all_stage_prompts_support_bilingual_switching(lang: str) -> None:
    s1 = prompts.stage1_plan_prompt(["HARDWARE_RTL", "GENERAL"], lang=lang)
    s2 = prompts.stage2_audit_plan_prompt(lang=lang)
    s4_single = prompts.stage4_single_impl_prompt("summary", "do impl", lang=lang)
    s4_skel = prompts.stage4_skeleton_prompt("lock interfaces", lang=lang)
    s4_batch = prompts.stage4_batch_worker_prompt("write module A", 1, 3, lang=lang)
    s5 = prompts.stage5_debug_prompt("pytest", round_idx=1, lang=lang)
    s6 = prompts.stage6_goldfish_prompt(lang=lang)

    assert "HARDWARE_RTL, GENERAL" in s1
    assert "_PLAN.json" in s1 and "_PLAN.json" in s2
    assert ".bak" in s4_single and ".bak" in s4_skel and ".bak" in s4_batch
    assert "[TESTS: PASSED]" in s5
    assert "_ai_tmp/" in s5 and "_ai_tmp/" in s6
    assert "[STATUS: VERIFIED]" in s6

    # Verify both languages enforce testbench protection in Stage 4 and Stage 5
    for text in (s4_single, s4_skel, s4_batch, s5):
        assert "testbench" in text.lower()


def test_en_and_zh_prompts_produce_distinct_localized_outputs() -> None:
    en_review = prompts.stage6_goldfish_prompt(lang="en")
    zh_review = prompts.stage6_goldfish_prompt(lang="zh-TW")

    assert "Phase 1" in en_review
    assert "階段一" in zh_review
    assert en_review != zh_review


def test_cli_lang_flag_parsing_and_override(tmp_path) -> None:
    from pipeline import main as pipeline_main
    from pipeline.config import load_config

    args = pipeline_main.build_arg_parser().parse_args(["--doctor", "--lang", "zh-TW"])
    assert args.doctor is True
    assert args.lang == "zh-TW"

    cfg = load_config(tmp_path / "missing.yaml", warn_missing=False)
    assert cfg.prompt_language == "en"

    overridden = pipeline_main._apply_lang_override(cfg, "zh")
    assert overridden.prompt_language == "zh-TW"

    with pytest.raises(SystemExit):
        pipeline_main.main(["--doctor", "--lang", "invalid-lang"])
