from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Control artifacts generated inside the sandbox and removed upon completion
CONTROL_FILES: set[str] = {
    "_CLEAN_SPEC.md",
    "_FILE_TREE.txt",
    "_AVAILABLE_TOOLS.txt",
    "_AVAILABLE_MODELS.txt",
    "_PLAN.json",
}

# Isolated scratch directory for Stage 5/6 temporary test harnesses and build outputs
TEMP_DIRS: set[str] = {
    "_ai_tmp",
}

# Filename prefix for rendered PDF visual pages
SPEC_PAGE_PREFIX = "_spec_page"

DEFAULT_WATCH_DIR = "./dropzone"
DEFAULT_SANDBOX_DIR = "./active_sandbox"
DEFAULT_PROCESSED_DIR = "./processed_drops"
DEFAULT_NEEDS_REVIEW_DIR = "./needs_review"
DEFAULT_DOMAIN = "GENERAL"
DEFAULT_PROMPT_LANGUAGE = "en"

SUPPORTED_PROMPT_LANGUAGES: dict[str, str] = {
    "en": "en",
    "en-us": "en",
    "zh-tw": "zh-TW",
    "zh_tw": "zh-TW",
    "zh": "zh-TW",
}

DEFAULT_ARCHIVE_ROUTES: dict[str, str] = {
    "HARDWARE_RTL": "./archive/hardware",
    "SOFTWARE_BACKEND": "./archive/software",
    "ALGORITHMS": "./archive/algorithms",
    "GENERAL": "./archive/general",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def normalize_prompt_language(raw: str) -> str:
    """Normalize a prompt language code to 'en' or 'zh-TW'."""
    key = raw.strip().lower()
    if key in SUPPORTED_PROMPT_LANGUAGES:
        return SUPPORTED_PROMPT_LANGUAGES[key]
    raise ValueError(
        f"Unsupported prompt_language '{raw}'. Supported values: 'en', 'zh-TW'."
    )


@dataclass(frozen=True)
class PipelineConfig:
    """Runtime paths and behavioral configuration for the pipeline."""

    watch_dir: Path
    sandbox_dir: Path
    processed_dir: Path
    needs_review_dir: Path
    archive_routes: dict[str, Path]
    default_domain: str = DEFAULT_DOMAIN
    prompt_language: str = DEFAULT_PROMPT_LANGUAGE
    prefer_google_models: bool = True
    extra_tool_dirs: list[Path] = field(default_factory=list)
    config_path: Path | None = None
    loaded_from_file: bool = False

    def resolve_archive_dir(self, domain: str | None) -> Path:
        """Resolve the archive directory for a domain with safe fallback."""
        if domain and domain in self.archive_routes:
            return self.archive_routes[domain]
        for fallback_key in (self.default_domain, "GENERAL", "DEFAULT"):
            if fallback_key in self.archive_routes:
                return self.archive_routes[fallback_key]
        if self.archive_routes:
            return next(iter(self.archive_routes.values()))
        return self.watch_dir.parent / "archive" / "general"


def resolve_config_path(explicit_path: Path | str | None = None) -> Path:
    """Resolve config.yaml path: explicit arg > PIPELINE_CONFIG env > CWD > project root."""
    if explicit_path is not None:
        return Path(explicit_path).expanduser()

    env_path = os.environ.get("PIPELINE_CONFIG", "").strip()
    if env_path:
        return Path(env_path).expanduser()

    cwd_candidate = Path.cwd() / "config.yaml"
    if cwd_candidate.is_file():
        return cwd_candidate

    repo_candidate = PROJECT_ROOT / "config.yaml"
    if repo_candidate.is_file():
        return repo_candidate

    return cwd_candidate


def _resolve_path(raw: str, base_dir: Path) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = base_dir / p
    return p.resolve()


def validate_config_data(data: Any) -> dict[str, Any]:
    """Validate the parsed YAML configuration schema."""
    if not isinstance(data, dict):
        raise ValueError("config.yaml root must be a YAML mapping (key-value pairs).")

    for key in (
        "watch_dir",
        "sandbox_dir",
        "processed_dir",
        "needs_review_dir",
        "default_domain",
        "prompt_language",
    ):
        if key in data and (not isinstance(data[key], str) or not data[key].strip()):
            raise ValueError(f"Config field '{key}' must be a non-empty string.")

    if "prompt_language" in data:
        normalize_prompt_language(data["prompt_language"])

    if "archive_routes" in data:
        routes = data["archive_routes"]
        if not isinstance(routes, dict) or not routes:
            raise ValueError("Config field 'archive_routes' must be a non-empty mapping.")
        for domain, target in routes.items():
            if not isinstance(domain, str) or not domain.strip():
                raise ValueError("Domain keys in 'archive_routes' must be non-empty strings.")
            if not isinstance(target, str) or not target.strip():
                raise ValueError(f"Path for 'archive_routes.{domain}' must be a non-empty string.")

    if "prefer_google_models" in data and not isinstance(data["prefer_google_models"], bool):
        raise ValueError("Config field 'prefer_google_models' must be a boolean (true/false).")

    if "extra_tool_dirs" in data:
        dirs = data["extra_tool_dirs"]
        if not isinstance(dirs, list) or not all(isinstance(d, str) and d.strip() for d in dirs):
            raise ValueError("Config field 'extra_tool_dirs' must be a list of non-empty strings.")

    return data


def _build_default_config(base_dir: Path, config_path: Path) -> PipelineConfig:
    return PipelineConfig(
        watch_dir=_resolve_path(DEFAULT_WATCH_DIR, base_dir),
        sandbox_dir=_resolve_path(DEFAULT_SANDBOX_DIR, base_dir),
        processed_dir=_resolve_path(DEFAULT_PROCESSED_DIR, base_dir),
        needs_review_dir=_resolve_path(DEFAULT_NEEDS_REVIEW_DIR, base_dir),
        archive_routes={
            domain: _resolve_path(raw_path, base_dir)
            for domain, raw_path in DEFAULT_ARCHIVE_ROUTES.items()
        },
        default_domain=DEFAULT_DOMAIN,
        prompt_language=DEFAULT_PROMPT_LANGUAGE,
        prefer_google_models=True,
        extra_tool_dirs=[],
        config_path=config_path,
        loaded_from_file=False,
    )


def load_config(
    config_path: Path | str | None = None,
    *,
    warn_missing: bool = True,
) -> PipelineConfig:
    """Load YAML configuration; fall back to defaults with a setup hint if missing."""
    target = resolve_config_path(config_path)

    if not target.is_file():
        if warn_missing:
            print(
                f"[!] Configuration file not found at '{target}'. Falling back to built-in defaults.\n"
                "    Please create one from the template: cp config.example.yaml config.yaml"
            )
        base_dir = target.parent.resolve() if target.parent != Path("") else Path.cwd().resolve()
        return _build_default_config(base_dir, target)

    try:
        raw_text = target.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse YAML in '{target}': {exc}") from exc

    data = validate_config_data(parsed)
    base_dir = target.resolve().parent

    raw_routes = data.get("archive_routes") or DEFAULT_ARCHIVE_ROUTES
    archive_routes = {
        domain: _resolve_path(raw_path, base_dir)
        for domain, raw_path in raw_routes.items()
    }
    extra_tool_dirs = [
        _resolve_path(raw_dir, base_dir)
        for raw_dir in data.get("extra_tool_dirs", [])
    ]
    prompt_language = normalize_prompt_language(
        data.get("prompt_language", DEFAULT_PROMPT_LANGUAGE)
    )

    return PipelineConfig(
        watch_dir=_resolve_path(data.get("watch_dir", DEFAULT_WATCH_DIR), base_dir),
        sandbox_dir=_resolve_path(data.get("sandbox_dir", DEFAULT_SANDBOX_DIR), base_dir),
        processed_dir=_resolve_path(data.get("processed_dir", DEFAULT_PROCESSED_DIR), base_dir),
        needs_review_dir=_resolve_path(
            data.get("needs_review_dir", DEFAULT_NEEDS_REVIEW_DIR), base_dir
        ),
        archive_routes=archive_routes,
        default_domain=data.get("default_domain", DEFAULT_DOMAIN),
        prompt_language=prompt_language,
        prefer_google_models=data.get("prefer_google_models", True),
        extra_tool_dirs=extra_tool_dirs,
        config_path=target.resolve(),
        loaded_from_file=True,
    )
