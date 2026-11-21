"""Read-only GitHub publication preflight for the DataHealth AI prototype.

Usage from the project root:
    python -m scripts.repository_preflight --root . --output reports/deployment/preflight.json

This audit does not add, remove, upload, rewrite, or stage any files.
It does not guarantee that a repository is free of sensitive information.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REQUIRED = (
    "Clinical_Assistant.py",
    "pages/1_Analytics_Dashboard.py",
    "src/hybrid_assistant.py",
    "src/reliable_assistant.py",
    "src/analytics_backend.py",
    "tests",
    "docs",
    ".gitignore",
)

IGNORE_PROBES = (
    ".venv/Lib/site-packages/example.py",
    ".env",
    ".streamlit/secrets.toml",
    "data/gold/datahealth.db",
    "data/vectorstore/chroma/chroma.sqlite3",
    "data/raw/fhir/patient.json",
    "reports/llm_evaluation/full_run/evaluation_results.jsonl",
)

IGNORED_PARTS = {".venv", "venv", "__pycache__", ".git", ".pytest_cache"}
ALLOWED_ENV_FILES = {".env.example"}
SENSITIVE_EXTENSIONS = {".pem", ".p12", ".pfx", ".key", ".gguf", ".safetensors", ".ckpt"}
SENSITIVE_BASENAMES = {"secrets.toml", "id_rsa", "id_ed25519", "service-account.json", "credentials.json"}
DATA_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
MAX_TEXT_BYTES = 1_000_000
LARGE_FILE_BYTES = 20 * 1024 * 1024

# Best-effort detector only: manual inspection remains mandatory.
LITERAL_SECRET_RE = re.compile(
    r"(?im)^\s*(?:[A-Z_]*?(?:API[_-]?KEY|ACCESS[_-]?TOKEN|SECRET|PASSWORD|PRIVATE[_-]?KEY))\s*[:=]\s*['\"]([^'\"\r\n]{8,})['\"]",
)
SAFE_EXAMPLE_VALUES = ("example", "placeholder", "replace", "your_", "dummy", "not-a-real", "changeme")


def is_sensitive_path(path: str) -> bool:
    """Conservatively block local datasets, credentials, caches and models."""
    norm = path.replace("\\", "/").strip("/")
    p = PurePosixPath(norm)
    parts = [s.lower() for s in p.parts]
    if not parts:
        return False
    name = parts[-1]
    if any(part in IGNORED_PARTS for part in parts):
        return True
    if parts[0] in {"data", "reports"}:
        return True
    if name in ALLOWED_ENV_FILES:
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name in SENSITIVE_BASENAMES or name.startswith("credentials-"):
        return True
    if name == "secrets.toml" or p.suffix.lower() in SENSITIVE_EXTENSIONS | DATA_EXTENSIONS:
        return True
    if norm.lower().startswith(".streamlit/") and "secrets" in name:
        return True
    return False


def has_literal_secret(text: str) -> bool:
    """Warn on obvious hard-coded secrets, without logging the secret itself."""
    for match in LITERAL_SECRET_RE.finditer(text):
        literal = match.group(1).strip().lower()
        if not any(marker in literal for marker in SAFE_EXAMPLE_VALUES):
            return True
    return False


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )


def git_tracking(root: Path) -> tuple[str, list[str]]:
    if shutil.which("git") is None:
        return "GIT_NOT_INSTALLED", []
    state = _git(root, "rev-parse", "--is-inside-work-tree")
    if state.returncode != 0 or state.stdout.strip() != "true":
        return "GIT_NOT_INITIALIZED", []
    result = _git(root, "ls-files", "--cached", "--full-name")
    if result.returncode != 0:
        return "GIT_TRACKING_UNAVAILABLE", []
    return "GIT_AVAILABLE", [x.strip() for x in result.stdout.splitlines() if x.strip()]


def check_ignore_rules(root: Path, git_state: str) -> list[str]:
    """Return paths that are not ignored by current effective Git rules."""
    if git_state != "GIT_AVAILABLE":
        return []
    not_ignored = []
    for probe in IGNORE_PROBES:
        result = _git(root, "check-ignore", "--quiet", probe)
        if result.returncode != 0:
            not_ignored.append(probe)
    return not_ignored


def audit(root: Path) -> dict:
    root = root.resolve()
    missing = [p for p in REQUIRED if not (root / p).exists()]
    git_state, tracked = git_tracking(root)
    sensitive = sorted({p for p in tracked if is_sensitive_path(p)})
    large = []
    literal_secret_candidates = []
    for rel in tracked:
        file = root / rel
        if not file.is_file():
            continue
        try:
            size = file.stat().st_size
            if size > LARGE_FILE_BYTES:
                large.append({"path": rel, "bytes": size})
            if size > MAX_TEXT_BYTES or file.suffix.lower() not in {".py", ".toml", ".ini", ".json", ".yml", ".yaml", ".cfg", ".txt"}:
                continue
            if has_literal_secret(file.read_text(encoding="utf-8", errors="replace")):
                literal_secret_candidates.append(rel)
        except OSError:
            continue
    missing_ignores = check_ignore_rules(root, git_state)
    blockers = []
    if missing:
        blockers.append("Some expected project components are missing; verify the selected project root.")
    if sensitive:
        blockers.append("Sensitive, generated or local-data paths are Git-tracked; remove from Git index before publishing.")
    if literal_secret_candidates:
        blockers.append("Potential hard-coded secrets in Git-tracked source files need manual review.")
    if large:
        blockers.append("Large Git-tracked files need manual assessment.")
    if missing_ignores:
        blockers.append("Current Git ignore rules do not exclude every recommended local path.")
    warnings = [
        "This audit is a heuristic. Manually inspect every staged file and Git history before publication.",
        "The public Streamlit app will not work with a local-only SQLite/ChromaDB/Ollama backend; remote services are not configured.",
        "A source identifier is not medical evidence validation; this prototype is for synthetic data only.",
    ]
    if git_state != "GIT_AVAILABLE":
        warnings.append("Initialize Git and rerun the audit after staging intended source files.")
    if not tracked and git_state == "GIT_AVAILABLE":
        warnings.append("Git has no tracked files yet; rerun after 'git add' to inspect the staged source set.")
    return {
        "project": "DataHealth AI",
        "phase": "Phase 12 — GitHub & Deployment Readiness",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "git_state": git_state,
        "tracked_file_count": len(tracked),
        "missing_expected_components": missing,
        "tracked_sensitive_or_generated_paths": sensitive,
        "tracked_large_files": large,
        "potential_hardcoded_secret_paths": sorted(literal_secret_candidates),
        "missing_recommended_gitignore_coverage": missing_ignores,
        "local_dependencies": {
            "sqlite_database_present": (root / "data/gold/datahealth.db").is_file(),
            "chroma_store_present": (root / "data/vectorstore/chroma").is_dir(),
            "streamlit_entrypoint_present": (root / "Clinical_Assistant.py").is_file(),
            "ollama_url_in_code_is_local_only": True,
        },
        "git_publication_review_status": "BLOCKED" if blockers else "READY_FOR_MANUAL_REVIEW",
        "cloud_application_status": "NOT_DEPLOYABLE_AS_IS_LOCAL_BACKEND",
        "blockers": blockers,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("reports/deployment/preflight.json"))
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error(f"Project directory does not exist: {args.root}")
    result = audit(args.root)
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    brief = {
        "git_state": result["git_state"],
        "git_publication_review_status": result["git_publication_review_status"],
        "cloud_application_status": result["cloud_application_status"],
        "tracked_file_count": result["tracked_file_count"],
        "missing_expected_components": result["missing_expected_components"],
        "tracked_sensitive_or_generated_paths": result["tracked_sensitive_or_generated_paths"],
        "potential_hardcoded_secret_paths": result["potential_hardcoded_secret_paths"],
        "missing_recommended_gitignore_coverage": result["missing_recommended_gitignore_coverage"],
        "report_path": str(output),
    }
    print(json.dumps(brief, indent=2, ensure_ascii=False))
    return 2 if result["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
