from odoo import models, api, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    #CAMPO SELECTION 1 PARA OFERTA
    etapa_oferta = fields.Selection([
        ('presupuesto', 'Presupuesto'),
        ('pendiente de validacion', 'Pendiente de Validación'),
        ('valorado', 'Valorado'),
        ('enviado a cliente', 'Enviado a cliente'),
    ], string='Etapa Oferta MST',default='presupuesto')

    etapa_comanda = fields.Selection([
        ('pedido de venta', 'Pedido de Venta'),
        ('pendiente de planificacion', 'Pendiente de Planificación'),
        ('pendiente materiales', 'Pendiente Materiales'),
        ('material ok', 'Material OK'),
        ('en curso', 'En Curso'),
        ('terminado', 'Terminado'),
    ], string='Etapa Comanda MST',default='pedido de venta')

    # Resetear la etapa de comanda al confirmar
    @api.onchange('state')
    def _onchange_state_control(self):
        if self.state == 'sale' and self.etapa_comanda == 'pedido de venta':
            # Si se confirma el pedido, nos aseguramos que esté en 'pedido de venta' 
            # (o podrías querer cambiarlo a la siguiente etapa)
            pass