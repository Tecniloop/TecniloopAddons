# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

{
    "name": "Anticipos de crédito - Gestión contable",
    "summary": "Contabilización de remesas financiadas (anticipo de créditos "
    "comerciales): cesión, financiación, vencimiento e impago",
    "version": "19.0.1.0.0",
    "license": "AGPL-3",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "category": "Banking addons",
    "development_status": "Beta",
    "depends": [
        "analytic",
        "account_payment_order",
        "l10n_es_account_banking_sepa_fsdd",
    ],
    "data": [
        "security/credit_advance_security.xml",
        "security/ir.model.access.csv",
        "wizard/credit_advance_funding_view.xml",
        "wizard/credit_advance_settle_view.xml",
        "wizard/credit_advance_unpaid_view.xml",
        "views/credit_advance_line_view.xml",
        "views/account_payment_mode_view.xml",
        "views/account_payment_order_view.xml",
        "views/account_payment_view.xml",
        "views/menus.xml",
    ],
    "installable": True,
}
