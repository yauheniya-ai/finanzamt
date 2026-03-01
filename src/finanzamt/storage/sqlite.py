"""
finanzamt.storage.sqlite
~~~~~~~~~~~~~~~~~~~~~~~~
SQLite-backed receipt repository — 4-table schema.

Tables
------
counterparties  — vendors and clients with parsed address + tax numbers
receipts        — core record: hash id, FK to counterparty, type, totals
receipt_items   — line items, FK to receipt
receipt_content — raw OCR text, FK to receipt (kept separate, can be large)

Receipt ID
----------
The ``id`` is the SHA-256 hash of the normalised OCR text (computed by
``ReceiptData.__post_init__``).  Identical content → identical ID → duplicate.

Default path: ``~/.finanzamt/default/finanzamt.db``
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .base import ReceiptRepository
from .project import resolve_project
from ..models import (
    Address, Counterparty, ReceiptCategory, ReceiptData, ReceiptItem, ReceiptType,
)

DEFAULT_DB_PATH = resolve_project().db_path   # ~/.finanzamt/default/finanzamt.db
_SCHEMA_VERSION = 1


class SQLiteRepository:
    """Persistent SQLite storage implementing ``ReceiptRepository``."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path, check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "SQLiteRepository":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                self._create_tables()
                self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                self._conn.commit()
            # Always run migrations — safe on new and existing DBs
            self._migrate()

    def _migrate(self) -> None:
        """Idempotent column/table additions for schema evolution."""
        for tbl, col, typedef in [
            ("receipt_items",  "position",   "INTEGER"),
            ("receipt_items",  "vat_amount",  "TEXT"),
            ("counterparties", "verified",    "INTEGER DEFAULT 0"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typedef}")
                self._conn.commit()
            except Exception:
                pass  # column already exists — expected on all but first run
        # vat_splits table (safe CREATE IF NOT EXISTS)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS receipt_vat_splits (
                id         TEXT PRIMARY KEY,
                receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                position   INTEGER,
                vat_rate   TEXT,
                vat_amount TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_vat_splits_receipt
                ON receipt_vat_splits (receipt_id);
        """)
        self._conn.commit()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS counterparties (
                id           TEXT PRIMARY KEY,
                name         TEXT,
                street       TEXT,
                street_number TEXT,
                postcode     TEXT,
                city         TEXT,
                country      TEXT,
                tax_number   TEXT,
                vat_id       TEXT,
                verified     INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cp_name   ON counterparties (name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_cp_vat_id ON counterparties (vat_id);

            CREATE TABLE IF NOT EXISTS receipts (
                id               TEXT PRIMARY KEY,  -- SHA-256 content hash
                counterparty_id  TEXT REFERENCES counterparties(id) ON DELETE SET NULL,
                receipt_type     TEXT NOT NULL DEFAULT 'purchase',
                receipt_number   TEXT,
                receipt_date     TEXT,
                total_amount     TEXT,
                vat_percentage   TEXT,
                vat_amount       TEXT,
                category         TEXT,
                created_at       TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_receipts_date     ON receipts (receipt_date);
            CREATE INDEX IF NOT EXISTS idx_receipts_category ON receipts (category);
            CREATE INDEX IF NOT EXISTS idx_receipts_type     ON receipts (receipt_type);

            CREATE TABLE IF NOT EXISTS receipt_items (
                id           TEXT PRIMARY KEY,
                receipt_id   TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                position     INTEGER,
                description  TEXT,
                quantity     TEXT,
                unit_price   TEXT,
                total_price  TEXT,
                vat_rate     TEXT,
                vat_amount   TEXT,
                category     TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_items_receipt ON receipt_items (receipt_id);

            CREATE TABLE IF NOT EXISTS receipt_vat_splits (
                id           TEXT PRIMARY KEY,
                receipt_id   TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                position     INTEGER,
                vat_rate     TEXT,
                vat_amount   TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_vat_splits_receipt ON receipt_vat_splits (receipt_id);

            CREATE TABLE IF NOT EXISTS receipt_content (
                receipt_id   TEXT PRIMARY KEY REFERENCES receipts(id) ON DELETE CASCADE,
                raw_text     TEXT,
                content_hash TEXT NOT NULL
            );
        """)


    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _execmany(self, sql: str, rows: list) -> None:
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _dec(v) -> Decimal | None:
        return Decimal(str(v)) if v is not None else None

    # ------------------------------------------------------------------
    # Counterparty deduplication
    # ------------------------------------------------------------------

    def get_or_create_counterparty(self, cp: Counterparty) -> Counterparty:
        """
        Always insert a fresh counterparty row for this receipt.
        Each receipt owns its own counterparty record so address / VAT-ID
        corrections on one receipt never affect another.
        """
        self._exec(
            """INSERT INTO counterparties
               (id, name, street, street_number, postcode, city, country,
                tax_number, vat_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                cp.id, cp.name,
                cp.address.street, cp.address.street_number,
                cp.address.postcode, cp.address.city, cp.address.country,
                cp.tax_number, cp.vat_id, self._now(),
            ),
        )
        return cp

    def _row_to_counterparty(self, row: sqlite3.Row) -> Counterparty:
        return Counterparty(
            id=row["id"],
            name=row["name"],
            address=Address(
                street=row["street"],
                street_number=row["street_number"],
                postcode=row["postcode"],
                city=row["city"],
                country=row["country"],
            ),
            tax_number=row["tax_number"],
            vat_id=row["vat_id"],
        )

    # ------------------------------------------------------------------
    # save
    # ------------------------------------------------------------------

    def save(self, receipt: ReceiptData) -> bool:
        """
        Persist a receipt.

        Returns ``True`` on success, ``False`` if a duplicate already exists.
        Raises no exceptions on duplicate — callers check the return value
        or call ``exists()`` first.
        """
        if self.exists(receipt.id):
            return False

        # Resolve/create counterparty
        cp_id: str | None = None
        if receipt.counterparty:
            resolved = self.get_or_create_counterparty(receipt.counterparty)
            receipt.counterparty = resolved
            cp_id = resolved.id

        date_str: str | None = None
        if receipt.receipt_date is not None:
            d = receipt.receipt_date.date() if isinstance(receipt.receipt_date, datetime) else receipt.receipt_date
            date_str = d.isoformat()

        with self._lock:
            # receipts
            self._conn.execute(
                """INSERT INTO receipts
                   (id, counterparty_id, receipt_type, receipt_number,
                    receipt_date, total_amount, vat_percentage, vat_amount,
                    category, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    receipt.id, cp_id, str(receipt.receipt_type),
                    receipt.receipt_number, date_str,
                    str(receipt.total_amount)   if receipt.total_amount   is not None else None,
                    str(receipt.vat_percentage) if receipt.vat_percentage is not None else None,
                    str(receipt.vat_amount)     if receipt.vat_amount     is not None else None,
                    str(receipt.category),
                    self._now(),
                ),
            )

            # receipt_items
            import uuid as _uuid
            item_rows = [
                (
                    str(_uuid.uuid4()), receipt.id,
                    item.position,
                    item.description,
                    str(item.quantity)    if item.quantity    is not None else None,
                    str(item.unit_price)  if item.unit_price  is not None else None,
                    str(item.total_price) if item.total_price is not None else None,
                    str(item.vat_rate)    if item.vat_rate    is not None else None,
                    str(item.vat_amount)  if item.vat_amount  is not None else None,
                    str(item.category),
                )
                for item in receipt.items
            ]
            self._conn.executemany(
                """INSERT INTO receipt_items
                   (id, receipt_id, position, description, quantity, unit_price,
                    total_price, vat_rate, vat_amount, category)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                item_rows,
            )

            # vat_splits
            if hasattr(receipt, 'vat_splits') and receipt.vat_splits:
                import uuid as _uuid_vs
                for pos, split in enumerate(receipt.vat_splits, start=1):
                    self._conn.execute(
                        """INSERT INTO receipt_vat_splits (id, receipt_id, position, vat_rate, vat_amount)
                           VALUES (?, ?, ?, ?, ?)""",
                        (str(_uuid_vs.uuid4()), receipt.id, split.get("position", pos),
                         str(split["vat_rate"]) if split.get("vat_rate") is not None else None,
                         str(split["vat_amount"]) if split.get("vat_amount") is not None else None),
                    )

            # receipt_content
            self._conn.execute(
                """INSERT INTO receipt_content (receipt_id, raw_text, content_hash)
                   VALUES (?,?,?)""",
                (receipt.id, receipt.raw_text, receipt.id),
            )

            self._conn.commit()

        return True

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def exists(self, receipt_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        return row is not None

    def get(self, receipt_id: str) -> ReceiptData | None:
        row = self._conn.execute(
            """SELECT r.*, rc.raw_text,
                      c.id as cp_id, c.name as cp_name,
                      c.street, c.street_number, c.postcode, c.city, c.country,
                      c.tax_number, c.vat_id, COALESCE(c.verified, 0) as verified
               FROM receipts r
               LEFT JOIN receipt_content rc ON rc.receipt_id = r.id
               LEFT JOIN counterparties c   ON c.id = r.counterparty_id
               WHERE r.id = ?""",
            (receipt_id,),
        ).fetchone()
        return self._row_to_receipt(row) if row else None

    def delete(self, receipt_id: str) -> bool:
        cur = self._exec("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        return cur.rowcount > 0


    def update(self, receipt_id: str, fields: dict) -> bool:
        """
        Partially update a receipt's mutable fields (user corrections).

        Receipt fields: ``receipt_type``, ``receipt_number``, ``receipt_date``,
        ``total_amount``, ``vat_percentage``, ``vat_amount``, ``category``.

        Counterparty fields (applied to the counterparty row owned by this
        receipt): ``counterparty_name``, ``vat_id``, ``tax_number``,
        and address sub-fields via an ``address`` dict with keys
        ``street``, ``street_number``, ``postcode``, ``city``, ``country``.

        Returns True if the receipt row was found.
        """
        RECEIPT_MUTABLE = {
            "receipt_type", "receipt_number", "receipt_date",
            "total_amount", "vat_percentage", "vat_amount", "category",
        }
        CP_SCALAR = {
            "counterparty_name": "name",
            "vat_id":            "vat_id",
            "tax_number":        "tax_number",
        }
        ADDR_FIELDS = {"street", "street_number", "postcode", "city", "country"}

        receipt_updates = {k: v for k, v in fields.items() if k in RECEIPT_MUTABLE}

        # Normalise date/decimal
        if "receipt_date" in receipt_updates and receipt_updates["receipt_date"]:
            d = receipt_updates["receipt_date"]
            receipt_updates["receipt_date"] = d.isoformat() if hasattr(d, "isoformat") else str(d)
        for field in ("total_amount", "vat_percentage", "vat_amount"):
            if field in receipt_updates and receipt_updates[field] is not None:
                receipt_updates[field] = str(receipt_updates[field])

        # Apply receipt-level updates
        if receipt_updates:
            set_clause = ", ".join(f"{col} = ?" for col in receipt_updates)
            params = tuple(receipt_updates.values()) + (receipt_id,)
            self._exec(f"UPDATE receipts SET {set_clause} WHERE id = ?", params)

        # Counterparty updates
        cp_row = self._conn.execute(
            "SELECT counterparty_id FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        cp_id = cp_row["counterparty_id"] if cp_row else None

        # Collect all counterparty field changes
        cp_updates: dict = {}
        for field_in, col in CP_SCALAR.items():
            if field_in in fields and fields[field_in] is not None:
                cp_updates[col] = fields[field_in]
        addr = fields.get("address", {})
        if isinstance(addr, dict):
            for k in ADDR_FIELDS:
                if k in addr:
                    cp_updates[k] = addr[k]

        if cp_updates:
            if cp_id:
                # Update existing counterparty row
                set_clause = ", ".join(f"{col} = ?" for col in cp_updates)
                params = tuple(cp_updates.values()) + (cp_id,)
                self._exec(
                    f"UPDATE counterparties SET {set_clause} WHERE id = ?", params
                )
            else:
                # No counterparty row yet — create one and link it to the receipt
                import uuid
                new_cp_id = str(uuid.uuid4())
                self._exec(
                    """INSERT INTO counterparties
                       (id, name, street, street_number, postcode, city, country,
                        tax_number, vat_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        new_cp_id,
                        cp_updates.get("name"),
                        cp_updates.get("street"),
                        cp_updates.get("street_number"),
                        cp_updates.get("postcode"),
                        cp_updates.get("city"),
                        cp_updates.get("country"),
                        cp_updates.get("tax_number"),
                        cp_updates.get("vat_id"),
                        self._now(),
                    ),
                )
                self._exec(
                    "UPDATE receipts SET counterparty_id = ? WHERE id = ?",
                    (new_cp_id, receipt_id),
                )

        # VAT splits — full replace when provided
        if "vat_splits" in fields and isinstance(fields["vat_splits"], list):
            import uuid as _uuid_vs2
            self._exec("DELETE FROM receipt_vat_splits WHERE receipt_id = ?", (receipt_id,))
            for pos, split in enumerate(fields["vat_splits"], start=1):
                self._exec(
                    """INSERT INTO receipt_vat_splits (id, receipt_id, position, vat_rate, vat_amount)
                       VALUES (?, ?, ?, ?, ?)""",
                    (str(_uuid_vs2.uuid4()), receipt_id,
                     split.get("position", pos),
                     str(split["vat_rate"])    if split.get("vat_rate")    is not None else None,
                     str(split["vat_amount"])  if split.get("vat_amount")  is not None else None),
                )

        # Counterparty verified flag
        if "counterparty_verified" in fields and cp_id:
            self._exec(
                "UPDATE counterparties SET verified = ? WHERE id = ?",
                (1 if fields["counterparty_verified"] else 0, cp_id),
            )

        # Items — full replace when provided
        if "items" in fields and isinstance(fields["items"], list):
            import uuid as _uuid3
            self._exec("DELETE FROM receipt_items WHERE receipt_id = ?", (receipt_id,))
            for pos, item in enumerate(fields["items"], start=1):
                self._exec(
                    """INSERT INTO receipt_items
                       (id, receipt_id, position, description, quantity, unit_price,
                        total_price, vat_rate, vat_amount, category)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid3.uuid4()),
                        receipt_id,
                        item.get("position", pos),
                        item.get("description"),
                        str(item["quantity"])    if item.get("quantity")    is not None else None,
                        str(item["unit_price"])  if item.get("unit_price")  is not None else None,
                        str(item["total_price"]) if item.get("total_price") is not None else None,
                        str(item["vat_rate"])    if item.get("vat_rate")    is not None else None,
                        str(item["vat_amount"])  if item.get("vat_amount")  is not None else None,
                        item.get("category", "other"),
                    ),
                )

        return self.exists(receipt_id)

    def list_verified_counterparties(self) -> list[dict]:
        """Return all counterparties where verified=1."""
        rows = self._conn.execute(
            """SELECT id, name, street, street_number, postcode, city, country,
                      tax_number, vat_id, verified
               FROM counterparties WHERE verified = 1 ORDER BY name ASC"""
        ).fetchall()
        return [
            {
                "id":           r["id"],
                "name":         r["name"],
                "tax_number":   r["tax_number"],
                "vat_id":       r["vat_id"],
                "verified":     bool(r["verified"]),
                "address": {
                    "street":        r["street"],
                    "street_number": r["street_number"],
                    "postcode":      r["postcode"],
                    "city":          r["city"],
                    "country":       r["country"],
                },
            }
            for r in rows
        ]

    def set_counterparty_verified(self, cp_id: str, verified: bool) -> None:
        self._exec(
            "UPDATE counterparties SET verified = ? WHERE id = ?",
            (1 if verified else 0, cp_id),
        )

    def list_all(self) -> Iterable[ReceiptData]:
        return self._query_receipts(
            "ORDER BY receipt_date DESC NULLS LAST"
        )

    def find_by_period(self, start: date, end: date) -> Iterable[ReceiptData]:
        s = (start.date() if isinstance(start, datetime) else start).isoformat()
        e = (end.date()   if isinstance(end,   datetime) else end  ).isoformat()
        return self._query_receipts(
            "WHERE r.receipt_date BETWEEN ? AND ? ORDER BY r.receipt_date DESC",
            (s, e),
        )

    def find_by_category(self, category: str) -> Iterable[ReceiptData]:
        return self._query_receipts(
            "WHERE r.category = ? ORDER BY r.receipt_date DESC NULLS LAST",
            (category,),
        )

    def find_by_type(self, receipt_type: str) -> Iterable[ReceiptData]:
        return self._query_receipts(
            "WHERE r.receipt_type = ? ORDER BY r.receipt_date DESC NULLS LAST",
            (receipt_type,),
        )

    # ------------------------------------------------------------------
    # Internal query helper
    # ------------------------------------------------------------------

    def _query_receipts(self, where_order: str, params: tuple = ()) -> list[ReceiptData]:
        sql = f"""
            SELECT r.*, rc.raw_text,
                   c.id as cp_id, c.name as cp_name,
                   c.street, c.street_number, c.postcode, c.city, c.country,
                   c.tax_number, c.vat_id, COALESCE(c.verified, 0) as verified
            FROM receipts r
            LEFT JOIN receipt_content rc ON rc.receipt_id = r.id
            LEFT JOIN counterparties  c  ON c.id = r.counterparty_id
            {where_order}
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_receipt(row) for row in rows]

    def _row_to_receipt(self, row: sqlite3.Row) -> ReceiptData:
        # Counterparty
        cp: Counterparty | None = None
        if row["cp_id"]:
            _cp_verified = row["verified"] if "verified" in row.keys() else 0
            cp = Counterparty(
                id=row["cp_id"],
                name=row["cp_name"],
                address=Address(
                    street=row["street"],
                    street_number=row["street_number"],
                    postcode=row["postcode"],
                    city=row["city"],
                    country=row["country"],
                ),
                tax_number=row["tax_number"],
                vat_id=row["vat_id"],
                verified=bool(_cp_verified),
            )

        # receipt_date
        receipt_date: datetime | None = None
        if row["receipt_date"]:
            d = date.fromisoformat(row["receipt_date"])
            receipt_date = datetime(d.year, d.month, d.day)

        # items (separate query to keep row simple)
        item_rows = self._conn.execute(
            "SELECT * FROM receipt_items WHERE receipt_id = ? ORDER BY position ASC NULLS LAST",
            (row["id"],)
        ).fetchall()
        items = [
            ReceiptItem(
                description=ir["description"] or "",
                position=   ir["position"] if "position" in ir.keys() else None,
                quantity=   self._dec(ir["quantity"]),
                unit_price= self._dec(ir["unit_price"]),
                total_price=self._dec(ir["total_price"]),
                vat_rate=   self._dec(ir["vat_rate"]),
                vat_amount= self._dec(ir["vat_amount"]) if "vat_amount" in ir.keys() else None,
                category=   ReceiptCategory(ir["category"] or "other"),
            )
            for ir in item_rows
        ]

        # vat_splits
        split_rows = self._conn.execute(
            "SELECT * FROM receipt_vat_splits WHERE receipt_id = ? ORDER BY position ASC",
            (row["id"],)
        ).fetchall()
        vat_splits = [
            {
                "position":   sr["position"],
                "vat_rate":   float(self._dec(sr["vat_rate"]))   if sr["vat_rate"]   else None,
                "vat_amount": float(self._dec(sr["vat_amount"])) if sr["vat_amount"] else None,
            }
            for sr in split_rows
        ]

        receipt = ReceiptData.__new__(ReceiptData)
        receipt.raw_text       = row["raw_text"] or ""
        receipt.vat_splits     = vat_splits
        receipt.id             = row["id"]
        receipt.receipt_type   = ReceiptType(row["receipt_type"] or "purchase")
        receipt.counterparty   = cp
        receipt.receipt_number = row["receipt_number"]
        receipt.receipt_date   = receipt_date
        receipt.total_amount   = self._dec(row["total_amount"])
        receipt.vat_percentage = self._dec(row["vat_percentage"])
        receipt.vat_amount     = self._dec(row["vat_amount"])
        receipt.category       = ReceiptCategory(row["category"] or "other")
        receipt.items          = items
        return receipt