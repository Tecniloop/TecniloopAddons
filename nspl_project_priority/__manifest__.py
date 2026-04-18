# -*- coding: utf-8 -*-
{
    'name': 'Project And Task Priority',
    'version': '18.0.1.0.0',
    'summary': 'Add project priority and task priority filters for Odoo 18',
    'description': """
This module enhances Odoo 18 Project by:

- adding a priority field to projects,
- showing project priority in form, list and kanban views,
- adding filters and group by options for project priority,
- adding filters and group by options for task priority.
    """,
    'category': 'Project',
    'sequence': 5,
    'author': 'NSPL',
    'contributors': ['Khanak Hathi'],
    'website': 'https://www.namahsoftech.com',
    'license': 'OPL-1',
    'support': 'support@namahsoftech.com',
    'depends': ['project'],
    'data': [
        'views/project_view.xml',
        'views/task_view.xml',
    ],
    'images': ['static/description/img/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
