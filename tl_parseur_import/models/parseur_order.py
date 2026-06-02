from odoo import models, fields, _, api
import json
from dateutil import parser
from datetime import datetime
from odoo.exceptions import ValidationError, UserError
import requests
import base64


class ParseurOrder(models.Model):
    _name = 'parseur.order'
    _inherit = ['mail.thread']
    _description = 'Documento Parseur'
    _rec_name = "client_order_ref"
    
    active = fields.Boolean('Active', default=True)
    user_id = fields.Many2one(
        string='Asignado',
        comodel_name='res.users',
        ondelete='set null',
    )     
    partner_name = fields.Char(string='Proveedor')
    partner_vat = fields.Char(string='NIF')
    date_order = fields.Date(
        string='Fecha',
        default=fields.Date.context_today,
    )
    client_order_ref = fields.Char(string='Referencia Pedido')
    order_lines = fields.One2many(
        string='Lineas',
        comodel_name='parseur.order.line',
        inverse_name='parseur_order',
        copy=True
    )    
    amount_untaxed = fields.Float(string='Total sin impuestos')
    amount_tax = fields.Float(string='Total Impuestos')
    amount_total = fields.Float(string='Total')
    notes = fields.Text(string='Notas')    
    origin = fields.Char(string='Doc. Origen')
    partner_ref = fields.Char(string='Ref. Proveedor')
    original_link = fields.Html(string='Documento Original')
       
    json = fields.Text(string='JSON Recibido')    
    
    order_id = fields.Many2one(
        string='Documento de Venta',
        comodel_name='sale.order',
        ondelete='set null',
        copy=False,
        tracking=True
    )   
    
    purchase_id = fields.Many2one(
        string='Documento de Compra Asociado',
        comodel_name='purchase.order',
        ondelete='set null',
        copy=False,
        tracking=True
    )        
    temperaturas = fields.Char(string='Temperaturas')
    portes = fields.Char(string='Portes')
    error_log = fields.Text(string="Errores de procesamiento")
    
    analytic_account1_id = fields.Many2one(
        string='Centro de Coste 1',
        comodel_name='account.analytic.account',
        ondelete='set null',
        #domain=lambda self: self._domain_analytic_account1()
    ) 
    analytic_account2_id = fields.Many2one(
        string='Centro de Coste 2',
        comodel_name='account.analytic.account',
        ondelete='set null',
        #domain=lambda self: self._domain_analytic_account2()
    ) 
    analytic_account3_id = fields.Many2one(
        string='Centro de Coste 3',
        comodel_name='account.analytic.account',
        ondelete='set null',
        #domain=lambda self: self._domain_analytic_account3()
    ) 
    require_analytic_23 = fields.Boolean(
        compute='_compute_require_analytics',
        store=False
    )   
    
    is_manager = fields.Boolean(
        compute="_compute_is_manager",
        store=False
    )    
    state = fields.Selection(
        string='Estado',
        selection=[('pendiente', 'Pendiente Revisar'), ('aprobado', 'Aprobado'), ('facturado', 'Facturado/Imputado'), ('rechazado', 'Rechazado')],
        default='pendiente',
        tracking=True        
    )    

    @api.onchange('order_id')
    def _onchange_order_id(self):
        for record in self:
            if record.order_id:
                record.analytic_account1_id = record.order_id.plan2_id or False
                record.analytic_account2_id = record.order_id.plan3_id or False
                record.analytic_account3_id = record.order_id.plan4_id or False
                
    @api.onchange('client_order_ref')
    def _onchange_client_order_ref(self):
        for record in self:
            sale_order = self.env['sale.order'].sudo().search([
                ('name', '=', record.client_order_ref)
            ], limit=1)
            record.order_id = sale_order.id if sale_order else False
    
    def _compute_is_manager(self):
        group = self.env.user.has_group('tl_parseur_import.group_parseur_order_manager') 
        for rec in self:
            rec.is_manager = group
    
    @api.model
    def create(self, vals_list):
        for vals in vals_list:            
            if not vals.get('order_id') and vals.get('client_order_ref'):
                sale_order = self.env['sale.order'].sudo().search([
                    ('name', '=', vals['client_order_ref'])
                ], limit=1)
                if sale_order:
                    vals['order_id'] = sale_order.id
            
                if sale_order:
                    sale_order = self.env['sale.order'].browse(sale_order.id)
                    if not vals.get('analytic_account1_id') and sale_order.plan2_id:
                        vals['analytic_account1_id'] = sale_order.plan2_id.id
                    if not vals.get('analytic_account2_id') and sale_order.plan3_id:
                        vals['analytic_account2_id'] = sale_order.plan3_id.id
                    if not vals.get('analytic_account3_id') and sale_order.plan4_id:
                        vals['analytic_account3_id'] = sale_order.plan4_id.id
                
        return super().create(vals)
    
    def write(self, values):
        group = self.env.user.has_group('tl_parseur_import.group_parseur_order_manager') 
        
        if self.purchase_id and not group or (self.state == 'facturado' and not group):
            raise UserError(_("El documento esta bloqueado, contactar con un Administrador."))
        
        if 'purchase_id' in values:
            values['state'] = 'facturado'
            
        result = super(ParseurOrder, self).write(values)            
    
        return result
    
    @api.depends('analytic_account1_id')
    def _compute_require_analytics(self):
        Param = self.env['ir.config_parameter'].sudo()
        ids = Param.get_param('tl_parseur_import.force_analytic_ids', '')
        force_ids = {int(i) for i in ids.split(',') if i}

        for rec in self:
            rec.require_analytic_23 = (
                rec.analytic_account1_id
                and rec.analytic_account1_id.id in force_ids
            )
            
    def _domain_analytic_account1(self):
        plan = self.env.ref('tl_conn_a3erp.analytic_plan_1')
        return [('plan_id', '=', plan.id)]
    
    def _domain_analytic_account2(self):
        plan = self.env.ref('tl_conn_a3erp.analytic_plan_2')
        return [('plan_id', '=', plan.id)]
    
    def _domain_analytic_account3(self):
        plan = self.env.ref('tl_conn_a3erp.analytic_plan_3')
        return [('plan_id', '=', plan.id)]
    
    def create_record(self, payload):
        """Crea un nuevo registro de parseur.order con sus líneas"""
        values = payload.copy()
        env = self.env(user=self.env.ref('base.user_root').id)
        try:
            values['json'] = json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception as e:
            errores.append(f"Error serializando JSON: {str(e)}")
            values['json'] = "{}"
        
        order_lines_vals = payload.pop('order_lines', [])
        original_document = values.pop('OriginalDocument', False)
        order_lines = []        
        
        errores = []  # Lista para guardar errores ocurridos
         
        for line in order_lines_vals:
            if not isinstance(line, dict):
                errores.append("Línea inválida (no es dict).")
                continue
            product_code = line.get('product_code')
            product_name = line.get('name')
            price_unit = line.get('price_unit', 0.0) or 0.0
            qty = line.get('product_uom_qty', 0.0) or 0.0
            discount = line.get('discount', 0.0) or 0.0

            price_subtotal = line.get('price_subtotal')
            if price_subtotal in (None, ''):
                price_subtotal = qty * price_unit * (1 - discount / 100)

            # NOTE: Pre-cargar el producto por su referencia o nombre.
            product = False

            # 1. Buscar por código de proveedor
            if product_code:
                domain = [('seller_ids.product_code', '=', product_code)]
                product = self.env['product.template'].sudo().search(domain, limit=1)
                
            # 2. Si no se encuentra, buscar por nombre del producto
            if not product and product_name:
                product = self.env['product.template'].sudo().search(
                    [('name', '=', product_name)],
                    limit=1
                )
                
            # 3. Si sigue sin encontrarse, buscar por nombre del proveedor
            if not product and product_name:
                product = self.env['product.template'].sudo().search(
                    [('seller_ids.product_name', '=', product_name)],
                    limit=1
                )
                
            # 4. Última opcion buscar por 'default_code'
            if not product and product_code:
                product = self.env['product.template'].sudo().search(
                    [('default_code', '=', product_code)],
                    limit=1
                )

            # Resultado final
            if product:
                line['product_id'] = product.id
            else:
                errores.append(
                    f"[Linias] Producto no encontrado "
                    f"(código proveedor: {product_code}, nombre: {product_name})"
                )
                line['product_id'] = False
            
            line['price_subtotal'] = price_subtotal

            order_lines.append((0, 0, line))

        values['order_lines'] = order_lines
        
        # NOTE: Campos especiales
        # Fecha
        try:
            if values.get('date_order'):
                fecha_str = values['date_order'].strip()
                fecha_date = parser.parse(fecha_str, dayfirst=True).date()  # dayfirst=True asumes formato dd/mm/yyyy
                values['date_order'] = str(fecha_date)  # 'YYYY-MM-DD'
        except (ValueError, TypeError) as e:
            errores.append(f"[date_order] Error al convertir '{fecha_str}': {str(e)}")    
            values.pop('date_order', None)
        
        # Referencia
        if values.get('reference'):
            values['partner_ref'] = values.pop('reference')
        
        # Total sin impuestos
        if not values.get('amount_untaxed'):
            try:
                total_untaxed = 0.0

                for _, _, line_vals in order_lines:
                    subtotal = line_vals.get('price_subtotal') or 0.0
                    total_untaxed += float(subtotal)

                values['amount_untaxed'] = total_untaxed

            except Exception as e:
                errores.append(f"Error calculando amount_untaxed: {str(e)}")
                values['amount_untaxed'] = 0.0
        
        # NOTE: Crear registro
        try:
            record = env['parseur.order'].create(values)
        except Exception as e:
            errores.append(f"Error creando registro completo: {str(e)}")

            # Crear con datos mínimos
            record = self.create({
                'client_order_ref': payload.get('client_order_ref', 'ERROR'),
                'json': values.get('json', '{}'),
            })
        
        # Adjuntar Documento
        if original_document:
            url = original_document.get('url')
            filename = original_document.get('name')

            record.original_link = (
                f'<a href="{url}" '
                f'target="_blank" '
                f'class="o_form_uri o_external_link">'
                f'{filename}'
                f'</a>'
            )

            # Descargar y adjuntar archivo en el chatter
            if url:
                try:
                    response = requests.get(url)
                    response.raise_for_status()

                    file_content = base64.b64encode(response.content)

                    attachment = self.env['ir.attachment'].sudo().create({
                        'name': filename,
                        'type': 'binary',
                        'datas': file_content,
                        'res_model': 'parseur.order',
                        'res_id': record.id,
                        'mimetype': 'application/pdf',
                    })

                    record.sudo().message_post(
                        body="Documento original adjuntado.",
                        attachment_ids=[attachment.id],
                        author_id=self.env.ref('base.user_root').id
                    )

                except Exception as e:
                    errores.append(f"[OriginalDocument] Error descargando PDF: {str(e)}")
        
        if errores:
            record.error_log = '\n'.join(errores)

        return record
    
    def action_select_partner(self):
        self.ensure_one()
        sale_order = self.order_id or self.env['sale.order'].search([
            ('name', '=', self.client_order_ref)
        ], limit=1)
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Seleccionar Cliente/Proveedor'),
            'res_model': 'assign.partner.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_partner_id': sale_order.partner_id.id if sale_order else False,
                'default_sale_order': sale_order.id if sale_order else False,
                'default_sale_mode': 'oferta' if sale_order and 'OV' in sale_order.name else 'pedido',
                'skip_onchange_partner': True, 
            }
        }
        
class ParseurOrderLine(models.Model):
    _name = 'parseur.order.line'
    _description = 'Datos de Lineas'
    _rec_name = "parseur_order"
    
    parseur_order = fields.Many2one(
        string='Cabecera',
        comodel_name='parseur.order',
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.template',
        'Producto',
        ondelete='set null',
    )
    product_code = fields.Char(string='Ref. Producto')
    name = fields.Char(string='Descripción')
    product_uom_qty = fields.Float(string='Cantidad')
    price_unit = fields.Float(string='Precio unitario')
    discount = fields.Float(string='Descuento %')
    tax_id = fields.Char(string='Impuestos')
    price_subtotal = fields.Float(string='Subtotal')
    
    
    
    
    
    