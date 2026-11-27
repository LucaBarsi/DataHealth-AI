"""Private deployment entrypoint for the full synthetic DataHealth AI application.

This wrapper prepares the original read-only SQLite/ChromaDB assets before
launching Clinical_Assistant.py. The original local entrypoint remains unchanged.

Not production-ready: model inference still expects local Ollama. Keep the
cloud application private until inference and public-access safeguards are tested.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from pathlib import Path, PurePosixPath
import os
import sqlite3
import stat
import tempfile
from zipfile import ZipFile

from huggingface_hub import hf_hub_download
import streamlit as st

from src.ml_dashboard_data import REQUIRED_FILES, read_report

ROOT = Path(__file__).resolve().parent
REPO_ID = "barsi-luca97/datahealth-ai-deployment-assets"
ARCHIVE_NAME = "datahealth-ai-assets.zip"
ARCHIVE_SHA256 = "857799e5191de332771daf868c61a50269886e08fab8d4f5966ef81fb56dda26"
DATABASE = ROOT / "data/gold/datahealth.db"
CHROMA_DIR = ROOT / "data/vectorstore/chroma"
EXPECTED_COLLECTION = "synthetic_current_clinical_documents"
MAX_UNPACKED_BYTES = 128 * 1024 * 1024
REPORT_ARCHIVE = "phase18-reports.zip"
REPORT_SHA256 = "3428acd1b4e9c3c907f90118ccfd7414f1f4c6134dcd56862f94274135a36464"
REPORT_DIR = ROOT / "reports/ml/phase18"
REPORT_MAX_UNPACKED_BYTES = 256 * 1024


def _validate_database(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError("Synthetic Gold database is missing")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Synthetic Gold database integrity check failed")
        if db.execute("SELECT COUNT(*) FROM patients").fetchone()[0] != 112:
            raise RuntimeError("Unexpected number of synthetic patients")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("Synthetic Gold database has broken foreign keys")


def _validate_chroma(path: Path) -> None:
    if not path.is_dir():
        raise RuntimeError("ChromaDB index is missing")
    import chromadb

    client = chromadb.PersistentClient(path=str(path))
    collection = client.get_collection(EXPECTED_COLLECTION)
    if collection.count() != 198:
        raise RuntimeError("Unexpected number of indexed synthetic passages")
    meta = collection.metadata or {}
    if meta.get("embedding_model") != "nomic-embed-text":
        raise RuntimeError("Unexpected embedding model in the index")
    if meta.get("dataset") != "synthetic_synthea":
        raise RuntimeError("Unexpected source label in the index")


def _extract_checked(zip_path: Path, folder: Path) -> None:
    """Accept only the known archive layout; reject traversal and symlinks."""
    with ZipFile(zip_path) as archive:
        items = archive.infolist()
        names = [item.filename for item in items if not item.is_dir()]
        if len(names) != 6 or "datahealth.db" not in names:
            raise RuntimeError("Unexpected asset package contents")
        if archive.testzip() is not None:
            raise RuntimeError("Damaged asset package")
        if sum(item.file_size for item in items) > MAX_UNPACKED_BYTES:
            raise RuntimeError("Asset package exceeds the unpacked size limit")
        for item in items:
            name = item.filename
            path = PurePosixPath(name)
            if (not name or "\\" in name or path.is_absolute()
                    or any(part in ("", ".", "..") for part in path.parts)
                    or not (name == "datahealth.db" or name.startswith("chroma/"))):
                raise RuntimeError("Unexpected path in asset package")
            unix_mode = (item.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(unix_mode):
                raise RuntimeError("Symlinks are not allowed in the asset package")
        if len(set(names)) != len(names):
            raise RuntimeError("Duplicate files in the asset package")
        archive.extractall(folder)


def _prepare_assets(token: str) -> None:
    if DATABASE.exists() and CHROMA_DIR.is_dir():
        _validate_database(DATABASE)
        _validate_chroma(CHROMA_DIR)
        return

    downloaded = Path(hf_hub_download(
        repo_id=REPO_ID,
        filename=ARCHIVE_NAME,
        repo_type="dataset",
        token=token,
    ))
    actual_hash = sha256(downloaded.read_bytes()).hexdigest()
    if actual_hash.lower() != ARCHIVE_SHA256:
        raise RuntimeError("Asset archive checksum does not match the audited copy")

    (ROOT / "data").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="datahealth-stage-", dir=ROOT / "data") as tmp:
        staging = Path(tmp)
        _extract_checked(downloaded, staging)
        _validate_database(staging / "datahealth.db")
        # Do not open ChromaDB inside TemporaryDirectory: on Windows the
        # PersistentClient holds native index files open, blocking cleanup.
        # The downloaded ZIP has already passed a fixed SHA256 check; validate
        # the extracted directory layout before moving it to its final path.
        if not (staging / "chroma" / "chroma.sqlite3").is_file():
            raise RuntimeError("ChromaDB SQLite index file is missing from the package")
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        CHROMA_DIR.parent.mkdir(parents=True, exist_ok=True)
        if not DATABASE.exists():
            os.replace(staging / "datahealth.db", DATABASE)
        if not CHROMA_DIR.exists():
            os.replace(staging / "chroma", CHROMA_DIR)
    _validate_database(DATABASE)
    _validate_chroma(CHROMA_DIR)


def _prepare_reports(token: str) -> None:
    """Download and validate the four synthetic, aggregate Phase 18 reports."""
    if REPORT_DIR.is_dir():
        read_report(REPORT_DIR)
        return
    if not token:
        raise RuntimeError("HF_TOKEN is needed to obtain private Phase 18 reports")

    downloaded = Path(hf_hub_download(
        repo_id=REPO_ID,
        filename=REPORT_ARCHIVE,
        repo_type="dataset",
        token=token,
    ))
    if sha256(downloaded.read_bytes()).hexdigest() != REPORT_SHA256:
        raise RuntimeError("Phase 18 report checksum mismatch")

    expected = {f"reports/ml/phase18/{name}" for name in REQUIRED_FILES}
    with ZipFile(downloaded) as archive:
        members = archive.infolist()
        if (len(members) != len(expected)
                or {member.filename for member in members} != expected
                or sum(member.file_size for member in members) > REPORT_MAX_UNPACKED_BYTES
                or archive.testzip() is not None):
            raise RuntimeError("Unexpected or corrupt Phase 18 report package")
        for member in members:
            if stat.S_ISLNK((member.external_attr >> 16) & 0xFFFF):
                raise RuntimeError("Symlinks are not allowed in Phase 18 report package")

        (ROOT / "data").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="datahealth-report-", dir=ROOT / "data") as tmp:
            temporary_root = Path(tmp)
            archive.extractall(temporary_root)
            extracted = temporary_root / "reports/ml/phase18"
            read_report(extracted)
            REPORT_DIR.parent.mkdir(parents=True, exist_ok=True)
            if REPORT_DIR.exists():
                raise RuntimeError("Phase 18 report directory exists but is incomplete")
            os.replace(extracted, REPORT_DIR)
    read_report(REPORT_DIR)


@st.cache_resource(show_spinner=False)
def initialize_assets(token: str) -> bool:
    _prepare_assets(token)
    _prepare_reports(token)
    return True


def launch() -> None:
    try:
        # On local preflight, use validated existing assets without reading
        # Streamlit Secrets, which may not exist on the developer machine.
        if (DATABASE.is_file() and CHROMA_DIR.is_dir()
                and REPORT_DIR.is_dir()):
            token = ""
        else:
            token = str(st.secrets.get("HF_TOKEN", "")).strip()
            if not token:
                raise RuntimeError("HF_TOKEN is not configured in Streamlit Secrets")
        initialize_assets(token)
    except Exception as exc:
        st.set_page_config(page_title="DataHealth AI — Setup", layout="centered")
        st.error("The private synthetic-data package could not be prepared.")
        st.caption(f"Setup check: {type(exc).__name__}. Review the app's private configuration and logs.")
        st.stop()

    # Hosted preview uses SQL-only retrieval and bounded Mixlayer inference.
    # Directly launching Clinical_Assistant.py retains the local Ollama path.
    os.environ["DATAHEALTH_HOSTED_SQL"] = "1"
    # Explicit page titles keep navigation professional without renaming files.
    navigation = st.navigation([
        st.Page(str(ROOT / "Clinical_Assistant.py"), title="DataHealth AI", icon="🧬", default=True),
        st.Page(str(ROOT / "pages/1_Analytics_Dashboard.py"), title="Analytics Dashboard", icon="📊"),
        st.Page(str(ROOT / "pages/2_ML_Forecasting.py"), title="ML Forecasting", icon="📈"),
    ])
    navigation.run()


if __name__ == "__main__":
    launch()
