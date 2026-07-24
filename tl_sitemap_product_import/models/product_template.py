# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models


class ProductTemplate(models.Model):
    _inherit = ["product.template", "res.brand.mixin"]
