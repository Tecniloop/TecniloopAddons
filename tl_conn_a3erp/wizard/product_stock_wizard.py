from odoo import models, fields, api
from odoo.exceptions import MissingError, UserError, ValidationError

class ProductStockWizard(models.TransientModel):
    _name = 'product.stock.wizard'
    _description = 'Wizard para mostrar el stock del producto.'
    
    real_stock = fields.Integer(string='Stock Real')
    sold_units = fields.Integer(string='Ventas')
    date_next_sale = fields.Date(string='Próxima entrega: ')
    purchase_units = fields.Integer(string='Compras')
    date_next_purchase = fields.Date(string='Próxima entrega: ')
    forecast_stock = fields.Integer(string='Previsto')    
    description = fields.Html(string='Información Adicional')
    
    
    def action_confirm(self):
        return {'type': 'ir.actions.act_window_close'}