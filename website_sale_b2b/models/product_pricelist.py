# -*- coding: utf-8 -*-
# Part of SoftMuch. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, _


class Pricelist(models.Model):
    _inherit = "product.pricelist"

    web_display_mode = fields.Selection([('retail', _('Retail')), ('wholesale', _('Wholesale'))],
                                        required=True, string=_("Web Display Mode"), default='retail')
