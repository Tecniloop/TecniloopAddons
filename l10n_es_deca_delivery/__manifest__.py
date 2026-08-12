# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spain - DeCA / Delivery carrier partner bridge",
    "summary": (
        "Prefill the DeCA effective carrier from delivery_carrier_partner, and "
        "the tractor plate from a matching Fleet vehicle when Fleet is installed"
    ),
    "version": "19.0.1.0.0",
    "category": "Inventory/Inventory",
    "author": "Ecmr DeCA contributors",
    "license": "AGPL-3",
    "development_status": "Beta",
    "depends": ["l10n_es_deca", "delivery_carrier_partner"],
    "data": [
        "views/stock_picking_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
