# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
{
    "name": "Importador SUENLACE (a3asesor Eco/Con)",
    "version": "19.0.1.13.0",
    "category": "Accounting/Accounting",
    "summary": "Importa SUENLACE.DAT con vencimientos, tesorería, "
               "conciliación y separación multicompañía.",
    "author": "Tecniloop",
    "website": "https://github.com/tecniloop/l10n-spain",
    "license": "LGPL-3",
    "depends": [
        "account",
        "l10n_es",
        "analytic",
    ],
    "external_dependencies": {
        "python": ["chardet"],
    },
    "data": [
        "security/ir.model.access.csv",
        "security/suenlace_security.xml",
        "data/suenlace_sequence_data.xml",
        "data/suenlace_cron_data.xml",
        "data/suenlace_default_mapping_data.xml",
        "views/suenlace_tax_mapping_views.xml",
        "views/suenlace_fiscal_position_mapping_views.xml",
        "views/res_config_settings_views.xml",
        "views/account_move_views.xml",
        "views/suenlace_import_views.xml",
        "wizards/suenlace_import_wizard_views.xml",
        "wizards/suenlace_default_mapping_wizard_views.xml",
        "views/suenlace_menus.xml",
    ],
    "installable": True,
    "application": True,
    "development_status": "Beta",
    "maintainers": ["tecniloop"],
}
