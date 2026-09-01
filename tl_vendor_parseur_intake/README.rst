==========================
TL Vendor Parseur Intake
==========================

Private Tecniloop addon for Odoo 19.

Parses vendor delivery notes and bills from Parseur, matches purchase
orders, receives quantities and prepares draft vendor bills.

Installation
============

Copy ``tl_vendor_parseur_intake`` into the addons path and install
**TL Vendor Parseur Intake**.

Do not install the previous technical name ``vendor_parseur_intake``
alongside this module.

Configuration
=============

* Purchase → Settings: webhook token, price/qty policies.
* Vendor form → Parseur → Auto-validate Parseur receipts.
* DEBUG: ``--log-handler=odoo.addons.tl_vendor_parseur_intake:DEBUG``

Tests
=====

``odoo-bin -d DB -i tl_vendor_parseur_intake --test-tags=/tl_vendor_parseur_intake --stop-after-init``

Credits
=======

* Author: Tecniloop
* License: Other proprietary
