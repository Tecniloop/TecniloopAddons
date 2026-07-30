# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

{
    "name": "Anticipos de crédito - Riesgo financiero",
    "summary": "Separa los efectos cedidos y los impagados en el riesgo del cliente",
    "version": "19.0.1.0.0",
    "license": "AGPL-3",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "category": "Banking addons",
    "development_status": "Beta",
    "depends": [
        "tl_account_credit_advance",
        "account_financial_risk",
    ],
    "data": [
        "views/credit_advance_risk_view.xml",
        "views/res_partner_view.xml",
        "views/credit_advance_line_view.xml",
        "views/res_config_settings_view.xml",
    ],
    "installable": True,
    "auto_install": True,
}
