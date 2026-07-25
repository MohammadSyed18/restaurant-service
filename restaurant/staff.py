"""Local staff commands; no unauthenticated stock-write HTTP route is exposed."""

import argparse
import json
from .orders import Kitchen
from .inventory import InventoryLedger
from .fulfillment import FulfillmentBoard
from .reservations import PickupReservations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="data/kitchen.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    board = commands.add_parser("board")
    board.add_argument("start")
    board.add_argument("end")
    stock = commands.add_parser("adjust-stock")
    stock.add_argument("key")
    stock.add_argument("item")
    stock.add_argument("delta", type=int)
    stock.add_argument("expected_stock", type=int)
    stock.add_argument("note")
    move = commands.add_parser("move-pickup")
    for argument in ("order_id", "pickup", "key"):
        move.add_argument(argument)
    move.add_argument("version", type=int)
    commands.add_parser("audit-capacity")
    args = parser.parse_args()
    try:
        kitchen = Kitchen(args.database)
        if args.command == "move-pickup":
            result = PickupReservations(kitchen).move(
                args.order_id, args.pickup, args.version, args.key
            )
            print(json.dumps(result, indent=2))
            return
        if args.command == "audit-capacity":
            print(json.dumps(PickupReservations(kitchen).audit_capacity(), indent=2))
            return
        result = (
            FulfillmentBoard(kitchen).queue(args.start, args.end)
            if args.command == "board"
            else InventoryLedger(kitchen).adjust(
                args.key, args.item, args.delta, args.expected_stock, args.note
            )
        )
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
