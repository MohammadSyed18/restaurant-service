# Restaurant Service

Responsive menu browsing and a transactional pickup-order workflow, with an anonymized neighborhood-kitchen menu.

The ordering engine supports inventory reservations, 15-minute pickup capacity, idempotent order retries, integer-cent pricing, configurable tax, optimistic status updates, and reservation release on cancellation. The browser preserves the same request key when retrying an uncertain submission and renders menu content through text nodes.

```sh
python -m unittest discover -s tests -v
python -m restaurant.server
```

Open `http://127.0.0.1:8081`. The local server seeds a small menu on first run. `KITCHEN_DATABASE` changes the SQLite path and `PORT` changes the listening port. Pickup times must be aligned to a quarter-hour and fall 15 minutes to 24 hours ahead. Staff status transitions are available through the `Kitchen` Python interface.
