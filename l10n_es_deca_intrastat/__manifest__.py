# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spain - DeCA / Intrastat bridge",
    "summary": (
        "Let the DeCA goods-nature text be built from CN8 codes (Intrastat) "
        "instead of sale-line/product descriptions, as an Inventory setting"
    ),
    "version": "19.0.1.0.0",
    "category": "Inventory/Inventory",
    "author": "Ecmr DeCA contributors",
    "license": "AGPL-3",
    "development_status": "Beta",
    "depends": ["l10n_es_deca", "intrastat_product"],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
