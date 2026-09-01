# Copyright 2026 Tecniloop
# License Other proprietary.
{
    "name": "TL Vendor Parseur Intake",
    "version": "19.0.1.4.0",
    "category": "Inventory/Purchase",
    "summary": "Parseur intake for vendor delivery notes and bills with PO matching",
    "author": "Tecniloop",
    "website": "https://tecniloop.com",
    "license": "Other proprietary",
    "maintainers": ["tecniloop"],
    "development_status": "Beta",
    "depends": [
        "purchase",
        "purchase_stock",
        "stock",
        "account",
        "mail",
        "barcodes",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/vendor_document_intake_security.xml",
        "data/ir_sequence_data.xml",
        "views/parseur_mailbox_views.xml",
        "views/vendor_document_intake_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "tl_vendor_parseur_intake/static/src/intake_hotkeys.js",
        ],
    },
    "application": False,
    "installable": True,
}
