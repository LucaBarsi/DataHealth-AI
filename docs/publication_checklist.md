# Public Repository Publication Checklist

**Scope:** initial source-code repository. The full live application is not yet deployed.

## Audit and provenance

- [ ] Existing `.gitignore` retained and Phase 12 additions reviewed/appended.
- [ ] `python -m scripts.repository_preflight` completed with no blockers after staging intended files.
- [ ] `git diff --cached --name-only` reviewed line by line.
- [ ] No real patient information, personal contact details, API credentials, `.env`, `.venv`, local model artifacts or generated databases are staged.
- [ ] FHIR sample source and synthetic-only limitation clearly disclosed.
- [ ] Git history and remote branches inspected if repository existed before this phase.

## Documentation and reproducibility

- [ ] README reflects the two Streamlit pages and actual local run command.
- [ ] Python version and `requirements_local.txt` (or existing per-phase requirements) listed.
- [ ] Separate steps to rebuild SQLite and ChromaDB are documented.
- [ ] Architecture diagram distinguishes local MVP from future Azure/AWS deployment.
- [ ] Evaluation metrics reported with sample size and limitations.
- [ ] Screenshots do not expose local user names, absolute personal paths or credentials.

## Cloud readiness — separate future gate

- [ ] Hosted model endpoint and authentication configured (no direct public Ollama port).
- [ ] Hosted/packaged synthetic database and Chroma index accessible.
- [ ] App can start from a fresh cloud environment without local Windows dependencies.
- [ ] Request limits and cost controls defined.
- [ ] Application clearly marked as synthetic-only, educational and not for clinical use.
