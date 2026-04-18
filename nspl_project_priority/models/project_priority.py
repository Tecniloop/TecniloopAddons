from odoo import models, fields

PRIORITY_SELECTION = [
    ('0', 'Low'),
    ('1', 'Medium'),
    ('2', 'High'),
    ('3', 'Very High'),
]


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # priority = fields.Selection(PRIORITY_SELECTION, string="Priority", default='1')

    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Medium'),
        ('2', 'High'),
        ('3', 'Very High')
    ], string='Priority')


class ProjectTask(models.Model):
    _inherit = 'project.task'

    priority = fields.Selection(PRIORITY_SELECTION, string="Priority")
