"""Data directory resolution for the intake engine."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        path = Path(explicit)
    else:
        path = Path(os.environ.get("PFA_INTAKE_DATA", "./data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_db_path(root: Path | None = None) -> Path:
    return data_dir(root) / "work_items.sqlite3"


def store_json_path(root: Path | None = None) -> Path:
    return data_dir(root) / "work_items.json"


def audit_path(root: Path | None = None) -> Path:
    return data_dir(root) / "completions.jsonl"


def fd_queue_path(root: Path | None = None) -> Path:
    return data_dir(root) / "fd_queue.jsonl"
