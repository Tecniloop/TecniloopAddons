# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spain - DeCA PAdES Contractual Signatures",
    "summary": "Sign contractual DeCA PDFs with traceable PAdES signatures",
    "version": "19.0.1.1.0",
    "category": "Inventory/Inventory",
    "author": "Ecmr DeCA contributors, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/l10n-spain",
    "development_status": "Beta",
    "license": "AGPL-3",
    "depends": ["l10n_es_deca", "l10n_es_aeat"],
    "external_dependencies": {"python": ["pyhanko"]},
    "pre_init_hook": "pre_init_hook",
    "data": [
        "security/deca_security.xml",
        "views/deca_document_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
