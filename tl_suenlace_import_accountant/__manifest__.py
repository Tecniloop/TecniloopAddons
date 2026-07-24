# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
{
    "name": "Importador SUENLACE - Menú Contabilidad Enterprise",
    "version": "19.0.1.0.1",
    "category": "Accounting/Accounting",
    "summary": "Sitúa SUENLACE en la aplicación Contabilidad Enterprise",
    "author": "Tecniloop",
    "website": "https://github.com/tecniloop/l10n-spain",
    "license": "LGPL-3",
    "depends": [
        "tl_suenlace_import",
        "account_accountant",
    ],
    "data": [
        "views/suenlace_menu.xml",
    ],
    "auto_install": True,
    "installable": True,
    "application": False,
    "development_status": "Beta",
    "maintainers": ["tecniloop"],
}
