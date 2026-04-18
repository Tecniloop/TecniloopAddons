# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Project Task DMS Field",
    "version": "18.0.1.0.0",
    "category": "Project",
    "summary": "Embed DMS documents on project tasks",
    "author": "Tecniloop",
    "license": "AGPL-3",
    "depends": ["project", "dms_field"],
    "installable": True,
    "data": [
        "views/project_task_view.xml",
    ],
    "demo": ["demo/dms_data.xml"],
}
