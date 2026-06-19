from odoo import fields, models, api


class PosConfig(models.Model):
    _inherit = 'pos.config'

    display_discount_price = fields.Boolean(string='Display Discount Price in POS')


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    display_discount_price = fields.Boolean(string='Display Discount Price in POS',
                                            related="pos_config_id.display_discount_price",
                                            readonly=False)

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        icp = self.env['ir.config_parameter'].sudo()
        res.update(
            display_discount_price=icp.get_param(
                'eg_pos_display_discount_price.display_discount_price'))
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('eg_pos_display_discount_price.display_discount_price',
                      self.display_discount_price)
