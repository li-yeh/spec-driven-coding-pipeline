from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
PREFER_GOOGLE_MODELS = True  # Prefer Google (gemini-*) models by default to preserve third-party quota


def find_agy_binary() -> str | None:
    """Locate the agy CLI executable in PATH."""
    return shutil.which("agy")


def _agy_bin() -> str:
    return find_agy_binary() or "agy"


def _is_google_model(model_id: str) -> bool:
    return model_id.lower().startswith("gemini-")


def _runtime_env(extra_tool_dirs: list[Path] | None = None) -> dict[str, str]:
    """Augment subprocess PATH with configured tool directories (e.g., local simulators)."""
    env = os.environ.copy()
    path = env.get("PATH", "")
    candidate_dirs = list(extra_tool_dirs or [])
    default_iverilog = Path(r"C:\iverilog\bin")
    if os.name == "nt" and default_iverilog.is_dir():
        candidate_dirs.append(default_iverilog)

    for d in candidate_dirs:
        if d.is_dir() and str(d).lower() not in path.lower():
            path = f"{d}{os.pathsep}{path}"
    env["PATH"] = path
    return env


def fetch_live_models(*, prefer_google_models: bool = PREFER_GOOGLE_MODELS) -> str:
    """Query `agy models` for the account's currently available raw model IDs."""
    proc = subprocess.run(
        [_agy_bin(), "models"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return "(Unable to fetch live models; use auto for all stages)"
    ids = [
        ln.split("\t", 1)[0].strip()
        for ln in proc.stdout.splitlines()
        if "\t" in ln and not ln.strip().startswith("Fetching ")
    ]
    if prefer_google_models:
        google_ids = [m for m in ids if _is_google_model(m)]
        if google_ids:
            ids = google_ids
    return "\n".join(ids) if ids else "(Unable to fetch live models; use auto for all stages)"


def run_agy(
    cwd: Path,
    step_name: str,
    prompt: str,
    model: str | None = None,
    effort: str | None = None,
    timeout: str = "10m",
    *,
    prefer_google_models: bool = PREFER_GOOGLE_MODELS,
    extra_tool_dirs: list[Path] | None = None,
) -> str:
    """Execute a headless agy invocation with automatic fallback to `auto` if a specific model fails."""
    agy_cmd = _agy_bin()

    def _exec(use_model: str | None) -> subprocess.CompletedProcess[str]:
        cmd = [
            agy_cmd, "-p", prompt,
            "--print-timeout", timeout,
            "--dangerously-skip-permissions",  # Scoped strictly to the isolated sandbox directory
        ]
        if use_model and use_model.lower() != "auto":
            cmd += ["--model", use_model]
        if effort and effort.lower() in VALID_EFFORTS:
            cmd += ["--effort", effort.lower()]
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            env=_runtime_env(extra_tool_dirs),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    if prefer_google_models and model and model.lower() != "auto" and not _is_google_model(model):
        print(f"[!] [{step_name}] Non-Google model '{model}' intercepted by quota policy; falling back to auto.")
        model = None

    print(f"\n>>> [{step_name}] model={model or 'auto'} | effort={effort or 'default'}")
    proc = _exec(model)

    if proc.returncode != 0 and model and model.lower() != "auto":
        print(f"[!] [{step_name}] Model '{model}' failed; retrying with agy auto...")
        proc = _exec(None)

    if proc.returncode != 0:
        raise RuntimeError(f"[{step_name}] Execution failed (Code {proc.returncode}):\n{proc.stderr.strip()}")

    print(f"[OK] [{step_name}] Completed.")
    return proc.stdout.strip()
