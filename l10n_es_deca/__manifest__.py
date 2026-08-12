# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spain - Electronic Transport Control Document (DeCA)",
    "summary": "Issue immutable Spanish DeCA PDFs from stock transfers",
    "version": "19.0.1.1.1",
    "category": "Inventory/Inventory",
    "author": "Ecmr DeCA contributors, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/l10n-spain",
    "development_status": "Beta",
    "license": "AGPL-3",
    "depends": ["mail", "stock_picking_batch"],
    "external_dependencies": {"python": ["PIL", "qrcode"]},
    "data": [
        "security/deca_security.xml",
        "security/ir.model.access.csv",
        "data/deca_sequence.xml",
        "reports/deca_report.xml",
        "reports/deca_report_templates.xml",
        "views/deca_document_views.xml",
        "views/deca_version_views.xml",
        "views/deca_wizard_views.xml",
        "views/stock_picking_views.xml",
        "views/stock_picking_batch_views.xml",
        "views/deca_menus.xml",
    ],
    "installable": True,
    "application": False,
}
