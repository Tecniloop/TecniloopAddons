# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
{
    "name": "Importador SUENLACE - Queue Job",
    "version": "19.0.1.3.0",
    "category": "Accounting/Accounting",
    "summary": "Procesamiento asíncrono opcional para el importador SUENLACE",
    "author": "Tecniloop",
    "website": "https://github.com/tecniloop/l10n-spain",
    "license": "LGPL-3",
    "depends": [
        "tl_suenlace_import",
        "queue_job",
    ],
    "data": [
        "data/queue_job_function_data.xml",
        "views/suenlace_import_views.xml",
        "wizards/suenlace_import_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
    "development_status": "Beta",
    "maintainers": ["tecniloop"],
}
