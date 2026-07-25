import tempfile, unittest
from pathlib import Path
from datetime import datetime, timezone
from restaurant.orders import Kitchen, Conflict
from restaurant.reservations import PickupReservations


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.kitchen = Kitchen(Path(self.temp.name) / "k.db", slot_capacity=1)
        self.kitchen.add_item("a", "Soup", "Food", 500, 10)
        self.now = datetime(2026, 7, 1, 10, tzinfo=timezone.utc)
        self.first = self.kitchen.create_order(
            "a", [{"id": "a", "quantity": 1}], "2026-07-01T10:30:00Z", now=self.now
        )
        self.moves = PickupReservations(self.kitchen)

    def test_move_retry_and_audit(self):
        result = self.moves.move(
            self.first["id"], "2026-07-01T11:00:00Z", 1, "move", now=self.now
        )
        self.assertEqual(result["version"], 2)
        self.assertEqual(
            self.moves.move(
                self.first["id"], "2026-07-01T11:00:00Z", 1, "move", now=self.now
            ),
            result,
        )
        self.assertEqual(len(self.moves.history(self.first["id"])), 1)
        self.assertEqual(self.moves.audit_capacity(), [])
        self.assertEqual(self.kitchen.menu()[0]["stock"], 9)

    def test_full_slot_rolls_back_original_reservation(self):
        self.kitchen.create_order(
            "b", [{"id": "a", "quantity": 1}], "2026-07-01T11:00:00Z", now=self.now
        )
        with self.assertRaises(Conflict):
            self.moves.move(
                self.first["id"], "2026-07-01T11:00:00Z", 1, "move", now=self.now
            )
        self.assertEqual(self.moves.audit_capacity(), [])
        self.assertEqual(self.moves.history(self.first["id"]), [])

    def test_invalid_versions_and_started_orders(self):
        with self.assertRaises(Conflict):
            self.moves.move(
                self.first["id"], "2026-07-01T11:00:00Z", 9, "move", now=self.now
            )
        self.kitchen.transition(self.first["id"], "preparing", 1)
        with self.assertRaises(Conflict):
            self.moves.move(
                self.first["id"], "2026-07-01T11:00:00Z", 2, "move", now=self.now
            )
