"""
finanzamt.ui.api
~~~~~~~~~~~~~~~~
FastAPI backend for the finanzamt web UI.

Every receipt/tax endpoint accepts an optional ``?db=`` query parameter
(absolute path to a .db file). If omitted, DEFAULT_DB_PATH is used.
This lets the frontend switch between multiple databases without restarting.

Endpoints
---------
GET  /health
GET  /config
GET  /databases                    — list .db files under ~/.finanzamt/
POST /receipts/upload
GET  /receipts
GET  /receipts/{id}
GET  /receipts/{id}/pdf
PATCH /receipts/{id}
DELETE /receipts/{id}
GET  /tax/ustva?quarter=1&year=2024
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import Annotated, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# finanzamt integration
# ---------------------------------------------------------------------------
try:
    from finanzamt.agent import FinanceAgent
    from finanzamt.config import Config
    from finanzamt.prompts import RECEIPT_CATEGORIES
    from finanzamt.storage.sqlite import DEFAULT_DB_PATH, SQLiteRepository
    from finanzamt.tax.ustva import generate_ustva
    _LIB_AVAILABLE = True
    _cfg = Config()
except ImportError:
    _LIB_AVAILABLE = False
    _cfg = None  # type: ignore
    RECEIPT_CATEGORIES = [
        "material", "equipment", "internet", "telecommunication",
        "software", "education", "travel", "utilities",
        "insurance", "taxes", "other",
    ]
    DEFAULT_DB_PATH = Path.home() / ".finanzamt" / "finanzamt.db"

FINANZAMT_DIR = DEFAULT_DB_PATH.parent

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

def _resolve_db(db: Optional[str]) -> Path:
    """Return the DB path to use — explicit arg or default."""
    if db:
        p = Path(db)
        if not p.suffix == ".db":
            raise HTTPException(status_code=400, detail="db must be a .db file path.")
        return p
    return DEFAULT_DB_PATH


def _pdf_dir(db_path: Path) -> Path:
    """PDFs live in a pdfs/ subfolder next to the .db file."""
    return db_path.parent / "pdfs"


def _repo(db_path: Path) -> SQLiteRepository:
    if not _LIB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="finanzamt library not installed.",
        )
    return SQLiteRepository(db_path=db_path)


def _receipt_to_response(r, db_path: Path) -> dict:
    d = r.to_dict()
    pdf_path = _pdf_dir(db_path) / f"{r.id}.pdf"
    d["pdf_url"] = f"/receipts/{r.id}/pdf" if pdf_path.exists() else None
    return d


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
def health():
    return {
        "status":            "ok",
        "library_available": _LIB_AVAILABLE,
        "db_path":           str(DEFAULT_DB_PATH),
        "db_exists":         DEFAULT_DB_PATH.exists(),
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
        "default_db":      str(DEFAULT_DB_PATH),
    }


@app.get("/databases", tags=["meta"])
def list_databases():
    """
    Scan ~/.finanzamt/ (recursively one level) for .db files and return
    each one with its path, size, and receipt count.
    """
    results = []
    if FINANZAMT_DIR.exists():
        # Direct children first, then one level of subdirs
        candidates = list(FINANZAMT_DIR.glob("*.db")) + list(FINANZAMT_DIR.glob("*/*.db"))
        for db_file in sorted(candidates):
            entry: dict = {
                "name":     db_file.name,
                "path":     str(db_file),
                "dir":      str(db_file.parent),
                "size_kb":  round(db_file.stat().st_size / 1024, 1) if db_file.exists() else 0,
                "receipts": 0,
                "is_default": db_file == DEFAULT_DB_PATH,
            }
            # Try to count receipts without crashing
            if _LIB_AVAILABLE:
                try:
                    with SQLiteRepository(db_path=db_file) as repo:
                        entry["receipts"] = sum(1 for _ in repo.list_all())
                except Exception:
                    pass
            results.append(entry)

    return {
        "databases": results,
        "default":   str(DEFAULT_DB_PATH),
    }


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

    db_path = _resolve_db(db)
    suffix  = Path(file.filename or "receipt").suffix or ".pdf"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
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