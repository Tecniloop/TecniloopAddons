==========================================
Payment Order Due Date as Journal Date
==========================================

Tecniloop addon that extends OCA ``account_payment_order``.

Usage
=====

On inbound payment orders whose execution date type is *Due Date*:

* Confirming the order still stores the maturity date on each payment line
  (standard OCA behaviour).
* The generated ``account.payment`` and its journal entry use that due date
  instead of today.

Outbound orders and execution types *Immediately* / *Fixed Date* are
unchanged.

Credits
=======

* Tecniloop
