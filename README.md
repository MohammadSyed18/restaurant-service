# Restaurant Service

Responsive menu browsing and a transactional pickup-order workflow, with an anonymized neighborhood-kitchen menu.

The ordering engine supports inventory reservations, 15-minute pickup capacity, idempotent order retries, integer-cent pricing, configurable tax, optimistic status updates, and reservation release on cancellation. The browser preserves the same request key when retrying an uncertain submission and renders menu content through text nodes.

```sh
python -m unittest discover -s tests -v
python -m restaurant.server
```

Open `http://127.0.0.1:8081`. The local server seeds a small menu on first run. `KITCHEN_DATABASE` changes the SQLite path and `PORT` changes the listening port. Pickup times must be aligned to a quarter-hour and fall 15 minutes to 24 hours ahead. Staff status transitions are available through the `Kitchen` Python interface.

## Staff inventory and fulfillment tools

[inventory.py](restaurant/inventory.py) adds an audited stock-adjustment ledger with idempotency keys, expected-stock checks, nonnegative inventory, and adjustment history. [fulfillment.py](restaurant/fulfillment.py) provides pickup capacity, active order queues, preparation quantities, and collected-order totals.

```sh
python -m restaurant.staff --database data/kitchen.sqlite3 board 2026-10-22T00:00:00Z 2026-10-23T00:00:00Z
python -m restaurant.staff --database data/kitchen.sqlite3 adjust-stock delivery-1 item-id 5 10 "Supplier delivery"
```

The second example requires an existing item with expected stock 10. Adjustments are local staff commands; no unauthenticated stock-write route was added to the customer service. Tests cover retried deliveries, stale counts, capacity release, cancellation, and preparation demand.
