"""Versioned pickup rescheduling, atomic capacity transfer, and order event history."""

from datetime import datetime, timezone
import json
from .orders import Conflict
from .fulfillment import epoch


class PickupReservations:
    def __init__(self, kitchen):
        self.kitchen = kitchen
        with kitchen.connection() as db:
            db.executescript(
                """
              CREATE TABLE IF NOT EXISTS pickup_changes(
                request_key TEXT PRIMARY KEY, order_id TEXT NOT NULL, pickup INTEGER NOT NULL,
                expected_version INTEGER NOT NULL, result TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS pickup_events(
                sequence INTEGER PRIMARY KEY, order_id TEXT NOT NULL, previous INTEGER NOT NULL,
                pickup INTEGER NOT NULL, version INTEGER NOT NULL);
            """
            )

    def move(self, order_id, pickup_at, version, key, *, now=None):
        pickup = epoch(pickup_at)
        if (
            pickup % 900
            or type(version) is not int
            or version < 1
            or not isinstance(key, str)
            or not 1 <= len(key) <= 128
        ):
            raise ValueError("aligned pickup, version, and request key required")
        with self.kitchen.transaction() as db:
            retry = db.execute(
                "SELECT * FROM pickup_changes WHERE request_key=?", (key,)
            ).fetchone()
            if retry:
                if (retry["order_id"], retry["pickup"], retry["expected_version"]) != (
                    order_id,
                    pickup,
                    version,
                ):
                    raise Conflict("request key used for another pickup change")
                return json.loads(retry["result"])
            current = now or datetime.now(timezone.utc)
            if (
                current.tzinfo is None
                or not 900 <= pickup - current.timestamp() <= 86400
            ):
                raise ValueError("pickup must be 15 minutes to 24 hours ahead")
            row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if row is None:
                raise KeyError(order_id)
            if row["status"] != "accepted" or row["version"] != version:
                raise Conflict("only the current accepted order can change pickup")
            if pickup != row["pickup"]:
                db.execute("INSERT OR IGNORE INTO slots VALUES(?,0)", (pickup,))
                changed = db.execute(
                    "UPDATE slots SET reserved=reserved+1 WHERE start=? AND reserved<?",
                    (pickup, self.kitchen.capacity),
                )
                if changed.rowcount != 1:
                    raise Conflict("new pickup slot is full")
                released = db.execute(
                    "UPDATE slots SET reserved=reserved-1 WHERE start=? AND reserved>0",
                    (row["pickup"],),
                )
                if released.rowcount != 1:
                    raise Conflict("original pickup reservation is inconsistent")
                db.execute(
                    "UPDATE orders SET pickup=?,version=version+1 WHERE id=?",
                    (pickup, order_id),
                )
                db.execute(
                    "INSERT INTO pickup_events(order_id,previous,pickup,version) VALUES(?,?,?,?)",
                    (order_id, row["pickup"], pickup, version + 1),
                )
            result = self.kitchen._order(
                db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            )
            db.execute(
                "INSERT INTO pickup_changes VALUES(?,?,?,?,?)",
                (key, order_id, pickup, version, json.dumps(result)),
            )
            return result

    def history(self, order_id):
        with self.kitchen.connection() as db:
            if not db.execute(
                "SELECT 1 FROM orders WHERE id=?", (order_id,)
            ).fetchone():
                raise KeyError(order_id)
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM pickup_events WHERE order_id=? ORDER BY sequence",
                    (order_id,),
                )
            ]

    def audit_capacity(self):
        """A read-only check; never silently repairs stock or reservations."""
        with self.kitchen.connection() as db:
            expected = {
                row["pickup"]: row["count"]
                for row in db.execute(
                    "SELECT pickup,count(*) AS count FROM orders WHERE status!='cancelled' GROUP BY pickup"
                )
            }
            actual = {
                row["start"]: row["reserved"]
                for row in db.execute("SELECT * FROM slots")
            }
        return [
            {
                "pickup": slot,
                "reserved": actual.get(slot, 0),
                "expected": expected.get(slot, 0),
            }
            for slot in sorted(set(expected) | set(actual))
            if expected.get(slot, 0) != actual.get(slot, 0)
        ]
