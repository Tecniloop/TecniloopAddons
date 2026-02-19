# -*- coding: utf-8 -*-
#################################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2022-today Ascetic Business Solution <www.asceticbs.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#################################################################################


from odoo import api, models, fields


class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    allowed_delivery_addresses = fields.Many2many(
        comodel_name='res.partner',
        compute='_compute_allowed_delivery_addresses'
    )
    
    allowed_invoice_addresses = fields.Many2many(
        comodel_name='res.partner',
        compute='_compute_allowed_invoice_addresses'
    )
    
    @api.depends('partner_id')
    def _compute_allowed_invoice_addresses(self):
        """Busca las direcciones de facturacion permitidas para cada cliente seleccionado en el pedido de venta."""        
        for order in self:
            partner = order.partner_id.parent_id or order.partner_id or False
            if partner:
                invoicing_addreses = self.env['res.partner'].search([
                    '|',
                    ('id', '=', partner.id),
                    '&',
                    ('parent_id', '=', partner.id),
                    ('type', '=', 'invoice')
                ])
                order.allowed_invoice_addresses = invoicing_addreses.ids
            else:
                order.allowed_invoice_addresses = False    
    
    @api.depends('partner_id')
    def _compute_allowed_delivery_addresses(self):
        """
        Busca las direcciones de entrega permitidas para cada pedido de venta.
        Este método busca direcciones de entrega relacionadas con el Cliente del pedido de venta, si el partner_id es un contacto tiene en cuenta su padre.
        Tambien permite seleccionar la direccion del padre.
        """
        for order in self:
            partner = order.partner_id.parent_id or order.partner_id or False
            if partner:
                delivery_address = self.env['res.partner'].search([
                    '|',
                    ('id', '=', partner.id),
                    '&',
                    ('parent_id', '=', partner.id),
                    ('type', '=', 'delivery')
                ])
                order.allowed_delivery_addresses = delivery_address.ids
            else:
                order.allowed_delivery_addresses = False