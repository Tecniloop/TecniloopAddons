# -*- coding: utf-8 -*-
# Part of SoftMuch. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, _
from odoo.http import request


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_wholesale = fields.Boolean(compute="_compute_is_wholesale")

    def _compute_is_wholesale(self):
        for partner in self:
            partner.is_wholesale = request.website.pricelist_id.web_display_mode == 'wholesale' if 'website_id' in request.context else False