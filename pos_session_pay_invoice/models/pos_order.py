# Copyright 2023 Jose Zambudio - Aures Tic <jose@aurestic.es>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models
from odoo.fields import Domain


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def search_paid_order_ids(self, config_id, domain, limit, offset):
        """Ignore paid orders without receipt reference when loading paid orders."""
        new_domain = Domain(domain) & Domain("pos_reference", "!=", False)
        return super().search_paid_order_ids(
            config_id,
            new_domain,
            limit,
            offset,
        )
