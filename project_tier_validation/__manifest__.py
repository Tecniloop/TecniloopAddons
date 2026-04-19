{
    "name": "Project Tier Validation",
    "summary": "Extends Projects to support a tier validation process.",
    "version": "18.0.1.0.0",
    "category": "Project",
    "website": "https://github.com/OCA/project",
    "author": "OpenAI, Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": ["project", "base_tier_validation"],
    "data": [
        "data/mail_data.xml",
        "views/project_project_views.xml",
    ],
}
