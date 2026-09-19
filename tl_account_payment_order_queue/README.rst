================================
Payment Order Upload Queue Job
================================

Odoo 19.0 — Tecniloop

Depends
=======

* ``account_payment_order``
* ``queue_job``
* optionally ``account_payment_order_grouped_output`` (if installed,
  grouped moves are also generated in a job and split by batch size)

Why
===

``generated2uploaded`` posts every ``account.payment`` and then
``account_payment_order_grouped_output.generate_move`` builds **one
journal entry per payment.date**.

OCA sets ``account.payment.date = today``, so a remittance of 5000
lines becomes a single 5001-line move in the same HTTP request and
the worker collapses.

This addon:

1. Marks the order as uploaded and enqueues ``queue_job`` work.
2. Posts + reconciles payments in batches (default 100).
3. Then generates grouped moves, splitting each date group into
   chunks (default 200 payments per move).

Use together with ``tl_account_payment_order_due_date`` so
``payment.date`` is the due date and grouped moves split by maturity
instead of all landing on today.
