from odoo import fields, models

PRIORITY_SELECTION = [
    ('0', 'Low'),
    ('1', 'Medium'),
    ('2', 'High'),
    ('3', 'Very High'),
]


class ProjectProject(models.Model):
    _inherit = 'project.project'

    priority = fields.Selection(
        PRIORITY_SELECTION,
        string='Priority',
        default='1',
    )
