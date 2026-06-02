
from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sale_global_margin = fields.Float(
        string="Margen % Global de Ventas", 
        default=0.0,
        help="Margen que se aplicara al precio de compra para calcular el precio de Venta al crear el Pedido de Venta."
    )
    
    analytic_skip_sale_ids = fields.Many2many(
        'account.analytic.account',
        'res_config_analytic_skip_sale_rel',
        'config_id',
        'analytic_id',
        string="Centros de coste sin pedido de venta",
        help="Centros de coste que SOLO generan pedido de compra"
    )
    force_analytic_ids = fields.Many2many(
        'account.analytic.account',
        'res_config_force_analytic_rel',
        'config_id',
        'analytic_id',
        string="Centros de coste que obligan a Nivel 2 y Nivel 3",
        help="Centros de coste que obligaran a informar el Nivel 2 y el Nivel 3."
    )
    
    @api.model
    def get_values(self):
        """Get the values from settings."""
        res = super(ResConfigSettings, self).get_values()
        icp_sudo = self.env['ir.config_parameter'].sudo()
        sale_global_margin = icp_sudo.get_param('tl_parseur_import.sale_global_margin')
        skip_ids = self.env['ir.config_parameter'].sudo().get_param('tl_parseur_import.analytic_skip_sale_ids','')
        force_ids = self.env['ir.config_parameter'].sudo().get_param('tl_parseur_import.force_analytic_ids','')
        res.update(
            sale_global_margin=sale_global_margin,
            analytic_skip_sale_ids=[(6, 0, [int(i) for i in skip_ids.split(',') if i])],
            force_analytic_ids=[(6, 0, [int(i) for i in force_ids.split(',') if i])]
        )
        return res
    
    def set_values(self):
        """Set the values. The new values are stored in the configuration parameters."""
        res = super(ResConfigSettings, self).set_values()
        self.env['ir.config_parameter'].sudo().set_param(
            'tl_parseur_import.sale_global_margin', self.sale_global_margin)
        
        self.env['ir.config_parameter'].sudo().set_param(
            'tl_parseur_import.analytic_skip_sale_ids',
            ','.join(map(str, self.analytic_skip_sale_ids.ids))
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'tl_parseur_import.force_analytic_ids',
            ','.join(map(str, self.force_analytic_ids.ids))
        )
        return res