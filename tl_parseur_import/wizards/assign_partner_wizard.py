from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare
import re

class AssignPartnerWizard(models.TransientModel):
    _name = 'assign.partner.wizard'
    _description = 'Wizard seleccionar el cliente y pedido del registro'
    
    sale_partner_id = fields.Many2one(
        string='Cliente Pedido de Venta',
        comodel_name='res.partner',
        ondelete='set null',
        help='Cliente al que se hará el pedido de Venta',
    )
    purchase_partner_id = fields.Many2one(
        string='Proveedor Pedido de Compra',
        comodel_name='res.partner',
        ondelete='set null',
        help='Proveedor al que se hará el pedido de compra',
    )    
    sale_order = fields.Many2one(
        string='Pedido',
        comodel_name='sale.order',
        ondelete='set null',
    )
    wizard_lines = fields.One2many(
        'assign.partner.wizard.line',
        'wizard_id',
        string='Líneas del Pedido',
    )
    
    analytic_account1_id = fields.Many2one(
        comodel_name='account.analytic.account',
        string='Centro de Coste 1',
        domain=lambda self: self._domain_analytic_account1()
    )
    analytic_account2_id = fields.Many2one(
        comodel_name='account.analytic.account',
        string='Centro de Coste 2',
        domain=lambda self: self._domain_analytic_account2()
    )
    analytic_account3_id = fields.Many2one(
        comodel_name='account.analytic.account',
        string='Centro de Coste 3',
        domain=lambda self: self._domain_analytic_account3()
    )
    
    def _domain_analytic_account1(self):
        # Obtener el registro activo de parseur.order
        order = self.env['parseur.order'].browse(
            self.env.context.get('active_id')
        )
        return order._domain_analytic_account1()
    
    def _domain_analytic_account2(self):
        # Obtener el registro activo de parseur.order
        order = self.env['parseur.order'].browse(
            self.env.context.get('active_id')
        )
        return order._domain_analytic_account2()
    
    def _domain_analytic_account3(self):
        # Obtener el registro activo de parseur.order
        order = self.env['parseur.order'].browse(
            self.env.context.get('active_id')
        )
        return order._domain_analytic_account3()
    
    skip_sale_order = fields.Boolean(
        compute="_compute_skip_sale_order",
        store=False,
    )
    manual_skip_sale_order = fields.Boolean(
        string="Solo Pedido de Compra",
        help="Si se marca, solo se creará el pedido de compra sin generar pedido de venta."
    )
    require_analytic_23 = fields.Boolean(
        compute='_compute_require_analytic_23',
        store=False
    ) 
    sale_mode = fields.Selection(
        selection=[
            ('oferta', 'Oferta'),
            ('pedido', 'Pedido'),
        ],
        string="Origen Documento",
        help="""Opciones:\n- Oferta: Las líneas se crean teniendo en cuenta si el pedido de venta ha sido ofertado o no (precio 0).
            \n- Pedido: Las líneas se crean con el precio de venta, ya que se trata de un pedido de venta directo. (No viene de oferta)""",
    )
    
    @api.depends('analytic_account1_id')
    def _compute_require_analytic_23(self):
        Param = self.env['ir.config_parameter'].sudo()
        ids = Param.get_param('tl_parseur_import.force_analytic_ids', '')
        force_ids = {int(i) for i in ids.split(',') if i}

        for rec in self:
            rec.require_analytic_23 = bool(
                rec.analytic_account1_id
                and rec.analytic_account1_id.id in force_ids
            )
            
    @api.depends('analytic_account1_id','manual_skip_sale_order')
    def _compute_skip_sale_order(self):
        Param = self.env['ir.config_parameter'].sudo()
        ids = Param.get_param('tl_parseur_import.analytic_skip_sale_ids', '')

        skip_ids = {int(i) for i in ids.split(',') if i}

        for rec in self:
            rec.skip_sale_order = bool(
                rec.manual_skip_sale_order or 
                rec.analytic_account1_id and rec.analytic_account1_id.id in skip_ids
            )

        # Si se omite el pedido de venta, limpiar campos relacionados
        if rec.skip_sale_order:
            self.sale_order = False
            self.sale_partner_id = False
            
    def _skip_sale_order(self):
        """Saber si crear el pedido de Venta o no."""
        Param = self.env['ir.config_parameter'].sudo()
        ids = Param.get_param('tl_parseur_import.analytic_skip_sale_ids', '')
        skip_ids = {int(i) for i in ids.split(',') if i}
        return (
            self.manual_skip_sale_order or 
            self.analytic_account1_id.id in skip_ids
        )
    
    @api.model
    def default_get(self, fields):
        """Cuando se abre el wizard, pre-cargar las lineas del documento de parseur."""
        
        res = super().default_get(fields)
        
        Param = self.env['ir.config_parameter'].sudo()
        ids = Param.get_param('tl_parseur_import.analytic_skip_sale_ids', '')
        skip_ids = {int(i) for i in ids.split(',') if i}
        
        active_id = self.env.context.get('active_id')
        parseur = self.env['parseur.order'].browse(active_id)

        if parseur:
            lines = []
            margen_str = self.env['ir.config_parameter'].sudo().get_param('tl_parseur_import.sale_global_margin')  # MARGEN GLOBAL DE CONFIGURACIÓN
            
            # Cargar lineas
            for line in parseur.order_lines:
                # if line.product_id:
                #     margin = (line.product_id.a3erp_product_margin) / 100 # Margen del producto
                # else:
                #     margin = 0.0
                    
                if margin == 0.0:
                    margin = float(margen_str)
                    
                lines.append((0, 0, {
                    'product_id': line.product_id.id if line.product_id else False,
                    'product_code': line.product_code,
                    'name': line.name,
                    'product_uom_qty': line.product_uom_qty,
                    'price_unit_cost': line.price_unit,
                    'price_subtotal': line.price_subtotal,
                    'discount': line.discount,
                    'margin': margin
                }))
                
            res['wizard_lines'] = lines
            res["manual_skip_sale_order"] = bool(parseur.analytic_account1_id and parseur.analytic_account1_id.id in skip_ids)
            
            # Pre-Cargar el proveedor
            partner = False
            if parseur.partner_vat:
                partner = self.env['res.partner'].search([('vat','=', parseur.partner_vat),('supplier_rank','>',0)], limit=1)
            if not partner:
                def normalize(text):
                    # Normaliza el nombre de cliente para buscar
                    text = text.lower()
                    return re.sub(r'[^\w]', '', text)
                
                incoming = normalize(parseur.partner_name) if parseur.partner_name else ""
                
                partners = self.env['res.partner'].search([])
                # Busca el cliente comparando con el valor normalizado
                if incoming:
                    partner = self.env['res.partner'].search([('name','ilike',incoming)], limit=1)
                    # partner = partners.filtered( 
                    #     lambda p: normalize(p.name).startswith(incoming)
                    # )[:1]
                
            res['purchase_partner_id'] = partner.id if partner else False
            
            if parseur.analytic_account1_id:
                res['analytic_account1_id'] = parseur.analytic_account1_id.id
                res['analytic_account2_id'] = parseur.analytic_account2_id.id
                res['analytic_account3_id'] = parseur.analytic_account3_id.id
                res['require_analytic_23'] = parseur.require_analytic_23
            
        return res
    
    def action_create_sale_order(self):
        """Crea un nuevo pedido de venta según los valores. Las lineas se crean a partir de los valores del Wizard."""
        self.ensure_one()
        parseur_doc = self.env['parseur.order'].browse(self.env.context.get('active_ids'))
        if not parseur_doc:
            raise UserError(_("No se encontró el registro de Parseur."))
        
        partner = self.sale_partner_id
        if not partner and not self._skip_sale_order():
            raise UserError(_("Debe seleccionar un cliente."))
        
        if not self.wizard_lines:
            raise UserError(_("No hay líneas para procesar."))
        
        purchase_order = self.create_purchase_order(parseur_doc)
        if self._skip_sale_order():
            parseur_doc.purchase_id = purchase_order

            return {
                'name': _('Pedido de Compra'),
                'view_mode': 'form',
                'res_model': 'purchase.order',
                'res_id': purchase_order.id,
                'type': 'ir.actions.act_window',
                'target': 'current',
            }
        
        try:
            sale_order = self.env['sale.order'].create({
                'partner_id': partner.id,
                'date_order': parseur_doc.date_order,
                'client_order_ref': parseur_doc.client_order_ref,
                'note': parseur_doc.notes,
                'origin': parseur_doc.origin,
            })
        except Exception as e:
            raise ValidationError(_(f"Error generando el Pedido de Venta: {format(e)}"))
        
        SaleOrderLine = self.env['sale.order.line']
        
        analytic_distribution = {}

        if self.analytic_account3_id:
            analytic_distribution[self.analytic_account3_id.id] = 100

        if self.analytic_account2_id:
            analytic_distribution[self.analytic_account2_id.id] = 100

        if self.analytic_account1_id:
            analytic_distribution[self.analytic_account1_id.id] = 100    
                
        try:
            for line in self.wizard_lines:
                # Si ya hay producto coger el del campo
                if not line.product_id:
                    product = self.search_create_product(line.product_code, line)
                else:
                    product = line.product_id
                
                SaleOrderLine.sudo().create({
                    'order_id': sale_order.id,
                    'product_id': product.product_variant_id.id,
                    #'product_template_id': product.id,
                    'name': line.name or product.name,
                    'product_uom_qty': line.product_uom_qty,
                    'margin_percent': line.margin,
                    'price_unit': line.sale_unit_price,
                    'analytic_distribution': analytic_distribution,
                    
                })
            
            sale_order.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': sale_order, 'origin': parseur_doc},
                subtype_xmlid='mail.mt_note',
            )
            parseur_doc.order_id = sale_order
            parseur_doc.purchase_id = purchase_order
            
            return {
                'name': _('Pedido de Venta'),
                'view_mode': 'form',
                'res_model': 'sale.order',
                'res_id': sale_order.id,
                'type': 'ir.actions.act_window',
                'target': 'current',
            }
            
        except Exception as e:
            raise ValidationError(_(f"Error generando las lineas del Pedido de Venta: {format(e)}\nReferencia: {line.product_code}"))
            
    def action_add_lines(self):
        """Añade las lineas a un pedido de venta ya existente. Las lineas se crean a partir de los valores del Wizard. 
            Este metodo controla mas cosas que la creacion directa de pedido.
        """
        self.ensure_one()
        parseur_doc = self.env['parseur.order'].browse(self.env.context.get('active_id'))
        if not parseur_doc:
            raise UserError(_("No se encontró el registro de Parseur."))

        sale_order = self.sale_order
        if not sale_order:
            raise UserError(_("Debe seleccionar un pedido de venta al que añadir las líneas."))
        
        if not self.wizard_lines:
            raise UserError(_("No hay líneas para procesar."))
        
        purchase_order = self.create_purchase_order(parseur_doc)
        
        SaleOrderLine = self.env['sale.order.line']
        
        try:          
            for line in self.wizard_lines:
                # Si ya hay producto coger el del campo
                if not line.product_id:
                    product = self.search_create_product(line.product_code, line)
                else:
                    product = line.product_id
                
                # BUSCAR LINIA CON ESE PRODUCTO Y VIENEN DE OFERTA
                existing_lines = sale_order.order_line.filtered(
                    lambda l: l.product_template_id.id == product.id and l.from_draft
                )
                create_new_line = True
                price_zero = False
                extra_section = False
                sequence = False
                
                for existing_line in existing_lines:
                                          
                    existing_qty = existing_line.product_uom_qty # Cantidad Ofertada
                    incoming_qty = line.product_uom_qty # Cantidad Albaran
                    
                    remaining_offered_qty = existing_qty - existing_line.parseur_qty_count
                    
                    # Si la linea viene de una oferta y la cantidad parseur es menor que la cantidad ofertada, actualizar el coste y no crear nueva linea.
                    if incoming_qty <= remaining_offered_qty:
                        if float_compare(
                            existing_line.purchase_price,
                            line.price_unit_cost,
                            precision_digits=2
                        ) != 0:
                            existing_line.sudo().purchase_price = line.price_unit_cost
                            product.sudo().standard_price = line.price_unit_cost

                        existing_line.sudo().parseur_qty_count += incoming_qty
                        create_new_line = False
                        break
                    
                    # Si la linea viene de una oferta y la cantidad parseur es mayor o igual que la cantidad ofertada, crear nueva linea con precio zero.
                    else:
                        # Consumir lo que queda de la oferta
                        if remaining_offered_qty > 0:
                            if float_compare(
                                existing_line.purchase_price,
                                line.price_unit_cost,
                                precision_digits=2
                            ) != 0:
                                existing_line.sudo().purchase_price = line.price_unit_cost
                                product.sudo().standard_price = line.price_unit_cost
                        
                        # Se actualiza siempre la QTY de Parseur
                        existing_line.sudo().parseur_qty_count += incoming_qty

                        # Calcular unidades EXTRA
                        extra_qty = incoming_qty - max(remaining_offered_qty, 0)

                        create_new_line = True
                        price_zero = True

                        # Buscar sección EXTRA
                        extra_section = sale_order.order_line.filtered(
                            lambda l: l.display_type == 'line_section'
                            and 'EXTRA' in (l.name or '').upper()
                        )

                        sequence = (
                            extra_section.sequence + 1
                            if extra_section
                            else max(sale_order.order_line.mapped('sequence') or [0]) + 1
                        )

                        # Guardar qty EXTRA para crear la línea
                        line_qty_extra = extra_qty
                        break   
                
                # Si no existe nignuna linia con ese producto, añadir con precio 0
                if not existing_lines:
                    create_new_line = True
                    price_zero = True
                    line_qty_extra = line.product_uom_qty
                    
                analytic_distribution = {}

                if self.analytic_account3_id:
                    analytic_distribution[self.analytic_account3_id.id] = 100

                if self.analytic_account2_id:
                    analytic_distribution[self.analytic_account2_id.id] = 100

                if self.analytic_account1_id:
                    analytic_distribution[self.analytic_account1_id.id] = 100
                            
                if create_new_line:
                        
                    if self.sale_mode == 'pedido':
                        # Siempre crear con precio de venta
                        price_unit = line.sale_unit_price
                        margin_percent = line.margin
                        price_zero = False

                    else:  # Oferta
                        price_unit = 0 if price_zero else line.sale_unit_price
                        margin_percent = line.margin if not price_zero else 0
                        
                    SaleOrderLine.sudo().create({
                        'order_id': sale_order.id,
                        'product_id': product.product_variant_id.id,
                        #'product_template_id': product.id,
                        'name': line.name or product.name,
                        'product_uom_qty': line_qty_extra if price_zero else line.product_uom_qty,
                        'price_unit': price_unit,
                        'purchase_price': line.price_unit_cost,
                        'margin_percent': margin_percent,
                        'sequence': sequence or max(sale_order.order_line.mapped('sequence') or [0]),
                        'analytic_distribution': analytic_distribution,
                        'is_extra_parseur': True,
                    })      
                
            sale_order.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': sale_order, 'origin': parseur_doc,'edit': True,},
                subtype_xmlid='mail.mt_note',
            )
            
            parseur_doc.sudo().write({
                'order_id': sale_order.id,
                'purchase_id': purchase_order.id,
            })
            
            return {
                'name': _('Pedido de Venta'),
                'view_mode': 'form',
                'res_model': 'sale.order',
                'res_id': sale_order.id,
                'type': 'ir.actions.act_window',
                'target': 'current',
            }
            
        except Exception as e:        
            raise ValidationError(_(f"Error añadiendo las lineas: {format(e)}\nReferencia: {line.product_code}"))        
    
    def create_purchase_order(self, parseur_doc):
        """Generar pedido de compra con las lineas del Wizard."""
        
        if not self.purchase_partner_id:
            raise UserError(_(f"No hay un proveedor informado."))
        else:
            sale_ref = self.sale_order.name or parseur_doc.client_order_ref
            try:                    
                purchase_order = self.env['purchase.order'].create({
                    'partner_id': self.purchase_partner_id.id,
                    'date_order': fields.Date.context_today(self),
                    'origin': sale_ref,
                    'partner_ref': parseur_doc.partner_ref,
                    'note': parseur_doc.notes,
                })
            except Exception as e:
                raise ValidationError(_(f"Error generando el Pedido de Compra: {format(e)}"))

        analytic_distribution = {}
        
        if self.analytic_account3_id:
            analytic_distribution[self.analytic_account3_id.id] = 100

        if self.analytic_account2_id:
            analytic_distribution[self.analytic_account2_id.id] = 100

        if self.analytic_account1_id:
            analytic_distribution[self.analytic_account1_id.id] = 100        
        
        for line in self.wizard_lines:
            # Si ya hay producto coger el del campo
            if not line.product_id:
                product = self.search_create_product(line.product_code, line).product_variant_id
            else:
                product = line.product_id.product_variant_id
                            
            try:
                self.env['purchase.order.line'].create({
                    'order_id': purchase_order.id,
                    'supplier_ref': line.product_code,
                    'product_id': product.id,
                    'name': line.name or product.name,
                    'product_qty': line.product_uom_qty,
                    'price_unit': line.price_unit_cost,
                    'price_subtotal': line.price_subtotal,
                    'discount': line.discount,
                    'analytic_distribution': analytic_distribution,
                    #'tax_ids': data.product_id.supplier_taxes_id.ids,
                    #'product_uom': product.uom_po_id.id,
                })
            except Exception as e:
                raise ValidationError(_(f"Error generando las lineas del Pedido de Compra: {format(e)}\nLinia: {line.product_code}"))
        
        purchase_order.message_post_with_source(
            'mail.message_origin_link',
            render_values={'self': purchase_order, 'origin': parseur_doc},
            subtype_xmlid='mail.mt_note',
        )
        
        return purchase_order
    
    def search_create_product(self, product_code, line):
        """
        Buscar producto con el siguiente orden:
            1. Código de proveedor (seller_ids.product_code)
            2. Nombre del producto (template)
            3. Nombre del producto en proveedor (seller_ids.product_name)
            4. default_code
        Si no existe, crearlo.

        :param product_code: Código del producto (proveedor o interno)
        :param line: Línea origen (debe contener name, price_unit_cost, margin...)
        :return: product.template
        """
        ProductTemplate = self.env['product.template'].sudo()
        product = False

        product_name = line.name

        # 1. Buscar por código de proveedor
        if product_code:
            domain = [('seller_ids.product_code', '=', product_code)]
            product = ProductTemplate.search(domain, limit=1)

        # 2. Buscar por nombre del producto
        if not product and product_name:
            product = ProductTemplate.search(
                [('name', '=', product_name)],
                limit=1
            )

        # 3. Buscar por nombre del producto en proveedores
        if not product and product_name:
            product = ProductTemplate.search(
                [('seller_ids.product_name', '=', product_name)],
                limit=1
            )

        # 4. Buscar por default_code
        if not product and product_code:
            product = ProductTemplate.search(
                [('default_code', '=', product_code)],
                limit=1
            )

        # 5. Si no existe → Crear producto
        if not product:
            product = self._create_product_with_supplier(product_code, line)

        return product

    def _create_product_with_supplier(self, product_code, line):
        """
        Crea un producto e informa el código en seller_ids
        en lugar de usar default_code.

        :param product_code: Código proveedor
        :param line: Línea del wizard
        :return: product.template
        """
        self.ensure_one()

        ProductTemplate = self.env['product.template'].sudo()
        SupplierInfo = self.env['product.supplierinfo'].sudo()

        supplier = line.wizard_id.purchase_partner_id
        if not supplier:
            raise UserError(_("No hay proveedor informado en el wizard."))

        vals = {
            'name': line.name or product_code or 'Producto',
            'standard_price': line.price_unit_cost,
            'type': 'consu',
            'sale_ok': True,
            'purchase_ok': True,
        }

        # Campo Margen
        if 'a3erp_product_margin' in ProductTemplate._fields:
            vals['a3erp_product_margin'] = line.margin * 100

        product = ProductTemplate.create(vals)
        
        #product.action_send_a3erp() # Crear producto en a3ERP justo después de crearse en Odoo

        SupplierInfo.create({
            'partner_id': supplier.id,
            'product_tmpl_id': product.id,
            'product_code': product_code,
            'product_name': line.name,
            'price': line.price_unit_cost,
        })

        return product
            
class AssignPartnerWizardLine(models.TransientModel):
    _name = 'assign.partner.wizard.line'
    _description = 'Líneas del Wizard de creación'
    
    wizard_id = fields.Many2one('assign.partner.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.template',
        'Producto',
        ondelete='set null',
    )
    product_code = fields.Char(string='Ref.Producto')
    name = fields.Char(string='Descripción')
    product_uom_qty = fields.Float(string='Cantidad')
    price_unit_cost = fields.Float(string='Precio de compra')
    discount = fields.Float(string='Descuento %')
    price_subtotal = fields.Float(string='Subtotal Compra')
    margin = fields.Float(string='Margen %')
    sale_unit_price = fields.Float(
        string='Precio de Venta',
        compute='_compute_sale_line_subtotal',
        inverse='_inverse_sale_line_subtotal',
        store=True
        )
    sale_line_subtotal = fields.Float(
        string='Subtotal', 
        compute='_compute_sale_line_subtotal',
        inverse='_inverse_sale_line_subtotal',
        store=True
    )

    @api.depends('price_unit_cost', 'margin','product_uom_qty')
    def _compute_sale_line_subtotal(self):
        for line in self:
            line.sale_unit_price = 1 * (line.price_unit_cost / (1 - line.margin)) if line.price_unit_cost else 0.0
            line.sale_line_subtotal = line.product_uom_qty * (line.price_unit_cost / (1 - line.margin)) if line.price_unit_cost else 0.0

    def _inverse_sale_line_subtotal(self):
        for line in self:
            pass
            
    def reset_sale_line_subtotal(self):
        for line in self:
            line._sale_line_subtotal = False
            line._compute_sale_line_subtotal()
