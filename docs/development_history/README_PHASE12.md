# DataHealth AI — Phase 12: Deployment Readiness & GitHub Preparation

**Scope:** prepare the existing local prototype for a future public code repository, without uploading anything, changing the app, or exposing secrets and local datasets.

**Important:** this is **repository readiness**, not a working cloud deployment. The existing Streamlit pages depend on the local `datahealth.db`, ChromaDB index, and Ollama models. A cloud host does not inherit those resources.

## Add this package to the current project

Copy these files **without replacing** the existing application, scripts, data, or reports:

| Package source | Project destination | Action |
|---|---|---|
| `scripts/repository_preflight.py` | `scripts/repository_preflight.py` | Add |
| `scripts/__init__.py` | `scripts/__init__.py` | Add |
| `tests/test_repository_preflight.py` | `tests/test_repository_preflight.py` | Add |
| `docs/deployment_readiness.md` | `docs/deployment_readiness.md` | Add |
| `docs/publication_checklist.md` | `docs/publication_checklist.md` | Add |
| `gitignore_phase12_additions.txt` | Project root | Add, then append contents to your EXISTING `.gitignore` |
| `requirements_local.txt` | Project root | Add; **do not** replace previous requirement files |
| `README_GITHUB_DRAFT.md` | Project root | Optional; review before using as main README |
| `README_PHASE12.md` | Project root | Add |

## Step 1 — Verify current project from VS Code

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_repository_preflight.py" -v
.\.venv\Scripts\python.exe -m scripts.repository_preflight --root . --output "reports/deployment/preflight.json"
```

Before Git is initialized, `GIT_NOT_INITIALIZED` is expected; it is **not** a test failure. The preflight can still report missing code components. Read the generated `reports/deployment/preflight.json`.

## Step 2 — Update `.gitignore` safely

Open your existing `.gitignore` and append the contents of `gitignore_phase12_additions.txt`. Do **not** replace the existing file. Review its contents first and keep any custom rules already in place.

You can append it using PowerShell from the project root:

```powershell
Get-Content ".\gitignore_phase12_additions.txt" | Add-Content ".\.gitignore"
```

You only need to append this once. The new ignore rules prevent accidental Git staging of `data/`, `reports/`, local environments, model files, and secrets. These files remain on disk and **continue working locally**.

## Step 3 — Initialize Git only after the ignore rules are present

```powershell
git --version
git init
git status --short
```

If `git` is not recognized, install Git for Windows from https://git-scm.com/downloads/win and restart VS Code's terminal.

Next, check what Git would ignore:

```powershell
git check-ignore -v data/gold/datahealth.db
```

It should print an ignore rule. The file remains on your computer.

## Step 4 — Inspect the files BEFORE publishing

```powershell
git add .
git status --short
git diff --cached --name-only
.\.venv\Scripts\python.exe -m scripts.repository_preflight --root . --output "reports/deployment/preflight.json"
```

**Do not push** if the report is `BLOCKED`, sensitive paths are staged, or you see unknown files. Remove a file from staging without deleting it from your computer:

```powershell
git restore --staged "PATH_TO_FILE"
```

If `git restore` is unavailable because the repository has no initial commit, use `git rm --cached -- "PATH_TO_FILE"` for a staged file. Be careful: Git staging commands affect the index, not your raw datasets, as long as `--cached` is used.

The automated audit is a heuristic only; personally inspect every staged filename and review code for secrets or identifying details.

## Step 5 — Share the repository after review

Only when the audit is clear and you are comfortable with the files being public:

1. Create an empty repository on GitHub, e.g. `datahealth-ai` (no initialization files, since the local project already has a README).
2. Commit reviewed source files locally using `git commit -m "Prepare DataHealth AI public source"`.
3. Add the repository's own URL as a remote with `git remote add origin https://github.com/USERNAME/REPOSITORY.git`.
4. Choose your default branch (`git branch -M main`) and push using `git push -u origin main`.

If your project already has a Git repository or remote, **do not re-initialize, change its history, or replace the remote**; inspect it first.

## Why the app is not yet publicly deployable

The code currently calls a local Ollama HTTP API (`127.0.0.1:11434`) and reads local `data/gold/datahealth.db` plus `data/vectorstore/chroma`. GitHub hosts **source files**, not the running service. Streamlit Community Cloud runs your app in a different computer/environment.

The next phase must implement a cloud-ready backend with a hosted LLM endpoint, a packaged/reproducible synthetic dataset or managed data store, persistence for embeddings, access controls, secrets management, and reasonable request limits. Do **not** expose the Ollama port on the internet as a workaround.

The Phase 12 package intentionally makes no production security claims.

## Local restart is unchanged

```powershell
.\.venv\Scripts\python.exe -m streamlit run Clinical_Assistant.py --server.address 127.0.0.1
```

Retain the existing local files and models. This update only adds an audit and publication documentation.
