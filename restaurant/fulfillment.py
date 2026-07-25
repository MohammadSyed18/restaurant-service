"""Read-only pickup capacity, preparation demand, and staff queue summaries."""

from collections import Counter
from datetime import datetime, timezone
import json


def epoch(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("time must include timezone")
    return int(parsed.timestamp())


class FulfillmentBoard:
    def __init__(self, kitchen):
        self.kitchen = kitchen

    def queue(self, start, end):
        start, end = epoch(start), epoch(end)
        if end <= start or end - start > 7 * 86400:
            raise ValueError("queue window must be positive and at most seven days")
        with self.kitchen.connection() as db:
            orders = [
                self.kitchen._order(row)
                for row in db.execute(
                    "SELECT * FROM orders WHERE pickup>=? AND pickup<? ORDER BY pickup,id",
                    (start, end),
                )
            ]
        active = [
            order
            for order in orders
            if order["status"] in {"accepted", "preparing", "ready"}
        ]
        demand = Counter()
        for order in active:
            if order["status"] == "ready":
                continue
            for line in order["lines"]:
                demand[line["id"]] += line["quantity"]
        return {
            "start": start,
            "end": end,
            "orders": active,
            "status_counts": dict(Counter(order["status"] for order in orders)),
            "preparation_quantities": dict(sorted(demand.items())),
            "collected_total_cents": sum(
                order["total"] for order in orders if order["status"] == "collected"
            ),
        }

    def capacity(self, start, slots=8):
        beginning = epoch(start)
        if beginning % 900 or type(slots) is not int or not 1 <= slots <= 96:
            raise ValueError("aligned start and 1..96 slots required")
        with self.kitchen.connection() as db:
            reservations = {
                row["start"]: row["reserved"]
                for row in db.execute(
                    "SELECT * FROM slots WHERE start>=? AND start<?",
                    (beginning, beginning + slots * 900),
                )
            }
        return [
            {
                "start": datetime.fromtimestamp(at, timezone.utc).isoformat(),
                "reserved": reservations.get(at, 0),
                "available": max(0, self.kitchen.capacity - reservations.get(at, 0)),
            }
            for at in range(beginning, beginning + slots * 900, 900)
        ]
