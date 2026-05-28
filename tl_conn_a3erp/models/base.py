from odoo import fields,models,api, _
from . import create_log
import requests, json, logging
from datetime import datetime, timedelta
from .web_service import *

_logger = logging.getLogger(__name__)

"CAMPOS POR DEFECTO PARA LAS TARIFAS"
MAX_FECHA = '31/12/2099'
MIN_FECHA = datetime.now() + timedelta(days=-2)

class ProductCategory(models.Model):
    _inherit = ['product.category']     
    
    a3erp_category_code = fields.Char(string='Cod.Categoria a3ERP')
    last_date_update = fields.Datetime(string='Fecha Última Actualización', help="Fecha de última actualización con los datos de a3ERP.")
    
    def process_replogs_familias(self, repValues):
        """ Metodo para procesar los replogs de Familias. 
        Args:
            repValues (Object): Lista de replogs a procesar. 
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'familias')
        if not required_fields_by_company: # CAMPOS REQUERIDOS
            create_log.create_log(self, "ERROR", False, self._name, False, "No hay campos requeridos para Familias.") 
        else:
            for replog in repValues.sorted(lambda x: x.fecha, reverse=False):
                new_categ = {}
                if replog.nombre:
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                    categ_id = self.search([('a3erp_category_code', '=', replog.codigo)])
                    try:  
                        if len(categ_id) < 2: #CONTROLAR SI HAY MAS DE UNA CATEGORIA CON ESTE CODART               
                            if categ_id and replog.movimiento in ('ALT','MOD'): # CATEGORIA EXISTENTE MODIFICADO O CREADO DE NUEVO EN A3
                                values_to_update = {'last_date_update': datetime.now()}
                                for field in required_fields:
                                    if replog[field.mapped_name]:
                                        if field.relational_table:
                                            value_id = self.resolve_field_values(field,replog)
                                            if value_id:
                                                values_to_update[field.odoo_field_name] = value_id 
                                        else:
                                            values_to_update[field.odoo_field_name] = replog[field.mapped_name]
                                                
                                categ_id.update(values_to_update)
                                replog.message_post(message_type='comment', body="Categoria actualizada correctamente.")

                            elif not categ_id and replog.movimiento in ('ALT','MOD'): # CATEGORIA NUEVO EN A3 Y EN ODOO
                                new_categ = {'last_date_update': datetime.now(), 'a3erp_category_code': replog.codigo}                            
                                for field in required_fields:
                                    if replog[field.mapped_name]:
                                        if field.relational_table:
                                            value_id = self.env[field.relational_table].search([(field.table_code,'=', replog[field.mapped_name]), ('company_id','in', (company_id, False))]).id
                                            if value_id:
                                                new_categ[field.odoo_field_name] = value_id
                                        else:
                                            new_categ[field.odoo_field_name] = replog[field.mapped_name]

                                try:
                                    self.create(new_categ)
                                    replog.message_post(message_type='comment', body=f"Categoria creado correctamente.")
                                except Exception as e:
                                    _logger.info(format(e))
                                    replog.message_post(message_type='comment', body=format(e))

                            replog.procesado = True
                            replog.error = False
                            self.env.cr.commit()
                        else:                
                            replog.message_post(message_type='comment', body=f"La Categoria {replog.codigo} esta duplicada.")
                            replog.error = True

                    except Exception as e:
                        _logger.info(format(e))
                        create_log.create_log(self, "ERROR", False, replog._name, replog.id, replog.descart, format(e), company_id)
                        replog.error = True
                        replog.message_post(message_type='comment', body=format(e))
                    finally:
                        continue
                
                else:
                    replog.message_post(message_type='comment', body=f"No hay un nombre de Categoria.")
                    replog.error = True

class ProductPricelist(models.Model):
    _inherit = ['product.pricelist']     

    partner_id = fields.Many2one(string='Cliente',comodel_name='res.partner', ondelete='restrict')
    a3erp_pricelist_code = fields.Char(string='Codigo Tarifa a3ERP')
    last_date_update = fields.Datetime(string='Fecha Última Actualización', help="Fecha de última actualización con los datos de a3ERP.")
    a3erp_pricelist_type = fields.Selection(
        string='Tipo de Tarifa', 
        default="standard",
        help="Estandard: tarifa normal que se puede aplicar a cualquier contacto.\nPrecios Especiales: Tarifa de cliente donde se guardan aparte de las lineas, las demas tarifas que pueda contener (Estandard, Descuento, Descuento Fam.).\nDescuento: Tarifa de descuento por cliente.\nDescuento Familia: Tarifa de descuentos por familia.", 
        selection=[('standard', 'Estandard'), ('cliente', 'Cliente'), ('descuentos_ac','Descuentos'), ('descuentos_fam','Descuentos Familia')])
    
    """OBSOLETO"""
    def process_rep_logs_tarifas(self, repValues):
        """Procesar replogs de Tarifas estandard.
        Args:
            repValues (List): Lista de Tarifas Estandard
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'tarifas')
        if not required_fields_by_company: # CAMPOS REQUERIDOS
            create_log.create_log(self, "ERROR", False, self._name, False, False, "No hay campos obligatorios informados para TARIFAS, revisar.") 
        else:
            for replog in repValues.sorted(lambda x: (x.tarifa, x.fecha), reverse=False):
                if replog.tarifa:
                    error = False           
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])

                    product = self.env['product.template'].search([('cod_articulo_a3', '=', replog.codart),('active','in', (False, True)), ('company_id','=', company_id)]) # PRODUCTO
                    if not product:
                        error = True
                        replog.error = True                    

                    if not error:
                        if len(product) < 2:
                            try:
                                pricelist_id = self.search([('a3erp_pricelist_code', '=', replog.tarifa)]) # TARIFA
                                if pricelist_id and replog.movimiento in ('ALT','MOD'): # MODIFICAR TARIFA
                                    update_pricelist = {'last_date_update': datetime.now()}

                                    pricelist_line = pricelist_id.item_ids.filtered(lambda x: x.product_tmpl_id.id == product.id)
                                    if pricelist_line: # MODIFICAR LINEA
                                        update_line = {}
                                        for field in required_fields:
                                            if not field.a3erp_field_name in ('TARIFAS.TARIFA', 'DESCTARIFA'): # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    update_line[field.odoo_field_name] = value_id
                                                else:
                                                    update_line[field.odoo_field_name] = replog[field.mapped_name]

                                        pricelist_line.write(update_line)
                                        replog.message_post(message_type='comment', body="Linea modificada.")
                                    else: # CREAR LINEA
                                        create_line = {'compute_price':'fixed', 'applied_on': '1_product'}
                                        for field in required_fields:
                                            if not field.a3erp_field_name in ('TARIFAS.TARIFA', 'DESCTARIFA'): # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    create_line[field.odoo_field_name] = value_id
                                                else:
                                                    create_line[field.odoo_field_name] = replog[field.mapped_name]

                                        pricelist_id.write({'item_ids': [(0,0, create_line)]})
                                        replog.message_post(message_type='comment', body="Linea creada.")

                                    pricelist_id.write(update_pricelist)

                                elif not pricelist_id and replog.movimiento in ('ALT','MOD'): # CREACION TARIFA CON LA PRIMERA LINEA
                                    new_pricelist = {'a3erp_pricelist_type': 'standard','last_date_update': datetime.now(),'a3erp_pricelist_code': replog['tarifa'],'name': replog['desctarifa']}
                                    line = {'compute_price':'fixed', 'applied_on': '1_product'}
                                    for field in required_fields:
                                        if not field.a3erp_field_name in ('TARIFAS.TARIFA', 'DESCTARIFA') :
                                            if field.relational_table:
                                                value_id = self.resolve_field_values(field, replog)
                                                line[field.odoo_field_name] = value_id
                                            else:
                                                line[field.odoo_field_name] = replog[field.mapped_name]

                                    new_pricelist['item_ids'] = [(0,0, line)]       

                                    try:
                                        self.create(new_pricelist)
                                        replog.message_post(message_type='comment', body="Tarifa creada.")
                                    except Exception as e:
                                        replog.message_post(message_type='comment', body=format(e))                                    

                                elif pricelist_id and replog.movimiento == 'BOR':
                                    pricelist_line = pricelist_id.item_ids.filtered(lambda x: x.product_tmpl_id.id == product.id)
                                    if pricelist_line:
                                        pricelist_line.unlink()
                                        replog.message_post(message_type='comment', body="Registro eliminado.")

                                replog.procesado = True
                                replog.error = False
                                self.env.cr.commit()

                            except Exception as e:
                                _logger.error(format(e))
                                replog.error = True
                                replog.message_post(message_type='comment', body=format(e))
                                create_log.create_log(self, "ERROR", False, self._name, replog.id, replog.desctarifa, format(e), company_id) 
                        else:
                            replog.error = True
                            replog.message_post(message_type='comment', body=f"El Producto esta repetido.")
                    else:
                        replog.error = True
                        replog.message_post(message_type='comment', body=f"El Producto no existe.")                                            
                else:
                    replog.error = True
                    replog.message_post(message_type='comment', body=f"No hay un codigo de Tarifa.")                        
    """Queda obsoleto hasta nuevo aviso"""
    def process_rep_logs_precios_esp(self, repValues):
        """Procesar los registros de precios especiales.
        Args:
            repValues (List): Lista de rep logs.
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'precios_esp')
        if not required_fields_by_company: # CAMPOS REQUERIDOS
            create_log.create_log(self, "ERROR", False, self._name, False, False, "No hay campos obligatorios informados para PRECIOS ESPECIALES, revisar.") 
        else:
            filtered_values = repValues.filtered(lambda x: x.codcli and x.fecha)
            for replog in filtered_values.sorted(lambda x: (x.codcli, x.fecha), reverse=False):         
                if replog.codcli:
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                    product_id = self.env['product.template'].search([('cod_articulo_a3', '=', replog.codart),('active','in', (False, True)), ('company_id','=', company_id)]) # PRODUCTO
                    partner_id = self.env['res.partner'].search_partner_by_a3erp_codcli(replog.codcli, company_id)
                    if product_id and partner_id:
                        if len(product_id) < 2:
                            try:
                                especial_pricelist = self.search([('partner_id.id','=', partner_id.id),('a3erp_pricelist_type', '=', 'precios_esp')]) # TARIFA
                                if especial_pricelist and replog.movimiento in ('ALT','MOD'): #MODIFICAR TARIFA
                                    update_pricelist = {'last_date_update': datetime.now(), 'active':True}
                                    especial_pricelist_line = especial_pricelist.item_ids.filtered(lambda x: x.product_tmpl_id.id == product_id.id)

                                    if especial_pricelist_line: # LA LINEA CON EL PRODUCTO EXISTE
                                        update_line = {}
                                        for field in required_fields:
                                            if 'CODART' in field.a3erp_field_name:
                                                update_line[field.odoo_field_name] = product_id.id
                                                continue  
                                            elif not field.a3erp_field_name in ('CODCLI'): # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    update_line[field.odoo_field_name] = value_id
                                                else:
                                                    update_line[field.odoo_field_name] = replog[field.mapped_name]

                                        especial_pricelist_line.write(update_line)
                                        replog.message_post(message_type='comment', body="Linea modificada.")

                                    else: #LA LINEA CON EL PRODUCTO NO EXISTE
                                        create_line = {'company_id':company_id, 'compute_price':'fixed', 'applied_on': '1_product', 'date_start': MIN_FECHA}
                                        for field in required_fields:
                                            if 'CODART' in field.a3erp_field_name:
                                                create_line[field.odoo_field_name] = product_id.id
                                                continue  
                                            elif not field.a3erp_field_name in ('CODCLI') : # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    create_line[field.odoo_field_name] = value_id
                                                else:
                                                    create_line[field.odoo_field_name] = replog[field.mapped_name]

                                        especial_pricelist.write({'item_ids': [(0,0, create_line)]})
                                        replog.message_post(message_type='comment', body="Linea creada.")

                                    especial_pricelist.write(update_pricelist) 

                                elif not especial_pricelist and replog.movimiento in ('ALT','MOD'): # CREAR TARIFA 
                                    # new_pricelist = self.create(new_especial_pricelist).id
                                    new_pricelist = self.create_pricelist(replog, partner_id, 'precios_esp', required_fields)
                                    if new_pricelist:
                                        partner_id.write({'property_product_pricelist': new_pricelist.id})
                                        replog.message_post(message_type='comment', body="Tarifa creada. Tarifa de la ficha del cliente actualizada.")
                                    else:
                                        replog.error = True
                                        continue

                                elif especial_pricelist and replog.movimiento == 'BOR':
                                    especial_pricelist_line = especial_pricelist.item_ids.filtered(lambda x: x.product_tmpl_id.id == product_id.id)
                                    if especial_pricelist_line:
                                        especial_pricelist_line.unlink(9)                                

                                replog.procesado = True
                                replog.error = False
                                self.env.cr.commit()

                            except Exception as e:
                                _logger.error(format(e))
                                replog.error = True
                                create_log.create_log(self, "ERROR", False, self._name, False, False, f"{format(e)}", company_id) 
                                replog.message_post(message_type='comment', body=f"{format(e)}")
                        else:
                            replog.error = True
                            replog.message_post(message_type='comment', body=f"El producto esta repetido.")                        
                    else:
                        replog.error = True
                        replog.message_post(message_type='comment', body=f"El Producto no existe o el Cliente no existe.")
                else:
                    replog.error = True
                    replog.message_post(message_type='comment', body=f"No hay un codigo de cliente.")
    """Queda obsoleto hasta nuevo aviso"""
    def process_rep_logs_descuentos_ac(self, repValues):
        """Procesar los registros de descuentos AC.
        Args:
            repValues (List): Lista de rep logs.
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'descuentos_ac')
        if not required_fields_by_company: # CAMPOS REQUERIDOS
            create_log.create_log(self, "ERROR", False, self._name, False, False, "No hay campos obligatorios informados para DESCUENTOS, revisar.") 
        else:
            filtered_values = repValues.filtered(lambda x: x.codcli and x.fecha)
            for replog in filtered_values.sorted(lambda x: (x.codcli, x.fecha), reverse=False):
                if replog.codcli:
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                    product_id = self.env['product.template'].search([('cod_articulo_a3', '=', replog.codart),('active','in', (False, True)), ('company_id','in', (company_id, False))]) # PRODUCTO
                    partner_id = self.env['res.partner'].search_partner_by_a3erp_codcli(replog.codcli, company_id)
                    if product_id and partner_id:
                        if len(product_id) < 2:
                            try:
                                discount_pricelist = self.search([('partner_id.id','=', partner_id.id),('a3erp_pricelist_type', '=', 'descuentos_ac')]) # TARIFA DESCUENTOS
                                if discount_pricelist and replog.movimiento in ('ALT','MOD'): #MODIFICAR TARIFA
                                    update_pricelist = {'last_date_update': datetime.now(), 'active':True}
                                    discount_line = discount_pricelist.item_ids.filtered(lambda x: x.product_tmpl_id.id == product_id.id)

                                    if discount_line: # LA LINEA CON EL PRODUCTO EXISTE
                                        update_line = {}
                                        for field in required_fields:
                                            value = field.a3erp_field_name.split('.')[1] if '.' in field.a3erp_field_name else field.a3erp_field_name
                                            if 'CODART' in field.a3erp_field_name:
                                                update_line[field.odoo_field_name] = product_id.id
                                                continue 
                                            elif not value in ('CODCLI','TIPREG'): # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    update_line[field.odoo_field_name] = value_id
                                                else:
                                                    if 'DESC' in field.a3erp_field_name:
                                                        update_line[field.odoo_field_name] = update_line.get(field.odoo_field_name, 0) + replog[field.mapped_name]
                                                    else:
                                                        update_line[field.odoo_field_name] = replog[field.mapped_name]

                                        discount_line.write(update_line)
                                        replog.message_post(message_type='comment', body="Linea modificada.")

                                    else: #LA LINEA CON EL PRODUCTO NO EXISTE
                                        create_line = {'company_id':company_id, 'compute_price':'percentage', 'applied_on': '1_product', 'date_start': MIN_FECHA}
                                        for field in required_fields:
                                            value = field.a3erp_field_name.split('.')[1] if '.' in field.a3erp_field_name else field.a3erp_field_name
                                            if 'CODART' in field.a3erp_field_name:
                                                create_line[field.odoo_field_name] = product_id.id
                                                continue 
                                            elif not value in ('CODCLI','TIPREG') : # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    create_line[field.odoo_field_name] = value_id
                                                else:
                                                    if 'DESC' in field.a3erp_field_name:
                                                        create_line[field.odoo_field_name] = create_line.get(field.odoo_field_name, 0) + replog[field.mapped_name]
                                                    else:
                                                        create_line[field.odoo_field_name] = replog[field.mapped_name]

                                        discount_pricelist.write({'item_ids': [(0,0, create_line)]})
                                        replog.message_post(message_type='comment', body="Linea creada.")

                                    discount_pricelist.write(update_pricelist) 

                                elif not discount_pricelist and replog.movimiento in ('ALT','MOD'): # CREAR TARIFA    
                                    pricelist = self.create_pricelist(replog, partner_id, 'precios_esp', required_fields)
                                    if pricelist:
                                        replog.message_post(message_type='comment', body="Tarifa descuentos creada.")
                                        pricelist_updated = self.update_partner_pricelist(replog, pricelist, partner_id, required_fields, 'descuentos_ac')   
                                        if not pricelist_updated:
                                            replog.error = True
                                            continue
                                    else:
                                        replog.error = True
                                        continue    

                                elif discount_pricelist and replog.movimiento == 'BOR': # ELIMINAR LINEA DE TARIFA
                                    discount_line = discount_pricelist.item_ids.filtered(lambda x: x.product_tmpl_id.id == product_id.id)
                                    if discount_line:
                                        discount_line.unlink()

                                replog.procesado = True
                                replog.error = False
                                self.env.cr.commit()

                            except Exception as e:
                                _logger.error(format(e))
                                replog.error = True
                                create_log.create_log(self, "ERROR", False, self._name, False, False, f"{format(e)}", company_id) 
                                replog.message_post(message_type='comment', body=f"{format(e)}")

                        else:
                            replog.error = True
                            replog.message_post(message_type='comment', body=f"El producto esta repetido.")                        
                    else:
                        replog.error = True
                        replog.message_post(message_type='comment', body=f"El Producto no existe o el Cliente no existe.")
                else:
                    replog.error = True 
                    replog.message_post(message_type='comment', body=f"No hay un codigo de cliente.")
    """Queda obsoleto hasta nuevo aviso"""
    def process_rep_logs_descuentos_af(self, repValues):
        """Procesar los registros de descuentos de familia.
        Args:
            repValues (List): Lista de rep logs.
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'descuentos_fam')
        if not required_fields_by_company: # CAMPOS REQUERIDOS
            create_log.create_log(self, "ERROR", False, self._name, False, False, "No hay campos obligatorios informados para DESCUENTOS FAMILIA, revisar.") 
        else:
            """Saber por que campo comparar el COD.""" 
            for replog in repValues.sorted(lambda x: (x.codart, x.fecha), reverse=False):
                if replog.famcli:
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                    product_id = self.env['product.template'].search([('cod_articulo_a3', '=', replog.codart),('active','in', (False, True)), ('company_id','=', company_id)]) # PRODUCTO

                    if product_id:
                        if len(product_id) < 2:      
                            
                            # TARIFAS CUYO CLIENTE TIENE ESA FAMILIA DESCUENTO INFORMADA
                            pricelist_famdesccli_id = self.env['product.pricelist'].search([('partner_id.cod_fam_desc', 'like', replog.famcli), ('company_id','in', (company_id, False))])
                            #discount_fam_pricelist = self.search([('a3erp_pricelist_code','=', replog.famcli),('a3erp_pricelist_type', '=', 'descuentos_fam')]) # TARIFA DESCUENTOS
                            for discount_fam_pricelist in pricelist_famdesccli_id:
                                try:
                                    if discount_fam_pricelist and replog.movimiento in ('ALT','MOD'): #MODIFICAR TARIFA
                                        update_pricelist = {'last_date_update': datetime.now(), 'active':True}
                                        discount_fam_line = next((x for x in discount_fam_pricelist.item_ids if x.product_tmpl_id.id == product_id.id), None)                                    

                                        if discount_fam_line: # LA LINEA CON EL PRODUCTO EXISTE
                                            update_line = {}
                                            for field in required_fields:
                                                value = field.a3erp_field_name.split('.')[1] if '.' in field.a3erp_field_name else field.a3erp_field_name
                                                if not value in ('CODCLI','FAMCLI','DESCFAM','TIPREG'): # EVITAR CAMPOS DE CABECERA
                                                    if field.relational_table:
                                                        value_id = self.resolve_field_values(field, replog)
                                                        update_line[field.odoo_field_name] = value_id
                                                    else:
                                                        update_line[field.odoo_field_name] = replog[field.mapped_name]

                                            discount_fam_line.write(update_line)
                                            replog.message_post(message_type='comment', body="Linea modificada.")

                                        else: #LA LINEA CON EL PRODUCTO NO EXISTE
                                            create_line = {'compute_price':'percentage', 'applied_on': '1_product', 'date_start': MIN_FECHA}
                                            for field in required_fields:
                                                value = field.a3erp_field_name.split('.')[1] if '.' in field.a3erp_field_name else field.a3erp_field_name
                                                if not value in ('CODCLI','FAMCLI','DESCFAM','TIPREG') : # EVITAR CAMPOS DE CABECERA
                                                    if field.relational_table:
                                                        value_id = self.resolve_field_values(field, replog)
                                                        create_line[field.odoo_field_name] = value_id
                                                    else:
                                                        if 'DESCUENT' in field.a3erp_field_name:
                                                            create_line[field.odoo_field_name] = create_line.get(field.odoo_field_name, 0) + replog[field.mapped_name]
                                                        else:
                                                            create_line[field.odoo_field_name] = replog[field.mapped_name]

                                            discount_fam_pricelist.write({'item_ids': [(0,0, create_line)]})
                                            replog.message_post(message_type='comment', body="Linea creada.")

                                        discount_fam_pricelist.write(update_pricelist) 

                                    elif not discount_fam_pricelist and replog.movimiento in ('ALT','MOD'): # CREAR TARIFA                                    
                                        pricelist = self.create_pricelist(replog, '', 'precios_esp', required_fields)
                                        if pricelist:
                                            replog.message_post(message_type='comment', body="Tarifa Cliente creada.")
                                        else:
                                            replog.error = True
                                            continue
                                        #self.update_partner_pricelist(replog, pricelist, False, required_fields, 'descuentos_fam')                                    

                                    elif discount_fam_pricelist and replog.movimiento == 'BOR': # ELIMINAR LINEA DE TARIFA
                                        discount_line = next((x for x in discount_fam_pricelist.item_ids if x.product_tmpl_id.id == product_id.id), None)   
                                        if discount_line:
                                            discount_line.unlink()

                                    replog.procesado = True
                                    replog.error = False
                                    self.env.cr.commit()

                                except Exception as e:
                                    _logger.error(format(e))
                                    replog.error = True
                                    create_log.create_log(self, "ERROR", False, self._name, False, False, f"{format(e)}", company_id) 
                                    replog.message_post(message_type='comment', body=f"{format(e)}")
                        else:
                            replog.error = True
                            replog.message_post(message_type='comment', body=f"El producto esta duplicado.")                        
                    else:
                        replog.error = True
                        replog.message_post(message_type='comment', body=f"El producto no existe.")
                else:
                    replog.error = True
                    replog.message_post(message_type='comment', body=f"No hay un codigo en {replog.famcli}.")
    """Queda obsoleto hasta nuevo aviso"""
    def process_rep_logs_descuentos_ff(self, repValues):
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'descuentos_ff')
        if not required_fields_by_company:
            create_log.create_log(self, "ERROR", False, self._name, False, False, "No hay campos obligatorios informados para DESCUENTOS FF, revisar.") 
            return
        
        for replog in repValues.sorted(lambda x: (x.famcli, x.fecha), reverse=False):
            if replog.famcli and replog.famart:
                company_id = replog.company_id.id if replog.company_id else None
                required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                categ_id = self.env['product.category'].search([('a3erp_category_code', '=', replog.famart)]) # CATEGORIA PRODUCTO
                if categ_id:
                    if len(categ_id) < 2:
                        
                        result = self._search_partner_and_pricelist(replog, company_id)

                        for partner, pricelist in result.items():
                            
                            try:
                                if pricelist and replog.movimiento in ('ALT','MOD'): # MODIFICAR/CREAR LINEA EN TARIFA
                                    update_pricelist = {'last_date_update': datetime.now(), 'active':True}
                                    categ_discount_line = next(
                                        (x for x in pricelist.item_ids if x.categ_id.id == categ_id.id and x.min_quantity == replog.unidades),
                                        None)

                                    if categ_discount_line: # LINEA CON CATEGORIA EXISTE
                                        update_line = {}
                                        for field in required_fields:
                                            value = field.a3erp_field_name.split('.')[1] if '.' in field.a3erp_field_name else field.a3erp_field_name
                                            if not value in ('CODCLI','FAMCLI','DESCFAM','TIPREG'): # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    update_line[field.odoo_field_name] = value_id
                                                else:
                                                    if 'DESCUENT' in field.a3erp_field_name:
                                                        update_line[field.odoo_field_name] = update_line.get(field.odoo_field_name, 0) + replog[field.mapped_name]
                                                        continue
                                                    update_line[field.odoo_field_name] = replog[field.mapped_name]
                                        categ_discount_line.write(update_line)
                                        replog.message_post(message_type='comment', body="Linea modificada.")

                                    else: #LA LINEA CON LA CATEGORIA NO EXISTE
                                        create_line = {'compute_price':'percentage', 'display_applied_on': '2_product_category', 'date_start': MIN_FECHA}
                                        for field in required_fields:
                                            value = field.a3erp_field_name.split('.')[1] if '.' in field.a3erp_field_name else field.a3erp_field_name
                                            if not value in ('CODCLI','FAMCLI','DESCFAM','TIPREG') : # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    create_line[field.odoo_field_name] = value_id
                                                else:
                                                    if 'DESCUENT' in field.a3erp_field_name:
                                                        create_line[field.odoo_field_name] = create_line.get(field.odoo_field_name, 0) + replog[field.mapped_name]
                                                        continue
                                                    create_line[field.odoo_field_name] = replog[field.mapped_name]
                                        pricelist.write({'item_ids': [(0,0, create_line)]})
                                        replog.message_post(message_type='comment', body="Linea creada.")

                                    pricelist.write(update_pricelist) 

                                elif not pricelist and replog.movimiento in ('ALT','MOD'): # CREAR TARIFA                                    
                                        pricelist = self.create_pricelist(replog, partner, 'cliente', required_fields)
                                        if pricelist:
                                            replog.message_post(message_type='comment', body="Tarifa Cliente creada")
                                        else:
                                            replog.error = True
                                            continue
                                        #self.update_partner_pricelist(replog, pricelist, False, required_fields, 'descuentos_fam')                                    

                                elif pricelist and replog.movimiento == 'BOR': # ELIMINAR LINEA DE TARIFA
                                    discount_line = next((x for x in pricelist.item_ids if x.categ_id.id == categ_id.id), None)
                                    if discount_line:
                                        discount_line.unlink()

                                replog.procesado = True
                                replog.error = False
                                self.env.cr.commit()
                                
                            except Exception as e:
                                _logger.error(format(e))
                                replog.error = True
                                create_log.create_log(self, "ERROR", False, self._name, False, False, f"{format(e)}", company_id) 
                                replog.message_post(message_type='comment', body=f"{format(e)}")
                            
                    else:
                        replog.error = True
                        replog.message_post(message_type='comment', body=f"Categoria {replog.famart} duplicada.")
                    
                else:
                    replog.error = True
                    replog.message_post(message_type='comment', body=f"Familia {replog.famart} no encontrada.")
                    
            else:   
                replog.error = True
                replog.message_post(message_type='comment', body=f"Falta el codigo de Familia Cliente o de Familia Articulo.")
    """Queda obsoleto hasta nuevo aviso"""
    def process_rep_logs_descuentos_cf(self, repValues):
        """Procesar los registros de descuentos cf.
        Args:
            repValues (List): Lista de rep logs.
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'descuentos_cf')
        if not required_fields_by_company: # CAMPOS REQUERIDOS
            create_log.create_log(self, "ERROR", False, self._name, False, False, "No hay campos obligatorios informados para DESCUENTOS CF, revisar.") 
        else:
            for replog in repValues.sorted(lambda x: (x.codcli, x.fecha), reverse=False):
                if replog.codcli:
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                    category_id = self.env['product.category'].search([('a3erp_category_code', '=', replog.famart), ('company_id','in', (company_id, False))]) # CATEGORIA DE PRODUCTO
                    partner_id = self.env['res.partner'].search_partner_by_a3erp_codcli(replog.codcli, company_id) # CLIENTE
                    
                    if partner_id:
                        if len(partner_id) < 2:                           
                            try:
                                discount_fam_pricelist = self.search([('a3erp_pricelist_code','=', replog.famart),('a3erp_pricelist_type', '=', 'descuentos_fam')]) # TARIFA DESCUENTOS
                                discount_pricelist = self.search([('partner_id','=', replog.codcli),('a3erp_pricelist_type', '=', 'descuentos_ac')]) # TARIFA DESCUENTOS
                                if discount_fam_pricelist and replog.movimiento in ('ALT','MOD'): #MODIFICAR TARIFA
                                    update_pricelist = {'last_date_update': datetime.now(), 'active':True}
                                    discount_line = discount_pricelist.item_ids.filtered(lambda x: x.categ_id.id == category_id.id)

                                    if discount_line: # LA LINEA CON EL PRODUCTO EXISTE
                                        update_line = {}
                                        for field in required_fields:
                                            if not field.a3erp_field_name in ('CODCLI', 'TIPREG'): # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    update_line[field.odoo_field_name] = value_id
                                                else:
                                                    if 'DESC' in field.a3erp_field_name:
                                                        update_line[field.odoo_field_name] = update_line.get(field.odoo_field_name, 0) + replog[field.mapped_name]
                                                    else:
                                                        update_line[field.odoo_field_name] = replog[field.mapped_name]

                                        discount_line.write(update_line)
                                        replog.message_post(message_type='comment', body="Linea modificada.")

                                    else: #LA LINEA CON EL PRODUCTO NO EXISTE
                                        create_line = {'compute_price':'percentage', 'applied_on': '2_product_category', 'date_start': MIN_FECHA}
                                        for field in required_fields:
                                            if not field.a3erp_field_name in ('CODCLI', 'TIPREG') : # EVITAR CAMPOS DE CABECERA
                                                if field.relational_table:
                                                    value_id = self.resolve_field_values(field, replog)
                                                    create_line[field.odoo_field_name] = value_id
                                                else:
                                                    if 'DESC' in field.a3erp_field_name:
                                                        create_line[field.odoo_field_name] = create_line.get(field.odoo_field_name, 0) + replog[field.mapped_name]
                                                    else:
                                                        create_line[field.odoo_field_name] = replog[field.mapped_name]

                                        discount_pricelist.write({'item_ids': [(0,0, create_line)]})
                                        replog.message_post(message_type='comment', body="Linea creada.")

                                    discount_pricelist.write(update_pricelist) 

                                elif not discount_fam_pricelist and replog.movimiento in ('ALT','MOD'): # CREAR TARIFA                                     
                                    pricelist = self.create_pricelist(replog, partner_id, 'descuentos_fam', required_fields)
                                    if pricelist:
                                        replog.message_post(message_type='comment', body="Tarifa descuentos creada.")
                                        pricelist_updated = self.update_partner_pricelist(replog, pricelist, partner_id, required_fields, 'descuentos_fam')
                                        if not pricelist_updated:
                                            replog.error = True
                                            continue   
                                    else:
                                        replog.error = True
                                        continue                                    

                                elif discount_fam_pricelist and replog.movimiento == 'BOR': # ELIMINAR LINEA DE TARIFA
                                    discount_line = discount_pricelist.item_ids.filtered(lambda x: x.categ_id.id == category_id.id)
                                    if discount_line:
                                        discount_line.unlink()

                                replog.procesado = True
                                replog.error = False
                                self.env.cr.commit()

                            except Exception as e:
                                _logger.error(format(e))
                                replog.error = True
                                create_log.create_log(self, "ERROR", False, self._name, False, False, f"{format(e)}", company_id) 
                        else:
                            replog.error = True
                            replog.message_post(message_type='comment', body=f"El cliente {replog.codcli} o categoria {replog.famart} estan repetidos. Revisar.")                        
                    else:
                        replog.error = True
                        replog.message_post(message_type='comment', body=f"El cliente {replog.codcli} o categoria de producto {replog.famart} no existe. Revisar.")
                else:
                    replog.error = True
                    replog.message_post(message_type='comment', body=f"No hay un cliente informado.")

    def _search_partner_and_pricelist(self, replog, company_id):
        """Buscar los clientes que tengan la familia de descuento informada y las tarifas asociadas."""
        result = {}
        partner_famdesc = self.env['res.partner'].search([('cod_fam_desc', 'like', replog.famcli.strip()), ('company_id','in', (company_id, False))])
        tarifas = self.search([
            ('partner_id', 'in', partner_famdesc.ids)
        ])
        result = {}
        for partner in partner_famdesc:
            tarifa = tarifas.filtered(lambda t: t.partner_id.id == partner.id)
            result[partner] = tarifa[0] if tarifa else False
        return result
    
    def create_pricelist(self, replog, partner_id, pricelist_type, required_fields, empty=False):
        """Metodo para crear las nuevas tarifas y lineas de Precios Esp; Descuentos; Descuentos Fam.
        Args:
            replog (Object): Registro RepLog
            partner_id (Object): Cliente
            pricelist_type (String): Tipo de tarifa
            required_fields (List): Campos requeridos
            empty (Boolean): Crear tarifa sin lineas
        Returns:
            Devuelve la tarifa si se ha creado bien.
        """
        
        new_pricelist = {
            #'discount_policy': 'without_discount',
            'a3erp_pricelist_type': 'cliente',
            'last_date_update': datetime.now(),
            'partner_id': partner_id.id,
            'company_id':partner_id.company_id.id,
            'name': partner_id.name
        }
        compute_price = 'fixed' if not 'tipreg' in self.env[replog._name]._fields else 'percentage'
        applied_on = '1_product' if not 'tipreg' in self.env[replog._name]._fields else '2_product_category'
        
        line = {'compute_price': compute_price, 'display_applied_on': applied_on, 'date_start': MIN_FECHA}
        search_global = True

        if not empty: 
            # CAMPOS REQUERIDOS
            for field in required_fields:
                value = field.a3erp_field_name.split('.')[1] if '.' in field.a3erp_field_name else field.a3erp_field_name
                if not value in ('CODCLI','FAMCLI','DESCFAM','TIPREG'):
                    if field.relational_table:
                        value_id = self.resolve_field_values(field, replog)
                        line[field.odoo_field_name] = value_id
                    else:
                        if 'DESCUENT' in field.a3erp_field_name:
                            line[field.odoo_field_name] = line.get(field.odoo_field_name, 0) + replog[field.mapped_name]
                        else:
                            line[field.odoo_field_name] = replog[field.mapped_name]

            new_pricelist['item_ids'] = [(0, 0, line)]

        # BUSCAR TARIFA GLOBAL
        if search_global:
            """Buscar la tarifa Global informada en el cliente."""
            campos, error = self.env['a3erp.clientes'].get_field_by_client(['TARIFA'], partner_id.cod_cliente_a3, replog.company_id)
            if campos == 'Unauthorized':
                replog.message_post(message_type='comment', body="Unauthorized: Usuario o Contraseña erroneos o Token Expirado.")
                return False
            elif campos == 'Error':
                replog.message_post(message_type='comment', body=error)
                return False
            elif campos:
                odoo_pricelist = self.search([('a3erp_pricelist_code', '=', campos['TARIFA'].strip()), ('company_id','=', partner_id.company_id.id)]).id
                item_lines = [] 
                if odoo_pricelist:
                    standard_line = {
                        'compute_price': 'formula',
                        'base': 'pricelist',
                        'base_pricelist_id': odoo_pricelist,
                        'applied_on': '3_global',
                        'date_start': MIN_FECHA,
                    }
                    item_lines.append((0, 0, standard_line))

                if not empty:
                    item_lines.append((0, 0, line))

                new_pricelist['item_ids'] = item_lines
                
        try:
            # CREAR NUEVA TARIFA
            pricelist_id = self.create(new_pricelist)
            partner_id.write({'property_product_pricelist': pricelist_id.id}) # ASIGNAR TARIFA A LA FICHA DEL CLIENTE
            return pricelist_id
        except Exception as e:
            _logger.error(format(e))
            create_log.create_log(self, "ERROR", False, self._name, False, False, f"{format(e)}", replog.company_id.id)
            replog.message_post(message_type='comment', body=f"{format(e)}")
            replog.error = True
            return False

    def update_partner_pricelist(self, repLog, newPricelist, partner, required_fields, pricelistType):
        """Actualizar tarifa de cliente con la tarifa creada de descuentos ac o descuentos familia.
        Args:
            repLog (Object): RepLog.
            newPricelist (Object): Tarifa nueva creada.
            partner (Object): Cliente.
            required_fields (List): Campos requeridos
            pricelistType (String): Tipo de tarifa
        """
        partner_special_pricelist = self.search([('a3erp_pricelist_type','=','precios_esp'), ('partner_id.id','=', partner.id)]) # TARIFA ESPECIFICA DE CLIENTE
        if partner_special_pricelist:
            partner_pricelist = partner.property_product_pricelist #TARIFA DE LA FICHA DEL CLIENTE
            if pricelistType == 'descuentos_ac':
                specific_pricelist = partner_special_pricelist.item_ids.filtered(
                    lambda x: x.base_pricelist_id.a3erp_pricelist_type == pricelistType
                    and x.partner_id.id == partner.id
                )
                if not partner_pricelist == partner_special_pricelist:
                    partner.write({'property_product_pricelist': partner_special_pricelist.id})
                    repLog.message_post(message_type='comment', body="Tarifa ficha cliente actualizada.")

            elif pricelistType == 'descuentos_fam':
                specific_pricelist = partner_special_pricelist.item_ids.filtered(
                    lambda x: x.base_pricelist_id.a3erp_pricelist_type == pricelistType
                    and x.base_pricelist_id.a3erp_pricelist_code 
                    == newPricelist.a3erp_pricelist_code
                )

            if not specific_pricelist: # SI NO EXISTE UNA LINEA CON LA TARIFA DE DESCUENTOS
                try:
                    new_line = {
                        'compute_price': 'formula',
                        'base': 'pricelist',
                        'base_pricelist_id': newPricelist.id,
                        'applied_on': '3_global',
                        'date_start': MIN_FECHA,
                    }
                    partner_special_pricelist.write({
                        'last_date_update': datetime.now(),
                        'item_ids': [(0,0, new_line)]
                    })
                    repLog.message_post(message_type='comment', body="Tarifa ficha cliente actualizada con la Tarifa de Descuento.")
                    return True
                
                except Exception as e:
                    _logger.error(format(e))
                    create_log.create_log(self, "ERROR", False, partner_special_pricelist._name, False, partner_special_pricelist.name, f"Error actualizando Tarifa de cliente {partner.name}: {format(e)}", partner.company_id.id) 
                    repLog.message_post(message_type='comment', body="Error actualizando la Tarifa de cliente con la Tarifa de Descuento.")
                    return False

        else:
            partner_pricelist = self.create_pricelist(repLog, partner, 'precios_esp', required_fields, empty=True) # CREAR TARIFA DE CLIENTE PORQUE NO EXISTE
            if partner_pricelist:
                partner.write({'property_product_pricelist': partner_pricelist.id})# ASIGNAR ESTA TARIFA A LA FICHA DEL CLIENTE
                pricelist_updated = self.update_partner_pricelist(repLog, newPricelist, partner, required_fields, pricelistType) # ACTUALIZAR LA TARIFA DE CLIENTE QUE HEMOS CREADO AÑADIENDO LA DE DESCUENTOS COMO LINEA
                if pricelist_updated:
                    repLog.message_post(message_type='comment', body="Tarifa cliente creada y actualizada ficha cliente.")
                    return True
                else:
                    return False
            else:
                return False

    def resolve_field_values(self, field, replog):
        """Añadir campos especiales
        Args:
            field (String): Campo
            replog (Object): RepLog
        Returns:
            Object: Devuelve el valor. 
        """
        if 'CODMON'in field.a3erp_field_name:
            if 'company_id' in self.env[field.relational_table]._fields:
                return self.env[field.relational_table].search([(field.table_code,'ilike', replog[field.mapped_name]), ('company_id','=', replog.company_id.id)]).id 
            else:
                return self.env[field.relational_table].search([(field.table_code,'ilike', replog[field.mapped_name])]).id 
        else:
            if 'company_id' in self.env[field.relational_table]._fields:
                if 'CODART'in field.a3erp_field_name:
                    return self.env[field.relational_table].search([(field.table_code,'=',replog[field.mapped_name]), ('company_id','=', replog.company_id.id)]).id
                else:
                    return self.env[field.relational_table].search([(field.table_code,'ilike', replog[field.mapped_name]), ('company_id','=', replog.company_id.id)]).id 
            else:
                return self.env[field.relational_table].search([(field.table_code,'=', replog[field.mapped_name])]).id 


class ResUsers(models.Model):
    _inherit = 'res.users'
    
    cod_rep_a3 = fields.Char(string='Cod.Representante a3ERP')
    cod_persona_a3 = fields.Char(string='Cod.Persona a3ERP')


class AccountTax(models.Model):
    _inherit = ['account.tax']     
    
    a3erp_iva_code = fields.Char(string='Cod. IVA a3ERP')
    last_date_update = fields.Datetime(string='Fecha Última Actualización', help="Fecha de última actualización con los datos de a3ERP.")


class AccountPaymentTerm(models.Model):
    _inherit = 'account.payment.term'

    a3erp_payment_term_code = fields.Char(string='Cod. a3ERP')
    last_date_update = fields.Datetime(string='Fecha Última Actualización', help="Fecha de última actualización con los datos de a3ERP.")
    
    def process_rep_logs_payment_term(self, repValues):
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'formapag')
        for replog in repValues.sorted(lambda x: x.forpag, reverse=False):
            if replog.forpag:
                try:                        
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                        
                    payment_term = self.search([('a3erp_payment_term_code','=',replog.forpag), ('active','in', (False, True)), ('company_id','=', company_id)])
                    if payment_term and replog.movimiento in ('ALT','MOD'):
                        update_payment_term = {'last_date_update': datetime.now()}
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if field.relational_table:
                                    value_id = self.resolve_field_values(field, replog)
                                    update_payment_term[field.odoo_field_name] = value_id if value_id else ''
                                elif 'code' in field.odoo_field_name:
                                    update_payment_term[field.odoo_field_name] = replog[field.mapped_name].strip()      
                                else:
                                    update_payment_term[field.odoo_field_name] = replog[field.mapped_name]

                        payment_term.update(update_payment_term)
                        replog.message_post(message_type='comment', body="Registro actualizado.")

                    elif not payment_term and replog.movimiento in ('ALT','MOD'):
                        new_payment_term = {"last_date_update": datetime.now(),"company_id": replog.company_id.id,}
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if field.relational_table:
                                    value_id = self.resolve_field_values(field, replog)
                                    new_payment_term[field.odoo_field_name] = value_id if value_id else ''
                                elif 'code' in field.odoo_field_name:
                                    new_payment_term[field.odoo_field_name] = replog[field.mapped_name].strip()                                    
                                else:
                                    new_payment_term[field.odoo_field_name] = replog[field.mapped_name]

                        self.create(new_payment_term)
                        replog.message_post(message_type='comment', body="Registro creado.")

                    replog.procesado = True
                    replog.error = False
                    self.env.cr.commit()

                except Exception as e:
                    _logger.info(format(e))
                    replog.error = True
                    replog.message_post(message_type='comment', body=format(e))
                    create_log.create_log(self, "ERROR", False, self._name, replog.id, replog.docpag, format(e), company_id)
                finally:
                    continue
            else:
                replog.message_post(message_type='comment', body=f"No hay un codigo de documento.")
                replog.error = True
                continue

    def resolve_field_values(self, field, replog):
        """Metodo para añadir condiciones especiales de los campos.
        Args:
            field (Object): Registro del Mappeado.
            replog (Object): Registro del replogs.
        Returns:
            String: Devuelve el valor buscado
        """
        return self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id


class AccountPaymentMode(models.Model):
    _inherit = 'account.payment.mode'

    a3erp_payment_mode_code = fields.Char(string='Cod. a3ERP')
    last_date_update = fields.Datetime(string='Fecha Última Actualización', help="Fecha de última actualización con los datos de a3ERP.")

    def process_rep_logs_payment_mode(self, repValues):
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'docupago')
        for replog in repValues.sorted(lambda x: x.docpag, reverse=False):
            if replog.docpag:
                try:                        
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                    
                    payment_mode = self.search([('a3erp_payment_mode_code','=',replog.docpag), ('active','in', (False, True)), ('company_id','=', company_id)])
                    if payment_mode and replog.movimiento in ('ALT','MOD'):
                        update_payment_mode = {'last_date_update': datetime.now()}
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if field.relational_table:
                                    value_id = self.resolve_field_values(field, replog)
                                    update_payment_mode[field.odoo_field_name] = value_id if value_id else ''
                                elif 'code' in field.odoo_field_name:
                                    update_payment_mode[field.odoo_field_name] = replog[field.mapped_name].strip()      
                                else:
                                    update_payment_mode[field.odoo_field_name] = replog[field.mapped_name]
                        payment_mode.update(update_payment_mode)
                        replog.message_post(message_type='comment', body="Registro actualizado.")
                        
                    elif not payment_mode and replog.movimiento in ('ALT','MOD'):
                        new_payment_mode = {
                            "last_date_update": datetime.now(),
                            "company_id": replog.company_id.id,
                            "payment_method_id": self.env['account.payment.method'].search([('payment_type','=','inbound')], limit=1).id,
                            "bank_account_link": 'fixed',
                            "fixed_journal_id": self.env['account.journal'].search([('type','=','bank'), ('company_id.id','=', replog.company_id.id)], limit=1).id,
                        }
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if field.relational_table:
                                    value_id = self.resolve_field_values(field, replog)
                                    new_payment_mode[field.odoo_field_name] = value_id if value_id else ''
                                elif 'code' in field.odoo_field_name:
                                    new_payment_mode[field.odoo_field_name] = replog[field.mapped_name].strip()      
                                else:
                                    new_payment_mode[field.odoo_field_name] = replog[field.mapped_name]
                                    
                        self.create(new_payment_mode)
                        replog.message_post(message_type='comment', body="Registro creado.")
                        
                    replog.procesado = True
                    replog.error = False
                    self.env.cr.commit()
                except Exception as e:
                    _logger.info(format(e))
                    replog.error = True
                    replog.message_post(message_type='comment', body=format(e))
                    create_log.create_log(self, "ERROR", False, self._name, replog.id, replog.docpag, format(e), company_id)
                finally:
                    continue                    
            else:
                replog.message_post(message_type='comment', body=f"No hay un codigo de documento.")
                replog.error = True
                continue

    def resolve_field_values(self, field, replog):
        """Metodo para añadir condiciones especiales de los campos.
        Args:
            field (Object): Registro del Mappeado.
            replog (Object): Registro del replogs.
        Returns:
            String: Devuelve el valor buscado
        """
        return self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id


class AccountAnalyticDistributionModel(models.Model):
    _inherit = ['account.analytic.distribution.model']
                
    def _find_or_create_distribution(self, product_id, analytic_account_id, company_id):
        """Encuentra o crea una línea de distribución analítica para un producto."""
        try:
            distribution_line = self.search([('product_id', '=', product_id)])
            analytic_account = self.env['account.analytic.account'].browse(analytic_account_id)
            plan_id = analytic_account.plan_id.id

            new_key = str(analytic_account_id)
            
            if not distribution_line:
                self.create({
                    'company_id': company_id,
                    'product_id': product_id,
                    'analytic_distribution': {new_key: 100}
                })
                return "Distribución analítica creada."
            
            existing_distribution = distribution_line.analytic_distribution or {}
            keys_to_remove = []
            for key in existing_distribution.keys():
                acc = self.env['account.analytic.account'].browse(int(key))
                if acc.plan_id.id == plan_id:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                existing_distribution.pop(key)

            # Añadir la nueva cuenta del plan
            existing_distribution[new_key] = 100.0

            distribution_line.write({
                'analytic_distribution': existing_distribution
            })

            return "Distribución analítica actualizada."
            #if len(existing_distribution) != 1 or int(next(iter(existing_distribution))) != analytic_account_id:                
            
        except Exception as e:
            raise ValueError(f"Error al manejar la distribución analítica: {e}")

    def _remove_distribution_by_plan(self, product_id, company_id, plan_id):
        """
        Elimina la cuenta analítica asociada a un PLAN concreto
        sin afectar a otros planes.
        """
        distribution_line = self.search(
            [('product_id', '=', product_id), ('company_id', '=', company_id)],
            limit=1
        )

        if not distribution_line or not distribution_line.analytic_distribution:
            return "No había distribución analítica que limpiar."

        existing_distribution = distribution_line.analytic_distribution
        keys_to_remove = []

        for key in existing_distribution.keys():
            acc = self.env['account.analytic.account'].browse(int(key))
            if acc.plan_id.id == plan_id:
                keys_to_remove.append(key)

        if not keys_to_remove:
            return "No había centro de coste en ese nivel."

        for key in keys_to_remove:
            existing_distribution.pop(key)

        distribution_line.write({
            'analytic_distribution': existing_distribution
        })

        return "Distribución analítica actualizada (nivel limpiado)."
    

    def _delete_distribution(self, product_id):
        """Elimina la línea de distribución analítica de un producto."""
        distribution_line = self.search([('product_id', '=', product_id)])
        if distribution_line:
            distribution_line.unlink()
            return "Distribución analítica eliminada."
        return "No se encontró distribución analítica para eliminar."
    
    def _post_message(self, record, message):
        """Publica un mensaje en el registro indicado."""
        record.message_post(message_type='comment', body=message)

    def process_product_analytic_account(self, product, analytic_vals, company_id):
        """Procesa y actualiza la cuenta analítica de un único producto des de la ficha."""
        plan_analitica_1 = self.env.ref('tl_conn_a3erp.analytic_plan_1').id
        plan_analitica_2 = self.env.ref('tl_conn_a3erp.analytic_plan_2').id
        plan_analitica_3 = self.env.ref('tl_conn_a3erp.analytic_plan_3').id
        try:
            automatic_analytic_account = product.carac8_id.cod_carac
            product_product = self.env['product.product'].search([('product_tmpl_id', '=', product.id)])

            mssg = ""

            #NO ANALÍTICA → eliminar todo
            if automatic_analytic_account == 'N':
                mssg = self._delete_distribution(product_product.id)

            # AUTOMÁTICA / NO DEFINIDA
            elif automatic_analytic_account in ('S', False):

                # -------- NIVEL 1 --------
                if analytic_vals.get('analitica_1'):
                    analytic_account = self._get_analytic_account(
                        analytic_vals['analitica_1'],
                        company_id,
                        plan_analitica_1
                    )
                    if analytic_account:
                        mssg = self._find_or_create_distribution(
                            product_product.id,
                            analytic_account.id,
                            company_id
                        ) + "\n"
                    else:
                        mssg += f"Error: Cuenta analítica '{analytic_vals['analitica_1']}' no encontrada para la empresa {company_id}.\n"

                # -------- NIVEL 2 --------
                if analytic_vals.get('analitica_2'):
                    analytic_account = self._get_analytic_account(
                        analytic_vals['analitica_2'],
                        company_id,
                        plan_analitica_2
                    )

                    if analytic_account:

                        mssg += self._find_or_create_distribution(
                            product_product.id,
                            analytic_account.id,
                            company_id
                        ) + "\n"
                    else:
                        mssg += f"Error: Cuenta analítica '{analytic_vals['analitica_2']}' no encontrada para la empresa {company_id}.\n"

                # -------- NIVEL 3 --------
                if analytic_vals.get('analitica_3'):
                    analytic_account = self._get_analytic_account(
                        analytic_vals['analitica_3'],
                        company_id,
                        plan_analitica_3
                    )
                    if analytic_account:
                        mssg = self._find_or_create_distribution(
                            product_product.id,
                            analytic_account.id,
                            company_id
                        ) + "\n"
                    else:
                        mssg += f"Error: Cuenta analítica '{analytic_vals['analitica_3']}' no encontrada para la empresa {company_id}.\n"

            if mssg:
                self._post_message(product, mssg)

        except Exception as e:
            _logger.error(f"Error al procesar la cuenta analítica para el producto {product.name}: {format(e)}")
            self._post_message(product, f"Error: {format(e)}")
            raise

    def process_replogs_analitica(self, repList):
        """Procesa los registros de logs para actualizar distribuciones analíticas."""
        plan_analitica_1 = self.env.ref('tl_conn_a3erp.analytic_plan_1').id
        plan_analitica_2 = self.env.ref('tl_conn_a3erp.analytic_plan_2').id
        plan_analitica_3 = self.env.ref('tl_conn_a3erp.analytic_plan_3').id
        
        for record in repList.filtered(lambda x: not x.error).sorted(lambda x: x.fecha, reverse=False):
            try:
                company_id = record.company_id.id if record.company_id else None
                product_template = self.env['product.template'].get_product_by_cod_a3(record.codart, company_id)
                if not product_template:
                    continue
                automatic_analytic_account = product_template.carac8_id.cod_carac
                product_product = self.env['product.product'].search([('product_tmpl_id', '=', product_template.id)])
                mssg = ""
                if automatic_analytic_account == 'N':
                    mssg = self._delete_distribution(product_product.id)
                    
                elif automatic_analytic_account in ('S', False):
                    # -------- NIVEL 1 --------
                    if record.analitica_1:
                        analytic_account = self._get_analytic_account(
                            record.analitica_1,
                            company_id,
                            plan_analitica_1
                        )

                        if not analytic_account:
                            raise ValueError(
                                f"Contabilidad analítica {record.analitica_1} "
                                f"no encontrada en Centro coste 1"
                            )

                        mssg = self._find_or_create_distribution(
                            product_product.id,
                            analytic_account.id,
                            company_id
                        )
                    else:
                        # LIMPIAR NIVEL 1
                        mssg = self._remove_distribution_by_plan(
                            product_product.id,
                            company_id,
                            plan_analitica_1
                        )
                    # -------- NIVEL 2 --------
                    if record.analitica_2:
                        analytic_account = self._get_analytic_account(
                            record.analitica_2,
                            company_id,
                            plan_analitica_2
                        )

                        if not analytic_account:
                            raise ValueError(
                                f"Contabilidad analítica {record.analitica_2} "
                                f"no encontrada en Centro coste 2"
                            )

                        mssg = self._find_or_create_distribution(
                            product_product.id,
                            analytic_account.id,
                            company_id
                        )
                    else:
                        #LIMPIAR NIVEL 2
                        mssg = self._remove_distribution_by_plan(
                            product_product.id,
                            company_id,
                            plan_analitica_2
                        )
                    # -------- NIVEL 3 --------
                    if record.analitica_3:
                        analytic_account = self._get_analytic_account(
                            record.analitica_3,
                            company_id,
                            plan_analitica_3
                        )

                        if not analytic_account:
                            raise ValueError(
                                f"Contabilidad analítica {record.analitica_3} "
                                f"no encontrada en Centro coste 3"
                            )

                        mssg = self._find_or_create_distribution(
                            product_product.id,
                            analytic_account.id,
                            company_id
                        )
                    else:
                        #LIMPIAR NIVEL 3
                        mssg = self._remove_distribution_by_plan(
                            product_product.id,
                            company_id,
                            plan_analitica_3
                        )
                        
                if mssg:
                    self._post_message(record, mssg)

                record.procesado = True
                record.error = False
            except Exception as e:
                _logger.error(format(e))
                record.error = True
                record.procesado = False
                self._post_message(record, f"Error: {format(e)}")
            finally:
                self.env.cr.commit()
                
    def _get_analytic_account(self, code, company_id, plan_id):
        return self.env['account.analytic.account'].search(
            [
                ('code', '=', code.strip()),
                ('company_id', '=', company_id),
                ('plan_id', '=', plan_id),
            ],
            limit=1
        )
            

class AccountAnalyticAccount(models.Model):
    _inherit = ['account.analytic.account']

    last_date_update = fields.Datetime(string='Fecha Última Actualización', help="Fecha de última actualización con los datos de a3ERP.")

    def process_rep_logs_analytic_account(self,repValues):
        """Procesar los replogs de las Cuentas analiticas.
        Args:
            repValues (List): Lista de repLogs.
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'centrosc')
        if not required_fields_by_company: # CAMPOS REQUERIDOS
            create_log.create_log(self, "ERROR", False, self._name, False, "No hay campos requeridos para Centros de Coste.") 
            return
        
        for replog in repValues.sorted(lambda x: x.nivelcentro, reverse=False):
            if replog.codigo:
                mssg = ""
                try:
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])

                    nivel = int(replog.nivelcentro or 1)
                    if nivel not in (1, 2, 3):
                        create_log.create_log(self, "ERROR", False, self._name, False, f"Nivel de centro no válido: {nivel}") 
                        return
                        
                    plan_xml_id = f"tl_conn_a3erp.analytic_plan_{nivel}"
                    plan_ref = self.env.ref(plan_xml_id, raise_if_not_found=False)
                    if not plan_ref:
                        # Buscar por nombre en fallback (por si el xml_id no está bien cargado)
                        plan_name = f"a3ERP: Centro coste {nivel}"
                        plan_ref = self.env['account.analytic.plan'].search([("name", "ilike", plan_name)], limit=1)
                    
                    if not plan_ref:
                        create_log.create_log(
                            self, "ERROR", False, self._name, False, False,
                            f"No se ha encontrado el Plan analítico para nivel {nivel}.", company_id
                        )
                        continue
                    
                    plan_id = plan_ref.id            
                    # NOTE: HAY CUENTAS ANALITICAS CON EL MISMO NOMBRE Y CODIGO PERO DISTINTO NIVEL, POR LO QUE HAY QUE COMPROVAR EL PLAN      
                    analytic_account = self.search([('code','=',replog.codigo),('plan_id','=', plan_id) ,('active','in', (False, True)), ('company_id','=', company_id)])

                    if analytic_account and replog.movimiento == 'BOR':
                        analytic_account.update({'active':False})
                        mssg = "Centro de Coste Archivado"

                    elif analytic_account and replog.movimiento in ('ALT','MOD'):
                        update_analytic_account = {'last_date_update': datetime.now(),"plan_id": plan_id,}
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if 'codigo' in field.mapped_name:
                                    value = replog[field.mapped_name].strip()
                                elif 'apen_centroln' in field.mapped_name:
                                    value = True if 'T' in replog[field.mapped_name] else False
                                else:
                                    value = replog[field.mapped_name]
                                update_analytic_account[field.odoo_field_name] = value
                            
                        analytic_account.update(update_analytic_account)
                        mssg = "Centro de Coste Actualizado"

                    elif not analytic_account and replog.movimiento in ('ALT','MOD'):
                        create_analytic_account = {
                            "last_date_update": datetime.now(),
                            "company_id": replog.company_id.id,
                            "plan_id": plan_id,
                        }
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if 'codigo' in field.mapped_name:
                                    value = replog[field.mapped_name].strip()
                                elif 'apen_centroln' in field.mapped_name:
                                    value = True if 'T' in replog[field.mapped_name] else False
                                else:
                                    value = replog[field.mapped_name]
                                create_analytic_account[field.odoo_field_name] = value
                                
                        self.create(create_analytic_account)                     
                        mssg = "Centro de Coste Creado"

                    replog.procesado = True
                    replog.error = False
                    self.env.cr.commit()
                    replog.message_post(message_type='comment', body=f"{mssg}") 

                except Exception as e:
                    _logger.info(format(e))
                    replog.error = True
                    replog.message_post(message_type='comment', body=format(e))
                    create_log.create_log(self, "ERROR", False, self._name, replog.id, replog.codigo, format(e), company_id)
                finally:
                    continue    
            else:
                replog.message_post(message_type='comment', body=f"No hay un codigo de Centro de Coste.")
                replog.error = True
                continue
