from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
EXTRACTIONS_DIR = DATA_DIR / "extractions"
INDEX_FILE = DATA_DIR / "index.json"
BUCKET = "invoices"

load_dotenv(PROJECT_ROOT / ".env")

_client: Any = None


def supabase_enabled() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SECRET_KEY"))


def _local_extractions_exist() -> bool:
    return EXTRACTIONS_DIR.is_dir() and any(EXTRACTIONS_DIR.glob("*.json"))


def _read_remote() -> bool:
    """ECS has no local invoice files, so it reads Supabase. A dev machine keeps using local JSON."""
    return supabase_enabled() and not _local_extractions_exist()


def _client_or_raise() -> Any:
    global _client
    if _client is None:
        from supabase import create_client

        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
        try:
            _client.storage.create_bucket(BUCKET, options={"public": False})
        except Exception:
            pass
    return _client


def _bucket() -> Any:
    return _client_or_raise().storage.from_(BUCKET)


def _content_type(name: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".json": "application/json",
    }.get(Path(name).suffix.lower(), "application/octet-stream")


def _upload_object(key: str, content: bytes, content_type: str) -> None:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            _bucket().upload(
                key,
                content,
                file_options={"content-type": content_type, "upsert": "true"},
            )
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    if last_error:
        raise last_error


def _download_object(key: str) -> bytes | None:
    try:
        return _bucket().download(key)
    except Exception as exc:
        text = str(exc).lower()
        if "not found" in text or "404" in text or "object not found" in text:
            return None
        raise


def _list_names(prefix: str) -> list[str]:
    names: list[str] = []
    offset = 0
    while True:
        batch = _bucket().list(prefix, {"limit": 1000, "offset": offset})
        if not batch:
            break
        for item in batch:
            name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
            if name and not str(name).endswith("/"):
                names.append(str(name))
        if len(batch) < 1000:
            break
        offset += len(batch)
    return names


def _remove_objects(keys: list[str]) -> None:
    if keys:
        _bucket().remove(keys)


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)


def save_upload(filename: str, content: bytes) -> Path:
    ensure_dirs()
    safe_name = filename.replace("\\", "_").replace("/", "_")
    path = UPLOAD_DIR / safe_name
    if path.exists():
        stem = path.stem
        suffix = path.suffix
        counter = 1
        while path.exists():
            path = UPLOAD_DIR / f"{stem}_{counter}{suffix}"
            counter += 1
    path.write_bytes(content)
    if supabase_enabled():
        _upload_object(f"uploads/{path.name}", content, _content_type(path.name))
    return path


def extraction_path(job_id: str) -> Path:
    return EXTRACTIONS_DIR / f"{job_id}.json"


def save_extraction(job_id: str, payload: dict[str, Any]) -> Path:
    ensure_dirs()
    path = extraction_path(job_id)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    path.write_bytes(encoded)
    _update_index(job_id, payload)
    if supabase_enabled():
        _upload_object(f"extractions/{job_id}.json", encoded, "application/json")
        if INDEX_FILE.exists():
            _upload_object("index.json", INDEX_FILE.read_bytes(), "application/json")
    return path


def load_extraction(job_id: str) -> dict[str, Any] | None:
    if _read_remote():
        raw = _download_object(f"extractions/{job_id}.json")
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8-sig"))

    path = extraction_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_all_extractions() -> dict[str, Any]:
    if _read_remote():
        names = [name for name in _list_names("extractions") if name.endswith(".json")]

        def _load(name: str) -> tuple[str, dict[str, Any] | None]:
            raw = _download_object(f"extractions/{name}")
            if raw is None:
                return name, None
            return name, json.loads(raw.decode("utf-8-sig"))

        jobs: dict[str, Any] = {}
        for name in names:
            _name, payload = _load(name)
            if payload is not None:
                jobs[Path(_name).stem] = payload
        return jobs

    ensure_dirs()
    jobs = {}
    for path in sorted(EXTRACTIONS_DIR.glob("*.json"), reverse=True):
        jobs[path.stem] = json.loads(path.read_text(encoding="utf-8-sig"))
    return jobs


def build_extraction_payload(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    document = job.get("document") or {}
    audit = document.get("audit", {})
    audit["job_id"] = job_id
    audit["saved_at"] = datetime.now(timezone.utc).isoformat()
    if supabase_enabled():
        audit["json_path"] = f"extractions/{job_id}.json"
        audit["storage_bucket"] = BUCKET
    else:
        audit["json_path"] = str(extraction_path(job_id).relative_to(PROJECT_ROOT)).replace("\\", "/")
    document["audit"] = audit

    return {
        "job_id": job_id,
        "status": job.get("status", "completed"),
        "saved_at": audit["saved_at"],
        "json_path": audit["json_path"],
        "document": document,
    }


def _read_index() -> dict[str, Any]:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8-sig"))
    if supabase_enabled():
        raw = _download_object("index.json")
        if raw:
            return json.loads(raw.decode("utf-8-sig"))
    return {"jobs": [], "count": 0}


def _update_index(job_id: str, payload: dict[str, Any]) -> None:
    ensure_dirs()
    index = _read_index()

    document = payload.get("document") or {}
    header = document.get("header") or {}
    vendor = document.get("vendor") or {}
    totals = document.get("totals") or {}
    line_items = document.get("line_items") or []

    summary = {
        "job_id": job_id,
        "status": payload.get("status", "completed"),
        "saved_at": payload.get("saved_at"),
        "json_path": payload.get("json_path"),
        "file_name": document.get("audit", {}).get("file_name", ""),
        "document_type": document.get("document_type", "unknown"),
        "invoice_number": header.get("invoice_number") or header.get("document_number") or "",
        "vendor": vendor.get("name") or vendor.get("gstin") or "",
        "line_item_count": len(line_items),
        "grand_total": totals.get("grand_total", 0),
    }

    jobs = [item for item in index.get("jobs", []) if item.get("job_id") != job_id]
    jobs.insert(0, summary)
    index_payload = {"jobs": jobs, "count": len(jobs)}
    INDEX_FILE.write_text(
        json.dumps(index_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8-sig",
    )


def load_index() -> dict[str, Any]:
    if _read_remote():
        raw = _download_object("index.json")
        if raw is None:
            return {"jobs": [], "count": 0}
        return json.loads(raw.decode("utf-8-sig"))

    ensure_dirs()
    if not INDEX_FILE.exists():
        return {"jobs": [], "count": 0}
    return json.loads(INDEX_FILE.read_text(encoding="utf-8-sig"))


def _remove_from_index(job_id: str) -> None:
    ensure_dirs()
    if not INDEX_FILE.exists() and not supabase_enabled():
        return
    index = _read_index()
    jobs = [item for item in index.get("jobs", []) if item.get("job_id") != job_id]
    INDEX_FILE.write_text(
        json.dumps({"jobs": jobs, "count": len(jobs)}, indent=2, ensure_ascii=False),
        encoding="utf-8-sig",
    )


def _delete_uploaded_file(source_uri: str) -> None:
    if not source_uri:
        return
    source_path = Path(source_uri)
    if not source_path.exists():
        return
    try:
        source_path.resolve().relative_to(UPLOAD_DIR.resolve())
    except ValueError:
        return
    source_path.unlink(missing_ok=True)


def delete_document(job_id: str) -> bool:
    ensure_dirs()
    payload = load_extraction(job_id)
    deleted = False
    upload_name = ""

    if payload:
        document = payload.get("document") or {}
        audit = document.get("audit") or {}
        source_uri = audit.get("source_uri", "")
        if source_uri:
            upload_name = Path(source_uri).name
        _delete_uploaded_file(source_uri)

        json_file = extraction_path(job_id)
        if json_file.exists():
            json_file.unlink()
            deleted = True

        _remove_from_index(job_id)
        deleted = True

    json_file = extraction_path(job_id)
    if json_file.exists():
        json_file.unlink()
        _remove_from_index(job_id)
        deleted = True

    if supabase_enabled():
        keys = [f"extractions/{job_id}.json"]
        if upload_name:
            keys.append(f"uploads/{upload_name}")
        _remove_objects(keys)
        if INDEX_FILE.exists():
            _upload_object("index.json", INDEX_FILE.read_bytes(), "application/json")
        deleted = True

    return deleted


def sync_local_to_supabase() -> dict[str, int]:
    """Upload the local data directory into the private Supabase bucket."""
    if not supabase_enabled():
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY are required")

    ensure_dirs()
    uploads = [path for path in UPLOAD_DIR.iterdir() if path.is_file()]
    extractions = list(EXTRACTIONS_DIR.glob("*.json"))
    files: list[tuple[str, Path]] = [(f"uploads/{path.name}", path) for path in uploads]
    files.extend((f"extractions/{path.name}", path) for path in extractions)
    if INDEX_FILE.exists():
        files.append(("index.json", INDEX_FILE))

    for index, (key, path) in enumerate(files, start=1):
        _upload_object(key, path.read_bytes(), _content_type(path.name))
        if index % 50 == 0 or index == len(files):
            print(f"uploaded {index}/{len(files)}", flush=True)

    return {"uploads": len(uploads), "extractions": len(extractions), "total": len(files)}
