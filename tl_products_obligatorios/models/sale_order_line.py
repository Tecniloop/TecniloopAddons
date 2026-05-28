from odoo import api, fields, models
from odoo.exceptions import UserError
import math

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    tiene_canon = fields.Char(string='Presupuesto con Canon')  
    
    def action_confirm(self):
        res = super().action_confirm()
        for record in self:
            if any(line.canon_calculado for line in record.order_line):
                record.tiene_canon = 'T'
        return res
    
class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    id_producto_padre = fields.Integer(string="ID Producto Padre")
    canon_calculado = fields.Boolean(string='Canon ya calculado',default=False)    

    @api.model
    def create(self,vals):
        """ Si es producto el display_type es igual a False. Se usan las decenas como referencia al producto i las unidades como orden de el.
        EJ: 100 = producto, [101, 102, 103] = productos/notas de este. 110 = otro producto, [111,112,113] = productos/notas de este.
        if 'display_type' in vals and vals['display_type'] == False:
            if vals['sequence'] > 100:
                vals['sequence'] =  math.trunc(vals['sequence'] / 10)
                vals['sequence'] += 1
            vals['sequence'] *= 10
        Si tiene una nota o seccion creada por user i no por modulo sigue el mismo orden 
        if 'display_type' in vals and (vals['display_type'] == 'line_section' or vals['display_type'] == 'line_note') and vals['sequence'] < 100:
            vals['sequence'] *= 10
        """
            
        records = super(SaleOrderLine, self).create(vals)
        # Mirar si tiene productos opcionales
        for record in records:
            partner_id = record.order_id.partner_id.parent_id or record.order_id.partner_id
            if record.display_type == False and (partner_id.opcional_obligatorio or partner_id.opcional_obligatorio):
                if 'a3erp_canon_company' in record.company_id._fields and record.company_id.a3erp_canon_company and 'carac2_id' in record.product_id._fields:
                    self.create_by_carac(record)
                elif record.product_id.productos_obligatorios:
                    self.create_by_product(record)
                elif record.product_id.categ_id.productos_obligatorios:
                    self.create_by_categ(record)
        
        return records
    
    def create_by_product(self, record = None):
        self = record
        try:
            if self.order_id.ids:
              for obl in self.product_id.productos_obligatorios:
                prod = self.env['product.product'].search([('product_tmpl_id', '=', obl.id)])
                valor = max(self.order_id.order_line, key=lambda x: x['sequence']).sequence
                linia = self.create({'product_id': prod.id, 'order_id': self.order_id.id,'product_uom_qty': self.product_uom_qty, 'sequence': valor +2}) 
                linia.id_producto_padre = self.id
                self.write({'canon_calculado':True})
        except Exception as e:
            raise UserError("Error:"+format(e))
      
    def create_by_categ(self, record = None):
        self = record
        try:
            if self.order_id.ids:
              for obl in self.product_id.categ_id.productos_obligatorios:
                prod = self.env['product.product'].search([('product_tmpl_id', '=', obl.id)])
                valor = max(self.order_id.order_line, key=lambda x: x['sequence']).sequence
                linia = self.create({'product_id': prod.id, 'order_id': self.order_id.id,'product_uom_qty': self.product_uom_qty, 'sequence': valor+2})
                linia.id_producto_padre = self.id
                self.write({'canon_calculado':True})
        except Exception as e:
            raise UserError("Error:"+format(e))
        
    def create_by_carac(self, record = None):
        """Este metodo añade el producto CANON informado en la CARAC2 del articulo.
        Args:
            record (Object, optional): Linea del pedido
        Returns:
            String: Exepcion
        """
        self = record
        try:
            if self.order_id.ids:
                for obl in self.product_id.carac2_id.product_ids:
                    prod = self.env['product.product'].search([('product_tmpl_id', '=', obl.id)])
                    valor = max(self.order_id.order_line, key=lambda x: x['sequence']).sequence
                    linia = self.create({'product_id': prod.id, 'order_id': self.order_id.id,'product_uom_qty': self.product_uom_qty, 'sequence': valor+2})
                    linia.id_producto_padre = self.id
                    self.write({'canon_calculado':True})
        except Exception as e:
            raise UserError("Error:"+format(e))
        
    @api.model
    def write(self,vals):
        record = super(SaleOrderLine, self).write(vals)
        if (self.order_id.partner_id.opcional_obligatorio or self.order_id.partner_id.parent_id.opcional_obligatorio) and 'product_uom_qty' in vals:
            for linia in self.order_id.order_line:
                if linia.id_producto_padre == self.id:
                    linia.product_uom_qty = vals['product_uom_qty']
        return record

    def unlink(self):
        """ELIMINAR LINEAS HIJAS SI SE ELIMINA SU PADRE"""
        for record in self:
            if record.exists():
                line_id = record.id
                child_line_id = record.order_id.order_line.filtered(lambda x: x.id_producto_padre == line_id)
                if child_line_id:
                    child_line_id.unlink()
        
        # SOLO PASAR LAS LINEAS QUE SE ELIMINAN EN LA PRIMERA ITERACION, YA QUE LAS HIJAS YA SE HAN ELIMINADO
        records_exists = self.filtered(lambda record: record.exists()) 
        return super(SaleOrderLine, records_exists).unlink()
            

