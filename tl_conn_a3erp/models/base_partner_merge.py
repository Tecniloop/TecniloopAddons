from odoo import models

class PartnerMergeWizard(models.TransientModel):
    _inherit = 'base.partner.merge.automatic.wizard'

    def _merge(self, partner_ids, dst_partner):
        return super(
            PartnerMergeWizard,
            self.with_context(from_merge=True)
        )._merge(partner_ids, dst_partner)