# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

{
    "name": "Payment Order Upload Queue Job",
    "version": "19.0.1.0.0",
    "license": "AGPL-3",
    "category": "Banking addons",
    "summary": "Process payment order file upload (post, reconcile, "
    "grouped moves) asynchronously with queue_job.",
    "author": "Tecniloop",
    "website": "https://tecniloop.com",
    "depends": ["account_payment_order", "queue_job"],
    "data": [
        "data/queue_job_channel_data.xml",
        "data/queue_job_function_data.xml",
        "views/account_payment_mode_views.xml",
        "views/account_payment_order_views.xml",
    ],
    "installable": True,
    "application": False,
    "development_status": "Beta",
    "maintainers": ["tecniloop"],
}
