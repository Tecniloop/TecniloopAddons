# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

{
    "name": "Anticipos de crédito - Devoluciones de pago",
    "summary": "Contabiliza los impagos de efectos anticipados desde las "
    "devoluciones de pago",
    "version": "19.0.1.0.0",
    "license": "AGPL-3",
    "author": "Tecniloop",
    "website": "https://www.tecniloop.com",
    "category": "Banking addons",
    "development_status": "Beta",
    "depends": [
        "tl_account_credit_advance",
        "account_payment_return",
    ],
    "data": [
        "views/payment_return_view.xml",
        "views/account_payment_view.xml",
    ],
    "installable": True,
    "auto_install": True,
}
