"""
finanzamt.ui.api
~~~~~~~~~~~~~~~~
FastAPI backend for the finanzamt web UI.

Every receipt/tax endpoint accepts an optional ``?db=`` query parameter
(absolute path to a .db file). If omitted, the default project is used (~/.finanzamt/default/finanzamt.db).
This lets the frontend switch between multiple databases without restarting.

Endpoints
---------
GET    /health
GET    /config
GET    /projects                   — list projects under ~/.finanzamt/
POST   /projects                   — create a new project folder
DELETE /projects/{name}            — delete a project (keeps PDFs optional)
GET    /databases                  — legacy alias for /projects
POST   /receipts/upload
GET    /receipts
GET    /receipts/{id}
GET    /receipts/{id}/pdf
PATCH  /receipts/{id}
DELETE /receipts/{id}
GET    /tax/ustva?quarter=1&year=2024
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# finanzamt integration
# ---------------------------------------------------------------------------
try:
    from finanzamt.agents.agent import FinanceAgent
    from finanzamt.agents.config import Config
    from finanzamt.agents.prompts import RECEIPT_CATEGORIES
    from finanzamt.storage.sqlite import SQLiteRepository
    from finanzamt.storage.project import (
        FINANZAMT_HOME, layout_from_db_path, list_projects,
        resolve_project, validate_project_name, DB_FILENAME, DEFAULT_PROJECT,
    )
    from finanzamt.tax.ustva import generate_ustva
    _LIB_AVAILABLE = True
    _cfg = Config()
except ImportError as _import_err:
    import traceback, sys
    print("\n[finanzamt] IMPORT ERROR — library failed to load:", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    print(file=sys.stderr)
    _LIB_AVAILABLE = False
    _cfg = None  # type: ignore
    RECEIPT_CATEGORIES = [
        "material", "equipment", "internet", "telecommunication",
        "software", "education", "travel", "utilities",
        "insurance", "taxes", "other",
    ]
    FINANZAMT_HOME     = Path.home() / ".finanzamt"
    DB_FILENAME        = "finanzamt.db"
    DEFAULT_PROJECT    = "default"

    def list_projects():       return []      # type: ignore
    def resolve_project(n=None): return None  # type: ignore
    def validate_project_name(n): return None # type: ignore
    def layout_from_db_path(p): return None   # type: ignore

# Computed once at startup — never relies on sqlite.py's DEFAULT_DB_PATH
_DEFAULT_LAYOUT = resolve_project(DEFAULT_PROJECT)
_DEFAULT_DB     = _DEFAULT_LAYOUT.db_path

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp",
    "image/tiff", "application/pdf",
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="finanzamt API",
    version="0.2.0",
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_layout(db: Optional[str], project: Optional[str] = None):
    """
    Resolve a ProjectLayout from either an explicit db path or a project name.
    Priority: explicit db path > project name > "default".
    Always returns a proper ProjectLayout — never the old flat path.
    """
    if db:
        p = Path(db)
        if p.suffix != ".db":
            raise HTTPException(status_code=400, detail="db must be a .db file path.")
        return layout_from_db_path(p)
    return resolve_project(project or DEFAULT_PROJECT)


def _resolve_db(db: Optional[str]) -> Path:
    """Backward-compat shim — returns the db_path from _resolve_layout."""
    return _resolve_layout(db).db_path


def _pdf_dir(db_path: Path) -> Path:
    """PDFs live in pdfs/ inside the project root (sibling of finanzamt.db)."""
    layout = layout_from_db_path(db_path)
    return layout.pdfs_dir if layout else db_path.parent / "pdfs"


def _repo(db_path: Path) -> SQLiteRepository:
    if not _LIB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="finanzamt library not installed.",
        )
    return SQLiteRepository(db_path=db_path)


def _require_db(db_path: Path) -> None:
    """Raise 404 if the database file doesn't exist yet.
    Prevents SQLite from creating an empty file on read-only requests.
    The db is created lazily on first write (upload).
    """
    if not db_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No database at {db_path}. Upload a receipt to initialise it.",
        )


def _receipt_to_response(r, db_path: Path) -> dict:
    d = r.to_dict()
    pdf_path = _pdf_dir(db_path) / f"{r.id}.pdf"
    d["pdf_url"] = f"/receipts/{r.id}/pdf" if pdf_path.exists() else None
    return d


def _project_entry(layout, active_db: Optional[str] = None) -> dict:
    """Serialise a ProjectLayout to a JSON-safe dict."""
    receipt_count = 0
    size_kb = 0.0
    if layout.db_path.exists():
        size_kb = round(layout.db_path.stat().st_size / 1024, 1)
        if _LIB_AVAILABLE:
            try:
                with SQLiteRepository(db_path=layout.db_path) as repo:
                    receipt_count = sum(1 for _ in repo.list_all())
            except Exception:
                pass
    is_active = (
        active_db == str(layout.db_path)
        or (active_db is None and layout.is_default)
    )
    return {
        "name":       layout.name,
        "path":       str(layout.db_path),
        "root":       str(layout.root),
        "size_kb":    size_kb,
        "receipts":   receipt_count,
        "is_default": layout.is_default,
        "is_active":  is_active,
        "exists":     layout.db_path.exists(),
    }


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
def health():
    return {
        "status":            "ok",
        "library_available": _LIB_AVAILABLE,
        "db_path":           str(_DEFAULT_DB),
        "db_exists":         _DEFAULT_DB.exists(),
    }


@app.get("/config", tags=["meta"])
def get_config():
    if not _LIB_AVAILABLE or _cfg is None:
        return {"error": "finanzamt library not available", "categories": RECEIPT_CATEGORIES}
    mc = _cfg.get_model_config()
    return {
        "ollama_base_url": mc.base_url,
        "model":           mc.model,
        "max_retries":     mc.max_retries,
        "request_timeout": mc.timeout,
        "categories":      RECEIPT_CATEGORIES,
        "default_db":      str(_DEFAULT_DB),
    }


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@app.get("/projects", tags=["projects"])
def list_projects_endpoint(active_db: Optional[str] = Query(default=None)):
    """
    List all projects under ~/.finanzamt/.
    Each project is a subdirectory containing finanzamt.db.
    """
    projects = list_projects()
    return {
        "projects":    [_project_entry(p, active_db) for p in projects],
        "finanzamt_home": str(FINANZAMT_HOME),
        "default_db":  str(_DEFAULT_DB),
    }


@app.post("/projects", status_code=status.HTTP_201_CREATED, tags=["projects"])
def create_project(body: dict = Body(...)):
    """
    Create a new project folder and initialise its SQLite database.
    Body: { "name": "acme-gmbh-2025" }
    """
    name = (body.get("name") or "").strip().lower()
    err  = validate_project_name(name)
    if err:
        raise HTTPException(status_code=400, detail=err)

    layout = resolve_project(name)
    if layout.db_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Project '{name}' already exists.",
        )

    # Create directories and initialise DB (SQLite creates on first connect)
    layout.create_dirs()
    if _LIB_AVAILABLE:
        try:
            with SQLiteRepository(db_path=layout.db_path):
                pass   # schema init happens in __init__
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"DB init failed: {exc}") from exc

    return _project_entry(layout)


@app.delete("/projects/{name}", status_code=status.HTTP_204_NO_CONTENT, tags=["projects"])
def delete_project(name: str, keep_pdfs: bool = Query(default=True)):
    """
    Delete a project's database (and optionally its debug folder).
    PDFs are kept by default (keep_pdfs=true).
    The 'default' project cannot be deleted.
    """
    if name == "default":
        raise HTTPException(status_code=403, detail="Cannot delete the default project.")

    layout = resolve_project(name)
    if not layout.db_path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found.")

    import shutil
    layout.db_path.unlink(missing_ok=True)
    if layout.debug_dir.exists():
        shutil.rmtree(layout.debug_dir, ignore_errors=True)
    if not keep_pdfs and layout.pdfs_dir.exists():
        shutil.rmtree(layout.pdfs_dir, ignore_errors=True)
    # Remove project root only if now empty
    try:
        layout.root.rmdir()
    except OSError:
        pass  # not empty — PDFs still there, leave it


# Legacy alias — the frontend used /databases before the project refactor
@app.get("/databases", tags=["projects"])
def list_databases(active_db: Optional[str] = Query(default=None)):
    """Legacy alias for GET /projects — kept for backwards compatibility."""
    return list_projects_endpoint(active_db=active_db)


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

@app.post("/receipts/upload", status_code=status.HTTP_201_CREATED, tags=["receipts"])
async def upload_receipt(
    file:         Annotated[UploadFile, File(description="Receipt PDF or image")],
    receipt_type: str           = Query(default="purchase", enum=["purchase", "sale"]),
    db:           Optional[str] = Query(default=None, description="DB file path"),
):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{file.content_type}'.",
        )
    if not _LIB_AVAILABLE:
        raise HTTPException(status_code=503, detail="finanzamt library not installed.")

    layout  = _resolve_layout(db)
    db_path = layout.db_path
    suffix  = Path(file.filename or "receipt").suffix or ".pdf"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        # Pass db_path explicitly so FinanceAgent uses this exact layout.
        # layout_from_db_path in agent.py will re-derive the project folder
        # correctly from the path we resolved above.
        agent  = FinanceAgent(db_path=db_path)
        result = agent.process_receipt(tmp_path, receipt_type=receipt_type)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Extraction failed: {result.error_message}",
        )

    response = _receipt_to_response(result.data, db_path)
    response["duplicate"] = result.duplicate
    if result.duplicate:
        response["message"] = "A receipt with identical content already exists."
    return response


@app.get("/receipts", tags=["receipts"])
def list_receipts(
    receipt_type: Optional[str] = Query(default=None, alias="type", enum=["purchase", "sale"]),
    category:     Optional[str] = Query(default=None),
    quarter:      Optional[int] = Query(default=None, ge=1, le=4),
    year:         Optional[int] = Query(default=None, ge=2000, le=2100),
    db:           Optional[str] = Query(default=None),
):
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {"receipts": [], "total": 0}
    with _repo(db_path) as repo:
        if quarter and year:
            starts = {1: (1,1), 2: (4,1), 3: (7,1), 4: (10,1)}
            ends   = {1: (3,31), 2: (6,30), 3: (9,30), 4: (12,31)}
            ms, ds = starts[quarter]; me, de = ends[quarter]
            receipts = list(repo.find_by_period(date(year,ms,ds), date(year,me,de)))
        elif receipt_type:
            receipts = list(repo.find_by_type(receipt_type))
        elif category:
            receipts = list(repo.find_by_category(category))
        else:
            receipts = list(repo.list_all())

    if receipt_type:
        receipts = [r for r in receipts if str(r.receipt_type) == receipt_type]
    if category:
        receipts = [r for r in receipts if str(r.category) == category]

    return {
        "receipts": [_receipt_to_response(r, db_path) for r in receipts],
        "total":    len(receipts),
    }


@app.get("/receipts/{receipt_id}", tags=["receipts"])
def get_receipt(receipt_id: str, db: Optional[str] = Query(default=None)):
    db_path = _resolve_db(db)
    _require_db(db_path)
    with _repo(db_path) as repo:
        receipt = repo.get(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    return _receipt_to_response(receipt, db_path)


@app.get("/receipts/{receipt_id}/pdf", tags=["receipts"])
def get_receipt_pdf(receipt_id: str, db: Optional[str] = Query(default=None)):
    db_path  = _resolve_db(db)
    pdf_path = _pdf_dir(db_path) / f"{receipt_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found.")
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


@app.patch("/receipts/{receipt_id}", tags=["receipts"])
def update_receipt(
    receipt_id: str,
    fields:     dict,
    db:         Optional[str] = Query(default=None),
):
    db_path = _resolve_db(db)
    with _repo(db_path) as repo:
        updated = repo.update(receipt_id, fields)
        if not updated:
            raise HTTPException(status_code=404, detail="Receipt not found.")
        receipt = repo.get(receipt_id)
    return _receipt_to_response(receipt, db_path)


@app.delete("/receipts/{receipt_id}", status_code=204, tags=["receipts"])
def delete_receipt(receipt_id: str, db: Optional[str] = Query(default=None)):
    db_path = _resolve_db(db)
    with _repo(db_path) as repo:
        if not repo.delete(receipt_id):
            raise HTTPException(status_code=404, detail="Receipt not found.")


# ---------------------------------------------------------------------------
# Tax
# ---------------------------------------------------------------------------

@app.get("/counterparties/verified", tags=["counterparties"])
def list_verified_counterparties(db: Optional[str] = Query(default=None)):
    """Return all counterparties marked as verified."""
    db_path = _resolve_db(db)
    if not db_path.exists():
        return {"counterparties": []}
    with _repo(db_path) as repo:
        rows = repo.list_verified_counterparties()
    return {"counterparties": rows}


@app.patch("/counterparties/{cp_id}/verify", tags=["counterparties"])
def set_counterparty_verified(
    cp_id: str,
    body: dict,
    db: Optional[str] = Query(default=None),
):
    """Set verified=true/false on a counterparty."""
    db_path = _resolve_db(db)
    verified = bool(body.get("verified", True))
    with _repo(db_path) as repo:
        repo.set_counterparty_verified(cp_id, verified)
    return {"ok": True, "cp_id": cp_id, "verified": verified}


@app.get("/tax/ustva", tags=["tax"])
def get_ustva(
    quarter: int           = Query(..., ge=1, le=4),
    year:    int           = Query(..., ge=2000, le=2100),
    db:      Optional[str] = Query(default=None),
):
    db_path = _resolve_db(db)
    starts  = {1:(1,1),2:(4,1),3:(7,1),4:(10,1)}
    ends    = {1:(3,31),2:(6,30),3:(9,30),4:(12,31)}
    ms, ds  = starts[quarter]; me, de = ends[quarter]
    start, end = date(year,ms,ds), date(year,me,de)

    if not db_path.exists():
        return generate_ustva([], start, end).to_dict()
    with _repo(db_path) as repo:
        receipts = list(repo.find_by_period(start, end))

    return generate_ustva(receipts, start, end).to_dict()


# ---------------------------------------------------------------------------
# Static SPA (must be last)
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_not_built(full_path: str):
        return {"error": "Frontend not built yet."}