"""Audited, idempotent stock adjustments independent of order reservations."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from .orders import Conflict


class InventoryLedger:
    def __init__(self, kitchen):
        self.kitchen = kitchen
        with kitchen.connection() as db:
            db.executescript(
                """CREATE TABLE IF NOT EXISTS inventory_adjustments(
                request_key TEXT PRIMARY KEY, digest TEXT NOT NULL, item_id TEXT NOT NULL,
                delta INTEGER NOT NULL, stock_before INTEGER NOT NULL, stock_after INTEGER NOT NULL,
                note TEXT NOT NULL, occurred_at TEXT NOT NULL);"""
            )

    def adjust(self, key, item_id, delta, expected_stock, note):
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 128
            or not isinstance(item_id, str)
        ):
            raise ValueError("adjustment key and item required")
        if (
            type(delta) is not int
            or delta == 0
            or abs(delta) > 100000
            or type(expected_stock) is not int
            or expected_stock < 0
        ):
            raise ValueError("invalid stock adjustment")
        if not isinstance(note, str) or not note.strip() or len(note) > 1000:
            raise ValueError("adjustment note required")
        digest = sha256(
            json.dumps([item_id, delta, expected_stock, note.strip()]).encode()
        ).hexdigest()
        with self.kitchen.transaction() as db:
            previous = db.execute(
                "SELECT * FROM inventory_adjustments WHERE request_key=?", (key,)
            ).fetchone()
            if previous:
                if previous["digest"] != digest:
                    raise Conflict("adjustment key reused with different content")
                return self._public(previous)
            item = db.execute(
                "SELECT stock FROM menu WHERE id=?", (item_id,)
            ).fetchone()
            if item is None:
                raise KeyError(item_id)
            if item["stock"] != expected_stock:
                raise Conflict("stock changed; reload before adjusting")
            after = item["stock"] + delta
            if after < 0:
                raise Conflict("adjustment would make stock negative")
            db.execute("UPDATE menu SET stock=? WHERE id=?", (after, item_id))
            db.execute(
                "INSERT INTO inventory_adjustments VALUES(?,?,?,?,?,?,?,?)",
                (
                    key,
                    digest,
                    item_id,
                    delta,
                    item["stock"],
                    after,
                    note.strip(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return self._public(
                db.execute(
                    "SELECT * FROM inventory_adjustments WHERE request_key=?", (key,)
                ).fetchone()
            )

    def _public(self, row):
        value = dict(row)
        value.pop("digest")
        return value

    def history(self, item_id, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        with self.kitchen.connection() as db:
            return [
                self._public(row)
                for row in db.execute(
                    "SELECT * FROM inventory_adjustments WHERE item_id=? ORDER BY occurred_at DESC,request_key LIMIT ?",
                    (item_id, limit),
                )
            ]
