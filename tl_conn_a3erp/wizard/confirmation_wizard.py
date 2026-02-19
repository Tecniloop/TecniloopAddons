from odoo import models, fields, api
from odoo.exceptions import MissingError, UserError, ValidationError

class SaleConfirmationWizard(models.TransientModel):
    _name = 'sale.confirmation.wizard'
    _description = 'Wizard de confirmacion del envio de Oferta'
    
    message = fields.Text()
    
    def confirm_button(self):
        productos_sin_codart = self.env['product.template'].browse(self._context.get('productos_sin_codart', []))
        
        if self._context.get('active_model') == 'sale.order':
            record = self.env['sale.order'].browse(self._context.get('active_id'))
        elif self._context.get('active_model') == 'purchase.order':
            record = self.env['purchase.order'].browse(self._context.get('active_id'))
            
        check_products = [] #Productos que requieren de campos obligatorios
        for product in productos_sin_codart:
            if product.queue_state != 'PENDIENTE':
                product_response = product.with_context({'create_from_sale':True}).action_send_a3erp()
                if product_response:
                    check_products.append(product.name)
        
        if check_products:
            lista = '\n'.join(f"- {x}" for x in check_products)
            raise ValidationError(f"Alguno/s productos requieren de campos obligatorios:\n{lista}")
        else:
            record.queue_state = "ESPERA"
            record.message_post(message_type='comment', body="Pedido en ESPERA de los Articulos")
        
        return {'type': 'ir.actions.act_window_close'}