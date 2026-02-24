"""
finanzamt.ui.api
~~~~~~~~~~~~~~~~
FastAPI backend for the finanzamt web UI.

All receipt data is persisted in ~/.finanzamt/finanzamt.db via SQLiteRepository.
Original PDFs are stored in ~/.finanzamt/pdfs/<hash>.pdf by FinanceAgent.

Endpoints
---------
GET  /health                       — Liveness + library status
GET  /config                       — Runtime configuration snapshot
POST /receipts/upload              — Upload PDF → extract → save to DB
GET  /receipts                     — List receipts (?type= ?category= ?q= ?year=)
GET  /receipts/{id}                — Full receipt detail
GET  /receipts/{id}/pdf            — Stream the original PDF
PATCH /receipts/{id}               — User corrections (mutable fields only)
DELETE /receipts/{id}              — Remove from DB (PDF kept in archive)
GET  /tax/ustva?quarter=1&year=24  — UStVA report for a quarter
"""

from __future__ import annotations

import shutil
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
    from finanzamt.models import ReceiptType
    from finanzamt.prompts import RECEIPT_CATEGORIES
    from finanzamt.storage.sqlite import DEFAULT_DB_PATH, SQLiteRepository
    from finanzamt.tax.ustva import generate_ustva
    _LIB_AVAILABLE = True
    _cfg = Config()
except ImportError as _err:
    _LIB_AVAILABLE = False
    _cfg = None  # type: ignore
    RECEIPT_CATEGORIES = [
        "material", "equipment", "internet", "telecommunication",
        "software", "education", "travel", "utilities",
        "insurance", "taxes", "other",
    ]
    DEFAULT_DB_PATH = Path.home() / ".finanzamt" / "finanzamt.db"

PDF_DIR = DEFAULT_DB_PATH.parent / "pdfs"

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp",
    "image/tiff", "application/pdf",
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="finanzamt API",
    description=(
        "REST API for the finanzamt library — OCR of German receipts, "
        "structured extraction via a local Ollama LLM, and VAT reporting."
    ),
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

def _repo() -> SQLiteRepository:
    """Open a fresh repository connection (caller must close / use as ctx)."""
    if not _LIB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="finanzamt library not installed.",
        )
    return SQLiteRepository(db_path=DEFAULT_DB_PATH)


def _receipt_to_response(r) -> dict:
    """Convert a ReceiptData into a JSON-serialisable dict for the API."""
    d = r.to_dict()
    # Add PDF URL if the file exists
    pdf_path = PDF_DIR / f"{r.id}.pdf"
    d["pdf_url"] = f"/receipts/{r.id}/pdf" if pdf_path.exists() else None
    return d


# ---------------------------------------------------------------------------
# Meta routes
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
    """Return active finanzamt configuration."""
    if not _LIB_AVAILABLE or _cfg is None:
        return {"error": "finanzamt library not available", "categories": RECEIPT_CATEGORIES}
    mc = _cfg.get_model_config()
    return {
        "ollama_base_url": mc.base_url,
        "model":           mc.model,
        "max_retries":     mc.max_retries,
        "request_timeout": mc.timeout,
        "categories":      RECEIPT_CATEGORIES,
        "db_path":         str(DEFAULT_DB_PATH),
    }


# ---------------------------------------------------------------------------
# Receipt routes
# ---------------------------------------------------------------------------

@app.post("/receipts/upload", status_code=status.HTTP_201_CREATED, tags=["receipts"])
async def upload_receipt(
    file: Annotated[UploadFile, File(description="Receipt PDF or image")],
    receipt_type: str = Query(default="purchase", enum=["purchase", "sale"]),
):
    """
    Upload a receipt file, extract structured data, and save to DB.

    Returns the full extracted receipt. If the content has been uploaded
    before (same SHA-256 hash), returns the existing record with
    ``duplicate: true`` — no DB changes are made.
    """
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '{file.content_type}'. "
                f"Allowed: {sorted(ALLOWED_MIME_TYPES)}"
            ),
        )

    if not _LIB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="finanzamt library not installed.",
        )

    # Write upload to a temp file so FinanceAgent can read it as a Path
    suffix = Path(file.filename or "receipt").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        agent  = FinanceAgent()   # uses DEFAULT_DB_PATH, auto-saves + copies PDF
        result = agent.process_receipt(tmp_path, receipt_type=receipt_type)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Extraction failed: {result.error_message}",
        )

    response = _receipt_to_response(result.data)
    response["duplicate"] = result.duplicate
    if result.duplicate:
        response["message"] = (
            "A receipt with identical content already exists. "
            "No changes were made."
        )
    return response


@app.get("/receipts", tags=["receipts"])
def list_receipts(
    receipt_type: Optional[str] = Query(default=None, alias="type",
                                        enum=["purchase", "sale"]),
    category:     Optional[str] = Query(default=None),
    quarter:      Optional[int] = Query(default=None, ge=1, le=4),
    year:         Optional[int] = Query(default=None, ge=2000, le=2100),
):
    """
    List all receipts with optional filters.

    - ``?type=purchase`` / ``?type=sale``
    - ``?category=travel``
    - ``?quarter=1&year=2024``  — filter by fiscal quarter
    """
    with _repo() as repo:
        if quarter and year:
            starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
            ends   = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
            ms, ds = starts[quarter]
            me, de = ends[quarter]
            receipts = list(repo.find_by_period(date(year, ms, ds), date(year, me, de)))
        elif receipt_type:
            receipts = list(repo.find_by_type(receipt_type))
        elif category:
            receipts = list(repo.find_by_category(category))
        else:
            receipts = list(repo.list_all())

    # Apply remaining filters in-memory if both type and category given
    if receipt_type and category:
        receipts = [r for r in receipts if str(r.receipt_type) == receipt_type
                    and str(r.category) == category]
    elif receipt_type and not quarter:
        receipts = [r for r in receipts if str(r.receipt_type) == receipt_type]
    elif category and not receipt_type:
        receipts = [r for r in receipts if str(r.category) == category]

    return {
        "receipts": [_receipt_to_response(r) for r in receipts],
        "total":    len(receipts),
    }


@app.get("/receipts/{receipt_id}", tags=["receipts"])
def get_receipt(receipt_id: str):
    """Return a single receipt with full extracted data."""
    with _repo() as repo:
        receipt = repo.get(receipt_id)
    if not receipt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Receipt not found.")
    return _receipt_to_response(receipt)


@app.get("/receipts/{receipt_id}/pdf", tags=["receipts"])
def get_receipt_pdf(receipt_id: str):
    """Stream the original uploaded PDF."""
    pdf_path = PDF_DIR / f"{receipt_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Original PDF not found in archive.")
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
    )


@app.patch("/receipts/{receipt_id}", tags=["receipts"])
def update_receipt(receipt_id: str, fields: dict):
    """
    Apply user corrections to a receipt's extracted fields.

    Accepted fields: ``receipt_type``, ``receipt_number``, ``receipt_date``,
    ``total_amount``, ``vat_percentage``, ``vat_amount``, ``category``,
    ``counterparty_name``.

    The content-hash ID never changes. Returns the updated receipt.
    """
    with _repo() as repo:
        updated = repo.update(receipt_id, fields)
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Receipt not found.")
        receipt = repo.get(receipt_id)

    return _receipt_to_response(receipt)


@app.delete("/receipts/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT,
            tags=["receipts"])
def delete_receipt(receipt_id: str):
    """
    Remove a receipt from the database.

    The original PDF is intentionally kept in ~/.finanzamt/pdfs/ as an audit
    trail. Delete it manually if you need to remove it entirely.
    """
    with _repo() as repo:
        deleted = repo.delete(receipt_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Receipt not found.")


# ---------------------------------------------------------------------------
# Tax routes
# ---------------------------------------------------------------------------

@app.get("/tax/ustva", tags=["tax"])
def get_ustva(
    quarter: int = Query(..., ge=1, le=4, description="Fiscal quarter (1–4)"),
    year:    int = Query(..., ge=2000, le=2100, description="Fiscal year"),
):
    """
    Generate a UStVA (VAT pre-return) for the given quarter.

    Returns input tax (Vorsteuer from purchases) and output tax
    (Umsatzsteuer from sales) split by VAT rate, plus the net liability.
    """
    starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    ends   = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    ms, ds = starts[quarter]
    me, de = ends[quarter]
    start  = date(year, ms, ds)
    end    = date(year, me, de)

    with _repo() as repo:
        receipts = list(repo.find_by_period(start, end))

    report = generate_ustva(receipts, start, end)
    return report.to_dict()


# ---------------------------------------------------------------------------
# Static frontend (SPA catch-all — must come last)
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
    # Mount /assets for hashed JS/CSS bundles (Vite default output)
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Catch-all: serve index.html for client-side routing."""
        # Serve actual files if they exist (favicons, manifest, etc.)
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_not_built(full_path: str):
        return {
            "error": "Frontend not built yet.",
            "hint":  "cd frontend && npm run build && cp -r dist/* src/finanzamt/ui/static/",
        }