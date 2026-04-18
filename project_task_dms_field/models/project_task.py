# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class ProjectTask(models.Model):
    _name = "project.task"
    _inherit = ["project.task", "dms.field.mixin"]
