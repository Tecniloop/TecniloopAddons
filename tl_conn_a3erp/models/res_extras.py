
# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from . import create_log
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

class ResCargos(models.Model):
    _name = 'res.cargos'
    _description = 'Cargos'
    #_rec_name = 'desc_cargo'
    _order = 'cod_cargo'

    active = fields.Boolean('Active', default=True)
    id_cargo = fields.Char(string='ID Cargo')
    cod_cargo = fields.Char(string='Codigo')
    desc_cargo = fields.Char(string='Descripción')
    observaciones = fields.Text(string='Observaciones')
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    last_date_update = fields.Datetime(string='Fecha Última Actualización', help="Fecha de última actualización con los datos de a3ERP.")
    
    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        if not name:
            return super().name_search(name, args, operator, limit)

        if name:
            domain = ['|', ('cod_cargo', operator, name), ('desc_cargo', operator, name)]
            if args:
                domain = ['&'] + args + domain
            records = self.search_fetch(domain, ['display_name'], limit=limit)
            return [(record.id, record.display_name) for record in records.sudo()]
    
    @api.depends(lambda self: (self._rec_name,) if self._rec_name else ())
    def _compute_display_name(self):
        """Compute the value of the `display_name` field."""
        for record in self:
            record.display_name = f"{record.desc_cargo}"
    
    def process_replogs_cargos(self, repValues):
        """
        Procesar los replogs de caracteristicas.
        Args:
            repValues (List): Lista de replogs
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'cargos')
        ordenados = sorted(
            [x for x in repValues if not x.error],
            key=lambda x: x.fecha, reverse = False
        )
        for replog in ordenados:
            if replog.codigo:
                try:         
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])             
                    
                    cargo = self.search([('cod_cargo','=', replog.codigo), ('active','in', (False, True)), ('company_id','=', company_id)])
                    if cargo and replog.movimiento in ('ALT','MOD'):
                        values_to_update = {'last_date_update': datetime.now(), 'active': True, 'company_id': replog.company_id.id}
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if field.relational_table:
                                    value_id = self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id
                                    if value_id:
                                        values_to_update[field.odoo_field_name] = value_id 
                                else:
                                    values_to_update[field.odoo_field_name] = replog[field.mapped_name]
                                    
                        cargo.update(values_to_update)
                        replog.message_post(message_type='comment', body="Cargo actualizado correctamente.")
                        
                    elif not cargo and replog.movimiento in ('ALT','MOD'):
                        new_cargo = {'last_date_update': datetime.now(), 'company_id': replog.company_id.id}
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if field.relational_table:
                                    value_id = self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id
                                    if value_id:
                                        new_cargo[field.odoo_field_name] = value_id 
                                else:
                                    new_cargo[field.odoo_field_name] = replog[field.mapped_name]
                                    
                        self.create(new_cargo)
                        replog.message_post(message_type='comment', body=f"Cargo creado correctamente.")
                    
                    replog.procesado = True
                    replog.error = False
                    self.env.cr.commit()
                            
                except Exception as e:
                    _logger.info(format(e))
                    replog.error = True
                    replog.message_post(message_type='comment', body=format(e))
                    create_log.create_log(self, "ERROR", False, replog._name, replog.id, replog.descart, format(e), company_id)
                    
            else:
                replog.message_post(message_type='comment', body=f"No hay un codigo de Cargo.")
            
class ResCaracteristicas(models.Model):
    _name = 'res.caracteristicas'
    _description = 'Caracteristicas a3ERP'
    _rec_name = 'desc_carac'
    _order = 'num_carac'

    active = fields.Boolean('Active', default=True)
    cod_carac = fields.Char(string='Codigo')
    desc_carac = fields.Char(string='Descripción')
    num_carac = fields.Integer(string='Num. Carac')
    tip_carac = fields.Selection(string='Tipo', selection=[('A', 'Articulos'),('O','Organización'),('C', 'Clientes'), ('P','Proveedores')])
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    last_date_update = fields.Datetime(string='Fecha Última Actualización', help="Fecha de última actualización con los datos de a3ERP.")
    product_ids = fields.Many2many('product.template', string="Productos CANON")
    
    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        if not name:
            return super().name_search(name, args, operator, limit)

        if name:
            domain = ['|', ('cod_carac', operator, name), ('desc_carac', operator, name)]
            if args:
                domain = ['&'] + args + domain
            records = self.search_fetch(domain, ['display_name'], limit=limit)
            return [(record.id, record.display_name) for record in records.sudo()]
    
    @api.depends(lambda self: (self._rec_name,) if self._rec_name else ())
    def _compute_display_name(self):
        """Compute the value of the `display_name` field."""
        for record in self:
            record.display_name = f"{record.cod_carac}-{record.desc_carac}"
    
    def process_replogs_caractaristicas(self, repValues):
        """
        Procesar los replogs de caracteristicas.
        Args:
            repValues (List): Lista de replogs
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'caracteristicas')
        ordenados = sorted(
            [x for x in repValues if not x.error],
            key=lambda x: x.fecha, reverse=False
        )
        for replog in ordenados:
            if replog.codcar:
                try:         
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])             
                    
                    caracteristica = self.search([('cod_carac','=',replog.codcar) ,('num_carac','=',replog.numcar), ('tip_carac','=',replog.tipcar), ('active','in', (False, True)), ('company_id','=', company_id)])
                    if caracteristica and replog.movimiento in ('ALT','MOD'):
                        values_to_update = {'last_date_update': datetime.now(), 'active': True, 'company_id': replog.company_id.id}
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if field.relational_table:
                                    if 'codart_canon' in field.mapped_name:
                                        product_ids = caracteristica.product_ids.ids                                        
                                        value_id = self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id
                                        if value_id and value_id not in product_ids:
                                            values_to_update[field.odoo_field_name] = [(6,0, product_ids + [value_id])]
                                        continue
                                            
                                    value_id = self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id
                                    if value_id:
                                        values_to_update[field.odoo_field_name] = value_id 
                                else:
                                    values_to_update[field.odoo_field_name] = replog[field.mapped_name]
                                    
                        caracteristica.update(values_to_update)
                        replog.message_post(message_type='comment', body="Caracteristica actualizada correctamente.")
                        
                    elif not caracteristica and replog.movimiento in ('ALT','MOD'):
                        new_carac = {'last_date_update': datetime.now(), 'company_id': replog.company_id.id}
                        for field in required_fields:
                            if replog[field.mapped_name]:
                                if field.relational_table:
                                    if 'codart_canon' in field.mapped_name:
                                        product_ids = caracteristica.product_ids.ids                                        
                                        value_id = self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id
                                        
                                        if value_id and value_id not in product_ids:
                                            new_carac[field.odoo_field_name] = [(4, value_id)]
                                        continue
                                    
                                    value_id = self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id
                                    if value_id:
                                        new_carac[field.odoo_field_name] = value_id 
                                else:
                                    new_carac[field.odoo_field_name] = replog[field.mapped_name]
                                    
                        self.create(new_carac)
                        replog.message_post(message_type='comment', body=f"Caracteristica creado correctamente.")
                    
                    replog.procesado = True
                    replog.error = False
                    self.env.cr.commit()
                            
                except Exception as e:
                    _logger.info(format(e))
                    create_log.create_log(self, "ERROR", False, replog._name, replog.id, replog.descart, format(e), company_id)
                    replog.error = True
                    replog.message_post(message_type='comment', body=format(e))
                finally:
                    continue
                    
            else:
                replog.message_post(message_type='comment', body=f"No hay un codigo de caracteristica.")

