"""Transactional pickup orders with inventory and capacity reservations."""

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json, sqlite3
from pathlib import Path
from uuid import uuid4


class Conflict(ValueError):
    pass


TRANSITIONS = {
    "accepted": {"preparing", "cancelled"},
    "preparing": {"ready"},
    "ready": {"collected"},
    "collected": set(),
    "cancelled": set(),
}


class Kitchen:
    def __init__(self, path, *, slot_capacity=8, tax_basis_points=0):
        if (
            type(slot_capacity) is not int
            or slot_capacity < 1
            or type(tax_basis_points) is not int
            or not 0 <= tax_basis_points <= 10000
        ):
            raise ValueError("invalid kitchen configuration")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.capacity = slot_capacity
        self.tax = tax_basis_points
        with self.connection() as db:
            db.executescript(
                """PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS menu(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,price INTEGER NOT NULL CHECK(price>=0),stock INTEGER NOT NULL CHECK(stock>=0),allergens TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS slots(start INTEGER PRIMARY KEY,reserved INTEGER NOT NULL CHECK(reserved>=0));
                CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE NOT NULL,digest TEXT NOT NULL,pickup INTEGER NOT NULL,status TEXT NOT NULL,version INTEGER NOT NULL,subtotal INTEGER NOT NULL,tax INTEGER NOT NULL,total INTEGER NOT NULL,lines TEXT NOT NULL);
            """
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def add_item(self, item_id, name, category, price_cents, stock, allergens=()):
        if any(
            not isinstance(x, str) or not x.strip() for x in (item_id, name, category)
        ):
            raise ValueError("menu text required")
        if (
            type(price_cents) is not int
            or price_cents < 0
            or type(stock) is not int
            or stock < 0
        ):
            raise ValueError("invalid price or stock")
        if not all(isinstance(x, str) and x.strip() for x in allergens):
            raise ValueError("invalid allergens")
        with self.transaction() as db:
            db.execute(
                "INSERT INTO menu VALUES(?,?,?,?,?,?)",
                (
                    item_id,
                    name,
                    category,
                    price_cents,
                    stock,
                    json.dumps(sorted(set(allergens))),
                ),
            )

    def menu(self):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM menu ORDER BY category,name").fetchall()
        return [
            {**dict(row), "allergens": json.loads(row["allergens"])} for row in rows
        ]

    def create_order(self, key, items, pickup_at, *, now=None):
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 128
            or not isinstance(items, list)
            or not items
            or len(items) > 50
        ):
            raise ValueError("invalid order")
        quantities = {}
        for item in items:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or type(item.get("quantity")) is not int
                or not 1 <= item["quantity"] <= 20
            ):
                raise ValueError("invalid order line")
            quantities[item["id"]] = quantities.get(item["id"], 0) + item["quantity"]
        if any(q > 20 for q in quantities.values()):
            raise ValueError("maximum quantity exceeded")
        pickup = datetime.fromisoformat(pickup_at)
        if pickup.tzinfo is None:
            raise ValueError("pickup must include timezone")
        pickup_epoch = int(pickup.timestamp())
        if pickup_epoch % 900:
            raise ValueError("pickup must align to a 15-minute slot")
        canonical = json.dumps(
            {"items": quantities, "pickup": pickup_epoch}, sort_keys=True
        )
        digest = sha256(canonical.encode()).hexdigest()
        with self.transaction() as db:
            existing = db.execute(
                "SELECT * FROM orders WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise Conflict("idempotency key already used for another order")
                return self._order(existing)
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                raise ValueError("now must include timezone")
            if not 900 <= pickup_epoch - current.timestamp() <= 86400:
                raise ValueError("pickup must be 15 minutes to 24 hours ahead")
            lines = []
            subtotal = 0
            for item_id, quantity in sorted(quantities.items()):
                row = db.execute("SELECT * FROM menu WHERE id=?", (item_id,)).fetchone()
                if row is None or row["stock"] < quantity:
                    raise Conflict("item unavailable: " + item_id)
                subtotal += row["price"] * quantity
                lines.append(
                    {
                        "id": item_id,
                        "name": row["name"],
                        "quantity": quantity,
                        "price_cents": row["price"],
                    }
                )
                db.execute(
                    "UPDATE menu SET stock=stock-? WHERE id=?", (quantity, item_id)
                )
            db.execute("INSERT OR IGNORE INTO slots VALUES(?,0)", (pickup_epoch,))
            updated = db.execute(
                "UPDATE slots SET reserved=reserved+1 WHERE start=? AND reserved<?",
                (pickup_epoch, self.capacity),
            )
            if updated.rowcount != 1:
                raise Conflict("pickup slot is full")
            tax = (subtotal * self.tax + 5000) // 10000
            order_id = str(uuid4())
            db.execute(
                "INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    order_id,
                    key,
                    digest,
                    pickup_epoch,
                    "accepted",
                    1,
                    subtotal,
                    tax,
                    subtotal + tax,
                    json.dumps(lines),
                ),
            )
            return self._order(
                db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            )

    def _order(self, row):
        value = dict(row)
        value["lines"] = json.loads(value["lines"])
        value.pop("digest")
        value.pop("idempotency_key")
        return value

    def transition(self, order_id, status, version):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if row is None:
                raise KeyError(order_id)
            if row["version"] != version:
                raise Conflict("order version changed")
            if status not in TRANSITIONS[row["status"]]:
                raise Conflict("invalid status transition")
            if status == "cancelled":
                for line in json.loads(row["lines"]):
                    db.execute(
                        "UPDATE menu SET stock=stock+? WHERE id=?",
                        (line["quantity"], line["id"]),
                    )
                db.execute(
                    "UPDATE slots SET reserved=reserved-1 WHERE start=?",
                    (row["pickup"],),
                )
            db.execute(
                "UPDATE orders SET status=?,version=version+1 WHERE id=?",
                (status, order_id),
            )
            return self._order(
                db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            )
