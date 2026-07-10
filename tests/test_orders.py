from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import tempfile, unittest
from restaurant import Kitchen, Conflict


class Orders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.kitchen = Kitchen(
            Path(self.tmp.name) / "kitchen.sqlite3",
            slot_capacity=1,
            tax_basis_points=825,
        )
        self.kitchen.add_item("bowl", "Bowl", "Mains", 1250, 2)
        self.now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        self.pickup = "2026-07-01T13:00:00+00:00"

    def order(self, key, quantity=1):
        return self.kitchen.create_order(
            key, [{"id": "bowl", "quantity": quantity}], self.pickup, now=self.now
        )

    def test_idempotent_retry_does_not_reserve_twice(self):
        first = self.order("same")
        self.assertEqual(first, self.order("same"))
        self.assertEqual(self.kitchen.menu()[0]["stock"], 1)
        with self.assertRaises(Conflict):
            self.order("same", 2)

    def test_full_slot_rolls_back_inventory(self):
        self.order("a")
        with self.assertRaises(Conflict):
            self.order("b")
        self.assertEqual(self.kitchen.menu()[0]["stock"], 1)

    def test_cancel_releases_inventory_and_capacity(self):
        order = self.order("a")
        self.kitchen.transition(order["id"], "cancelled", 1)
        self.assertEqual(self.kitchen.menu()[0]["stock"], 2)
        self.order("b")

    def test_concurrent_orders_cannot_overbook(self):
        def place(key):
            try:
                self.order(key)
                return True
            except Conflict:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(place, ["a", "b"])), 1)

    def test_integer_totals_and_stale_versions(self):
        order = self.order("a")
        self.assertEqual(order["tax"], 103)
        self.assertEqual(order["total"], 1353)
        self.kitchen.transition(order["id"], "preparing", 1)
        with self.assertRaises(Conflict):
            self.kitchen.transition(order["id"], "ready", 1)
