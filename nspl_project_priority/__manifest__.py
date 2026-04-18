# -*- coding: utf-8 -*-
{
    'name': 'Project And Task Priority',
    'version': '19.0.1',
    'summary': """Add Priority to Projects and Tasks with Filters and Kanban Rating""",
    'description': """
This module enhances Odoo's project management features by adding priority fields to both projects and tasks, helping teams stay focused and organized.

✔ Set priority on both projects and tasks  
✔ View priority visually in Kanban using ratings  
✔ Filter and group by priority for better task planning  
✔ Improves project tracking and team coordination  
✔ Seamless integration with Odoo Project app  

Ideal for teams that want to manage workloads and deadlines more effectively.
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
        'security/ir.model.access.csv',
        'views/project_view.xml',
        'views/task_view.xml',
    ],
    'images': ['static/description/img/banner.png'],
    'installable': True,
    'auto_install': False,
    'application': True,
}
