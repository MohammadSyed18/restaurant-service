import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
from restaurant.orders import Kitchen, Conflict
from restaurant.inventory import InventoryLedger
from restaurant.fulfillment import FulfillmentBoard


class FulfillmentTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.kitchen = Kitchen(Path(directory.name) / "kitchen.db", slot_capacity=2)
        self.kitchen.add_item("meal", "Meal", "Main", 1000, 10)
        self.now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)

    def test_adjustments_retry_without_double_restock(self):
        inventory = InventoryLedger(self.kitchen)
        first = inventory.adjust("delivery-1", "meal", 5, 10, "Supplier delivery")
        self.assertEqual(
            first, inventory.adjust("delivery-1", "meal", 5, 10, "Supplier delivery")
        )
        self.assertEqual(self.kitchen.menu()[0]["stock"], 15)
        with self.assertRaises(Conflict):
            inventory.adjust("delivery-1", "meal", 4, 10, "Supplier delivery")
        with self.assertRaises(Conflict):
            inventory.adjust("stale", "meal", 1, 10, "Count")
        self.assertEqual(len(inventory.history("meal")), 1)

    def test_board_capacity_and_preparation_demand(self):
        order = self.kitchen.create_order(
            "one", [{"id": "meal", "quantity": 2}], "2026-07-01T12:30:00Z", now=self.now
        )
        board = FulfillmentBoard(self.kitchen)
        self.assertEqual(board.capacity("2026-07-01T12:30:00Z", 1)[0]["available"], 1)
        report = board.queue("2026-07-01T12:00:00Z", "2026-07-02T00:00:00Z")
        self.assertEqual(report["preparation_quantities"], {"meal": 2})
        self.kitchen.transition(order["id"], "cancelled", 1)
        self.assertEqual(board.capacity("2026-07-01T12:30:00Z", 1)[0]["available"], 2)
        self.assertEqual(
            board.queue("2026-07-01T12:00:00Z", "2026-07-02T00:00:00Z")["orders"], []
        )
