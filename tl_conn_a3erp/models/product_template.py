from odoo.exceptions import MissingError, UserError, ValidationError
from odoo import fields,models,api, _
from .web_service import *
from .mapper_campos import TypeMapper, LangMapper
from . import create_log
import logging, json, re, requests, base64
from datetime import datetime, timedelta, date
from lxml import etree
import time

_logger = logging.getLogger(__name__)

NAX_PRODUCTOS = "{}/articulo/nax"
GETBYCODE_ARTICULOS = "{}/articulo/getbycode"
GETBYCODE_IDIOMAS = "{}/idiomas/getbycodart"
NAX_IDIOMAS = "{}/articulo/addidioma"
NAX_REFERENCIAS = "{}/referencias/nax"
GETBYCODE_STOCK = "{}/stockact/getstockbycodart"
GETBYCODE_STOCKRESERVA = "{}/stockact/getallstockreserva"
GETALL_STOCK = "{}/stockact/getallstockbycodalm"
MAPPER = TypeMapper()
LANGMAPPER = LangMapper()
DESCRIPTION_RENOVACION = """**--RENOVACIO: Servei de garantia i/o manteniment inclòs durant {} mesos o si ja existeix un manteniment, s´afageix a la data d´aquest. Després d´aquest període: {}. Preu unitari estimatiu de: {}€"""

class ProductProduct(models.Model):
    _inherit = ['product.product']       
        
    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        """Añadir CODART de a3ERP para buscar productos en las lineas."""
        args = args or []
        if not name:
            return super().name_search(name, args, operator, limit)

        if name:
            domain = ['|', '|' , '|' , ('name', operator, name), ('default_code', operator, name), ('barcode', operator, name), ('cod_articulo_a3', operator, name)]
            if args:
                domain = ['&'] + args + domain
            records = self.search_fetch(domain, ['display_name'], limit=limit)
            return [(record.id, record.display_name) for record in records.sudo()]
        
    def get_product_detail_stock(self):
        return self.product_tmpl_id.get_product_detail_stock()

    def get_a3erp_product_data(self):
        return self.product_tmpl_id.get_a3erp_product_data()
    
    def action_send_a3erp(self):
        return self.product_tmpl_id.action_send_a3erp()
    
    def get_product_multiline_description_sale(self):
        """Computar descripción del articulo en la linea para poder enviar a a3ERP."""
        name = self.name
        if self.description_sale and not self.default_code:
            name += '\n' + self.name + '\n' + self.description_sale            
        elif self.description_sale:
            name += '\n' + self.description_sale
        elif self and not self.default_code:
            name += '\n' + self.name
            
        return name
    
class ProductTemplate(models.Model):
    _inherit = ['product.template']       
    
    a3erp_active_company = fields.Boolean(
        related="company_id.a3erp_active_company",
        readonly=True,
    )    
    company_id = fields.Many2one(comodel_name='res.company', default=lambda self: self.env.company)
    cod_articulo_a3 = fields.Char(string='Cod.Articulo A3', readonly=False,copy=False, size=15)
    last_date_update = fields.Datetime(string='Fecha Última Actualización', readonly=False, help="Fecha de última actualización con los datos de a3ERP.",copy=False)
    a3erp_error_simple = fields.Text(string='Error',copy=False)
    a3erp_error_extend = fields.Text(string='Error Extenso',copy=False)
    json_content_send = fields.Text(string='Contenido del Json enviado', readonly=True,copy=False)
    id_queue = fields.Char(string='ID Cola',copy=False)
    queue_state = fields.Selection(string='Estado traspaso Cola', selection=[('PENDIENTE', 'PENDIENTE'), ('ERROR', 'INCIDENCIA'), ('FINALIZADO', 'FINALIZADO')], help="Estado de la peticion en la cola de creacion de la NAX.", track_visibility='onchange',copy=False)
    a3erp_product_stock = fields.Integer(string='Stock real en a3ERP.', default=0,copy=False)
    a3erp_product_margin = fields.Float(string='Margen en Ventas %', copy=False)    
    
    # CARACTERISTICAS
    carac1_id = fields.Many2one(string='Carac.1',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',1),('tip_carac','=','A')])
    carac2_id = fields.Many2one(string='Carac.2',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',2),('tip_carac','=','A')])
    carac3_id = fields.Many2one(string='Carac.3',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',3),('tip_carac','=','A')])
    carac4_id = fields.Many2one(string='Carac.4',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',4),('tip_carac','=','A')])
    carac5_id = fields.Many2one(string='Carac.5',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',5),('tip_carac','=','A')])
    carac6_id = fields.Many2one(string='Carac.6',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',6),('tip_carac','=','A')])
    carac7_id = fields.Many2one(string='Carac.7',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',7),('tip_carac','=','A')])
    carac8_id = fields.Many2one(string='Carac.8',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',8),('tip_carac','=','A')])
    carac9_id = fields.Many2one(string='Carac.9',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',9),('tip_carac','=','A')])
    carac10_id = fields.Many2one(string='Carac.10',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',10),('tip_carac','=','A')]) 

    pending_a3erp = fields.Boolean(
        string="Pendiente de enviar a a3ERP",
        compute="_compute_pending_a3erp",
        store=True,
        index=True,
    )
    
    @api.depends('write_date', 'last_date_update')
    def _compute_pending_a3erp(self):
        for rec in self:
            if not rec.last_date_update:
                rec.pending_a3erp = True
            else:
                rec.pending_a3erp = rec.write_date > rec.last_date_update
    
    def _log_and_continue(self, record, message):
        """Publica un mensaje y continúa."""
        record.message_post(message_type='comment', body=message)
    
    def action_send_translt(self):
        """Enviar traducciones en caso que tengan. Solo se envia Descripción y Nombre"""
        for record in self:
            headers = {'Authorization': f'Bearer {record.company_id.a3erp_token}','Content-Type': 'application/json'}
            response = False
            idiomas_activados = self.env['res.lang'].search([('active', '=', True)])
            
            for lang in idiomas_activados:
                traducciones = []
                try:
                    field = self._fields["name"]
                    translations = field._get_stored_translations(self)
                    if translations.get(lang.code):
                        traducciones.append(Parametro('DESCART', translations[lang.code], 'STRING'))
                    else:
                        self._log_and_continue(record, f"Traducciones: No hay traducción en {lang.code} para el campo {field.string}")
                        continue
                        traducciones.append(Parametro('DESCART', '', 'STRING'))
                        
                    field = self._fields["description_sale"]
                    translations = field._get_stored_translations(self)
                    if translations.get(lang.code):
                        traducciones.append(Parametro('TEXTO', translations[lang.code], 'STRING'))
                    else:
                        self._log_and_continue(record, f"Traducciones: No hay traducción en {lang.code} para el campo {field.string}")
                        continue                    
                        traducciones.append(Parametro('TEXTO', '', 'STRING'))

                    traducciones.append(Parametro('CODIDIOMA', LANGMAPPER.traducir(lang.code, "odoo"), "STRING"))
                    traducciones.append(Parametro('CODART', cuadrar(record.cod_articulo_a3, 15), "STRING"))
                    
                    post_referencias = MensajeSolicitudPost(record.company_id.a3erp_company_id, "ALTA", ENTIDADIDIOMAS, traducciones)
                    response = requests.post(NAX_IDIOMAS.format(record.company_id.a3erp_url), json=post_referencias.to_json(), verify=False, headers=headers, timeout=10)
                    
                    if response.status_code == 200:  # CONSULTA SIN ERRORES
                        return_message = MensajeRetorno = json.loads(response.text)
                        if return_message['message'] == "Sin Errores": # ACTUALIZAR CAMPOS SI EL MENSAJE ES SIN ERRORES
                            self._log_and_continue(record,f"Traducciones enviadas: {post_referencias.to_json()}")
                        elif return_message['message'] == "Error":
                            #record.a3erp_error_simple = return_message['result']
                            record.a3erp_error_extend = f"{return_message['result']} \n {post_referencias.to_json()}"
                            self._log_and_continue(record, f"Error al procesar la Traduccion {LANGMAPPER.traducir(lang.code, 'odoo')}: {return_message['result']}")

                    elif response.status_code == 400:
                        return_message = json.loads(response.text)['errors']
                        error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
                        record.a3erp_error_extend = return_message[error_key][0]
                        create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, return_message[error_key][0], record.company_id.id)

                    elif response.status_code == 401:
                        create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.", record.company_id.id)
                        record.a3erp_error_extend = "Unauthorized: Usuario o Contraseña erroneos o Token Expirado."
                    
                except Exception as e:
                    _logger.error(format(e))
                    create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, format(e), record.company_id.id)
                    record.a3erp_error_extend = format(e)
                finally:
                    continue            
            
    def action_send_refpro(self):
        """Enviar todas las referencias de proveedor."""
        for record in self:
            headers = {'Authorization': f'Bearer {record.company_id.a3erp_token}','Content-Type': 'application/json'}
            referencias_proveed = [] # GUARDAR LAS REFERENCIAS DE PROVEEDOR CON EL PROVEEDOR
            empty_mandatory_fields = [] # GUARDAR LOS CAMPOS DE ODOO QUE SON OBLIGATORIOS PASAR Y ESTAN VACIOS
            response = False
            ref_proveed_fields = self.env['a3erp.campos'].search([('table_name', '=', 'refpro'), ('field_use', 'in', ('odoo-a3erp', False)), ('company_id', 'in', (False, record.company_id.id))])
            if not ref_proveed_fields:
                create_log.create_log(record, "ERROR", "POST", record._name, False, False, "No hay campos de Referencias de Productos, revisar.", record.company_id.id)
                continue

            for ref in record.seller_ids: #AÑADIR REFERENCIAS DE PROVEEDOR COMO LINEAS
                referencias_proveed = []
                try:  
                    for field in ref_proveed_fields:
                        if ref[field.odoo_field_name]:
                            if field.relational_table:
                                campo_a3 = MAPPER.traducir_campo(ref[field.odoo_field_name]._fields[field.table_code].type)  # MAPPEAR EL TIPO DEL CAMPO
                                referencias_proveed.append(Parametro(field.a3erp_field_name, ref[field.odoo_field_name][field.table_code], campo_a3))    
                            else:
                                campo_a3 = MAPPER.traducir_campo(ref._fields[field.odoo_field_name].type)  # MAPPEAR EL TIPO DEL CAMPO
                                referencias_proveed.append(Parametro(field.a3erp_field_name, ref[field.odoo_field_name], campo_a3))
                        elif not ref[field.odoo_field_name] and field.mandatory_field:
                            empty_mandatory_fields.append(ref.company_id.get_field_translations(field.odoo_field_name,ref))

                    if empty_mandatory_fields:
                        fields = ', '.join(empty_mandatory_fields)
                        self._log_and_continue(record,f"Referencias: campos requeridos y estan vacíos: '{fields}'")
                        create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, f"Referencias: campos requeridos y estan vacíos: '{fields}'", record.company_id.id)
                        continue

                    referencias_proveed.append(Parametro('CODPRO', cuadrar(ref.partner_id.cod_proveed_a3), "STRING"))
                    referencias_proveed.append(Parametro('CODART', cuadrar(record.cod_articulo_a3, 15), "STRING"))

                    post_referencias = MensajeSolicitudPost(record.company_id.a3erp_company_id, "ALTA", ENTIDADREFERENCIAS, referencias_proveed)
                    response = requests.post(NAX_REFERENCIAS.format(record.company_id.a3erp_url), json=post_referencias.to_json(), verify=False, headers=headers, timeout=10)

                    record.a3erp_error_simple, record.a3erp_error_extend = "", ""
                    if response.status_code == 200:  # CONSULTA SIN ERRORES
                        return_message = MensajeRetorno = json.loads(response.text)
                        if return_message['message'] == "Sin Errores": # ACTUALIZAR CAMPOS SI EL MENSAJE ES SIN ERRORES
                            self._log_and_continue(record,f"Referencia de Proveedor enviada: {post_referencias.to_json()}")
                        elif return_message['message'] == "Error":
                            # record.queue_state = "ERROR"
                            record.a3erp_error_simple = return_message['result']
                            record.a3erp_error_extend = post_referencias.to_json()
                            self._log_and_continue(record,f"Error enviando Referencia de Proveedor {post_referencias.to_json()}: {return_message['result']}")

                    elif response.status_code == 400:
                        return_message = json.loads(response.text)['errors']
                        error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
                        record.a3erp_error_extend = return_message[error_key][0]
                        create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, return_message[error_key][0], record.company_id.id)

                    elif response.status_code == 401:
                        create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.", record.company_id.id)
                        record.a3erp_error_extend = "Unauthorized: Usuario o Contraseña erroneos o Token Expirado."

                except Exception as e:
                    _logger.error(format(e))
                    create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, format(e), record.company_id.id)
                    record.a3erp_error_extend = format(e)
                    self._log_and_continue(record, f"No se ha podido enviar la Referencia de Proveedor {ref.partner_id.name}: {format(e)}")
                finally:
                    continue

    def action_send_a3erp(self):
        """Enviar Producto para crear en a3ERP."""
        for record in self:
            headers = {'Authorization': f'Bearer {record.company_id.a3erp_token}','Content-Type': 'application/json'}
            list_parametros = [] # GUARDAR LOS VALORES QUE PASAMOS A a3ERP
            empty_mandatory_fields = [] # GUARDAR LOS CAMPOS DE ODOO QUE SON OBLIGATORIOS PASAR Y ESTAN VACIOS
            fields = False
            response = requests.post
            try:
                required_fields = self.env['a3erp.campos'].search([('table_name', '=', 'productos'), ('field_use', 'in', ('odoo-a3erp', False)), ('company_id', 'in', (False, record.company_id.id))])
                if not required_fields: # VALIDAR SI HAY ALGUN CAMPO ENTRADO EN LA VISTA DE CAMPOS
                    create_log.create_log(record, "ERROR", "POST", record._name, False, False, "No hay campos de Productos informados, revisar.", record.company_id.id)
                    return True
                    continue
                else:
                    for field in required_fields:
                        if field.odoo_field_name: # SI NO TIENE CAMPO DE ODOO, TIENE VALOR POR DEFECTO
                            if record[field.odoo_field_name]:
                                campo_a3 = MAPPER.traducir_campo(record._fields[field.odoo_field_name].type)  # MAPPEAR EL TIPO DEL CAMPO
                                
                                if 'DECIMAL' in campo_a3:
                                    list_parametros.append(Parametro(field.a3erp_field_name, str(record[field.odoo_field_name]).replace('.',','), campo_a3))
                                    continue
                                
                                if field.relational_table:
                                    if 'CODPRO' in field.a3erp_field_name:
                                        seller_id = record.seller_ids[0] if record.seller_ids else None
                                        if seller_id:
                                            value_id = seller_id.partner_id[field.table_code]
                                            list_parametros.append(Parametro(field.a3erp_field_name, cuadrar(value_id), "STRING"))
                                        continue
                                    list_parametros.append(Parametro(field.a3erp_field_name, record[field.odoo_field_name][field.table_code], campo_a3))
                                else:
                                    if 'IMAGEN' in field.a3erp_field_name:
                                        imagen = base64.b64decode(record[field.odoo_field_name]).hex()
                                        list_parametros.append(Parametro(field.a3erp_field_name, imagen, "STRING"))
                                    else:
                                        if 'AFESTOCK' in field.a3erp_field_name:
                                            list_parametros.append(Parametro(field.a3erp_field_name, 'T' if record[field.odoo_field_name] == 'consu' else 'F', campo_a3))
                                            continue
                                        list_parametros.append(Parametro(field.a3erp_field_name, record[field.odoo_field_name], campo_a3))
                            elif 'HAYNUMSERIE' in field.a3erp_field_name:
                                list_parametros.append(Parametro(field.a3erp_field_name, record[field.odoo_field_name], "BOOLEAN"))
                            elif not record[field.odoo_field_name] and field.mandatory_field:
                                empty_mandatory_fields.append(record.company_id.get_field_translations(field.odoo_field_name,record))

                        elif field.default_value:
                            default, campo_a3 = field.default_value.split('|',1)
                            list_parametros.append(Parametro(field.a3erp_field_name, default, campo_a3))                    

                    # CODART MANUAL 
                    if record.company_id.a3erp_codart_type == 'manual' and record.cod_articulo_a3:
                        list_parametros.append(Parametro('CODART', cuadrar(record.cod_articulo_a3, 15), "STRING"))                    

                    if empty_mandatory_fields:
                        context_value = self.env.context.get('create_from_sale')
                        fields = ', '.join(empty_mandatory_fields)
                        self._log_and_continue(record,f"Los siguientes campos son requeridos y estan vacíos: '{fields}'")
                        if not context_value:
                            create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, f"Los siguientes campos son requeridos y estan vacíos: '{fields}'")
                            raise ValidationError(_(f"Los siguientes campos son requeridos y estan vacíos: '{fields}'"))
                            continue                        
                        record.env.cr.commit()
                        return True
                    else:    
                        post_producto = MensajeSolicitudPost(record.company_id.a3erp_company_id, "ALTA", ENTIDADARTICULOS, list_parametros)
                        response = requests.post(NAX_PRODUCTOS.format(record.company_id.a3erp_url), json=post_producto.to_json(), verify=False, headers=headers, timeout=10)

                record.a3erp_error_simple, record.a3erp_error_extend, record.json_content_send = "", "", json_list_to_json_dump(post_producto.to_json())
                if response.status_code == 200:  # CONSULTA SIN ERRORES
                    return_message = MensajeRetorno = json.loads(response.text)
                    if return_message['message'] == "Sin Errores": # ACTUALIZAR CAMPOS SI EL MENSAJE ES SIN ERRORES
                        record.id_queue = return_message['result']
                        record.queue_state = "PENDIENTE"
                        self._log_and_continue(record, f"Respuesta a3ERP: {return_message['message']}")
                    elif return_message['message'] == "Error":
                        record.queue_state = "ERROR"
                        record.a3erp_error_simple = return_message['result']
                        create_log.create_log(record, "WARNING", "POST", record._name, record.id, record.name, return_message['result'], record.company_id.id)

                elif response.status_code == 400:
                    return_message = json.loads(response.text)['errors']
                    error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
                    record.a3erp_error_extend = return_message[error_key][0]
                    create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, return_message[error_key][0], record.company_id.id)

                elif response.status_code == 401:
                    record.queue_state = "ERROR"
                    create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.", record.company_id.id)
                    record.a3erp_error_extend = "Unauthorized: Usuario o Contraseña erroneos o Token Expirado."

            except Exception as e:
                _logger.error(format(e))
                create_log.create_log(record, "ERROR", "POST", record._name, record.id, record.name, format(e), record.company_id.id)
                record.a3erp_error_extend = format(e)
                self._log_and_continue(record,format(e))
                if not self.env.context.get('create_from_sale') and fields:
                    raise ValidationError(_(f"Los siguientes campos son requeridos y estan vacíos: '{fields}'"))

    def action_update_a3erp(self):
        """Actualizar artículo existente en a3ERP"""
        for record in self:
            if not record.cod_articulo_a3:
                continue

            headers = {
                'Authorization': f'Bearer {record.company_id.a3erp_token}',
                'Content-Type': 'application/json'
            }

            list_parametros = []
            empty_mandatory_fields = []
            response = requests.post

            try:
                required_fields = self.env['a3erp.campos'].search([
                    ('table_name', '=', 'productos'),
                    ('field_use', 'in', ('odoo-a3erp', False)),
                    ('company_id', 'in', (False, record.company_id.id))
                ])

                if not required_fields:
                    create_log.create_log(
                        record, "ERROR", "POST", record._name,
                        False, False,
                        "No hay campos de Productos informados, revisar.",
                        record.company_id.id
                    )
                    continue

                for field in required_fields:
                    if field.odoo_field_name:
                        if record[field.odoo_field_name]:
                            campo_a3 = MAPPER.traducir_campo(
                                record._fields[field.odoo_field_name].type
                            )

                            if 'DECIMAL' in campo_a3:
                                list_parametros.append(
                                    Parametro(
                                        field.a3erp_field_name,
                                        str(record[field.odoo_field_name]).replace('.', ','),
                                        campo_a3
                                    )
                                )
                                continue

                            if field.relational_table:
                                if 'CODPRO' in field.a3erp_field_name:
                                    seller = record.seller_ids[:1]
                                    if seller:
                                        value_id = seller.partner_id[field.table_code]
                                        list_parametros.append(
                                            Parametro(field.a3erp_field_name, cuadrar(value_id), "STRING")
                                        )
                                    continue

                                list_parametros.append(
                                    Parametro(
                                        field.a3erp_field_name,
                                        record[field.odoo_field_name][field.table_code],
                                        campo_a3
                                    )
                                )
                            else:
                                if 'IMAGEN' in field.a3erp_field_name:
                                    imagen = base64.b64decode(record[field.odoo_field_name]).hex()
                                    list_parametros.append(
                                        Parametro(field.a3erp_field_name, imagen, "STRING")
                                    )
                                elif 'AFESTOCK' in field.a3erp_field_name:
                                    list_parametros.append(
                                        Parametro(
                                            field.a3erp_field_name,
                                            'T' if record[field.odoo_field_name] == 'consu' else 'F',
                                            campo_a3
                                        )
                                    )
                                else:
                                    list_parametros.append(
                                        Parametro(
                                            field.a3erp_field_name,
                                            record[field.odoo_field_name],
                                            campo_a3
                                        )
                                    )

                        elif field.mandatory_field:
                            empty_mandatory_fields.append(
                                record.company_id.get_field_translations(
                                    field.odoo_field_name, record
                                )
                            )

                    elif field.default_value:
                        default, campo_a3 = field.default_value.split('|', 1)
                        list_parametros.append(
                            Parametro(field.a3erp_field_name, default, campo_a3)
                        )

                """if empty_mandatory_fields:
                    fields = ', '.join(empty_mandatory_fields)
                    self._log_and_continue(
                        record,
                        f"Campos obligatorios sin informar: {fields}"
                    )
                    continue"""

                list_parametros.append(
                    Parametro("CODART", cuadrar(record.cod_articulo_a3, 15), "STRING")
                )

                post_producto = MensajeSolicitudPost(
                    record.company_id.a3erp_company_id,
                    "MODIFICAR",
                    ENTIDADARTICULOS,
                    list_parametros
                )

                response = requests.post(
                    NAX_PRODUCTOS.format(record.company_id.a3erp_url),
                    json=post_producto.to_json(),
                    verify=False,
                    headers=headers,
                    timeout=10
                )

                record.json_content_send = json_list_to_json_dump(
                    post_producto.to_json()
                )
                record.a3erp_error_simple = ""
                record.a3erp_error_extend = ""

                if response.status_code == 200:
                    result = json.loads(response.text)
                    if result.get('message') == "Sin Errores":
                        record.queue_state = "PENDIENTE"
                        record.id_queue = result.get('result')
                        self._log_and_continue(record, f"Poducto enviado para actualizar. \nRespuesta a3ERP: {result['message']}")
                    else:
                        record.queue_state = "ERROR"
                        record.a3erp_error_simple = result.get('result')

                elif response.status_code == 400:
                    error = json.loads(response.text)['errors']
                    key = next((k for k in error if k != 'mensaje'), None)
                    record.a3erp_error_extend = error[key][0]

                elif response.status_code == 401:
                    record.a3erp_error_extend = "Unauthorized: Usuario o Contraseña erroneos o Token Expirado."

            except Exception as e:
                _logger.exception(e)
                record.a3erp_error_extend = str(e)
                self._log_and_continue(record, str(e))

    def get_cola_state(self):
        self.company_id.get_cola_state(self)

    def get_a3erp_product_translations(self):
        tabla,url,key = None, None, None
        tabla = 'idioma'
        url = GETBYCODE_IDIOMAS
        key = self.cod_articulo_a3

        if tabla and url and key:
            notType,msg = None,None
            responses, requiredFields = self.env['a3erp.replogs'].get_a3erp_record_data(tabla, url, self.company_id, cuadrar(key,15))
            for response in responses:
                """NOMBRE PRODUCTO"""
                field = self._fields["name"]
                translations = field._get_stored_translations(self)
                if translations:
                    lang_code = LANGMAPPER.traducir(response["CODIDIOMA"], "a3erp")
                    translations[lang_code] = response["DESCART"] if response["DESCART"] else ''
                    
                    # SI NO VIENE NOMBRE EN CASTELLANO PONER EN CATALAN
                    if lang_code == "es_ES" and not response["DESCART"]:
                        translations["es_ES"] = translations.get("ca_ES", "")
                else:
                    translations = {LANGMAPPER.traducir(response["CODIDIOMA"], "a3erp") : response["DESCART"] if response["DESCART"] else ''}
                
                self.env.cache.update_raw(
                    self, field, [translations], dirty=True
                )
                self.modified(["name"])
            
                """DESCRIPCION PRODUCTO"""
                if 'description_sale_as_note' in self._fields:
                    value = 'description_sale_as_note'
                    field = self._fields["description_sale_as_note"]
                else:
                    value = 'description_sale'
                    field = self._fields["description_sale"]
                    
                translations = field._get_stored_translations(self)
                if translations:
                    lang_code = LANGMAPPER.traducir(response["CODIDIOMA"], "a3erp")
                    translations[lang_code] = response["TEXTO"] if response["TEXTO"] else ''
                    
                    # SI NO VIENE TEXTO EN CASTELLANO PONER EN CATALAN
                    if lang_code == "es_ES" and not response["TEXTO"]:
                        translations["es_ES"] = translations.get("ca_CA", "")
                else:
                    translations = {LANGMAPPER.traducir(response["CODIDIOMA"], "a3erp") : response["TEXTO"] if response["TEXTO"] else ''}
                
                self.env.cache.update_raw(
                    self, field, [translations], dirty=True
                )
                self.modified([value])            
            
    def get_a3erp_product_data(self):
        """Actualizar directamente el Producto con los datos de a3ERP.
        Returns:
            Notification: Notificacion con mensaje final. 
        """
        tabla,url,key = None, None, None
        if self.cod_articulo_a3:
            tabla = 'productos'
            url = GETBYCODE_ARTICULOS
            key = self.cod_articulo_a3

        if tabla and url and key:
            notType,msg = None,None
            response, requiredFields = self.env['a3erp.replogs'].get_a3erp_record_data(tabla, url, self.company_id, cuadrar(key,15))
            if isinstance(response[0], dict):
                response = response[0]
                values_to_update = {"last_date_update": datetime.now()}
                requiredFields = [obj for obj in requiredFields if obj.a3erp_field_name not in ('CENTROCOSTEC','CENTROCOSTEC2','CENTROCOSTEC3')]
                values_to_update = self.prepare_values_to_update_product(
                    requiredFields,
                    self.company_id.id,
                    a3erp_dict=response,
                    values_to_update=values_to_update,
                )
                record_active = response.get('OBSOLETO') 
                if record_active == 'T':
                    values_to_update['active'] = False
                elif record_active == 'F':
                    values_to_update['active'] = True
                                        
                try:
                    self.sudo().with_context(dict(values_from_a3=True)).write(values_to_update)
                    self.sudo().get_a3erp_product_translations()
                    if response.get('CENTROCOSTEC'):
                        analytic_vals = {
                            'analitica_1': response.get('CENTROCOSTEC'),
                            'analitica_2': response.get('CENTROCOSTEC2'),
                            'analitica_3': response.get('CENTROCOSTEC3'),
                        }
                        self.env['account.analytic.distribution.model'].sudo().process_product_analytic_account(self, analytic_vals, self.company_id.id)
                    msg = 'Registro actualizado'
                    notType = 'success'
                    self.env.cr.commit()
                except Exception as e:
                    _logger.info(format(e))
                    create_log.create_log(self, "ERROR", False, self._name, self.id, self.name, format(e), self.company_id.id)   
                    self.a3erp_error_extend = format(e)
                    msg = f'{format(e)}'
                    notType = 'danger'
            else:
                self.a3erp_error_extend = response
                msg = response
                notType = 'warning'
                    
            notification = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Alerta'),
                    'type': notType,
                    'message': msg,
                    #'sticky': True,
                }
            }
            return notification
        
    def get_product_margin(self, default_code, codart=False):
        """Recupera el margen del producto según la referencia interna."""
        product_template = self.env['product.template'].search([('default_code', '=', default_code)], limit=1)
        if not product_template and codart:
            product_template = self.env['product.template'].search([('cod_articulo_a3', '=', codart)], limit=1)
             
        margin = 0.0
        if product_template:
            margin = product_template.a3erp_product_margin           
            
        return margin
    
    def cron_sync_a3erp_products(self):
        """
        Cron diario para sincronizar productos creados/modificados
        en las últimas 12h y pendientes de enviar a a3ERP.
        """

        limit_date = fields.Datetime.now() - timedelta(hours=12)

        domain = [
            '&',
                '|',
                    ('write_date', '>=', limit_date),
                    ('create_date', '>=', limit_date),
                ('pending_a3erp', '=', True)
        ]

        batch_size = 500

        while True:
            products = self.search(domain, limit=batch_size)
            if not products:
                break

            _logger.info("a3ERP CRON: Procesando %s productos", len(products))

            for product in products:
                try:
                    if product.cod_articulo_a3:
                        product.action_update_a3erp()
                    else:
                        product.action_send_a3erp()

                except Exception as e:
                    _logger.error(
                        "a3ERP CRON ERROR: Producto %s - %s",
                        product.default_code or product.name,
                        str(e)
                    )

            self.env.cr.commit() 
        
    def prepare_values_to_update_product(self, required_fields, company_id, replog=False, a3erp_dict=False, values_to_update=False):
        """Actualiza el diccionario de valores 'values_to_update' con los campos de Odoo correspondientes
        basados en los datos del 'RepLogs' y, en su defecto, usando 'a3erp_dict' si actualizamos desde la ficha del registro.

        :param required_fields: Lista de objetos con la definición de los campos requeridos.
        :param company_id: ID de la compañía para búsquedas relacionadas.
        :param replog: Replog con los datos nuevos.
        :param a3erp_dict: Diccionario adicional con datos de a3ERP (usado si 'replog' no tiene valores).
        :param values_to_update: Diccionario con los valores a actualizar en el producto de Odoo.
        :return: Diccionario 'values_to_update' actualizado.
        """ 
        
        for field in required_fields:
            if not a3erp_dict and field.default_value:
                default = field.default_value.split('|',1)
                values_to_update[field.odoo_field_name] = default[0]
                continue
            
            replog_value = replog[field.mapped_name] if replog else None
            
            if replog_value:
                if field.relational_table:
                    if 'carac' in field.odoo_field_name:
                        value_id = self.get_caracteristica(field.table_code, field.relational_table, field.a3erp_field_name, replog[field.mapped_name], company_id)
                        values_to_update[field.odoo_field_name] = value_id or ''
                        continue
                    else:
                        value_id = self.resolve_field_values(field,replog)
                        if value_id:
                            if 'TIPIVA' in field.a3erp_field_name and value_id: # EN CASO DE PASAR EL IVA
                                values_to_update[field.odoo_field_name] = [(5, ), (4, value_id)] # ELIMINAR LOS REGISTROS ACTUALES, Y AÑADIR EL NUEVO
                            else:
                                values_to_update[field.odoo_field_name] = value_id 
                else:
                    if 'IMAGEN' in field.a3erp_field_name:
                        values_to_update[field.odoo_field_name] = replog[field.mapped_name].encode('latin-1')
                    elif 'AFESTOCK' in field.a3erp_field_name:
                        values_to_update[field.odoo_field_name] = 'consu' if replog[field.mapped_name] == 'T' else 'service'
                    elif 'HAYNUMSERIE' in field.a3erp_field_name: 
                        values_to_update[field.odoo_field_name] = True if replog[field.mapped_name] == 'T' else False
                    else: 
                        values_to_update[field.odoo_field_name] = replog[field.mapped_name]                
                    
            # Si no hay valor en replog, pero hay a3erp_dict, buscar en a3erp_dict
            elif a3erp_dict and field.a3erp_field_name in a3erp_dict:
                a3erp_value = a3erp_dict[field.a3erp_field_name]

                if a3erp_value:
                    if field.relational_table:
                        if 'carac' in field.odoo_field_name:
                            value_id = self.get_caracteristica(field.table_code, field.relational_table, field.a3erp_field_name, a3erp_value, company_id)
                            values_to_update[field.odoo_field_name] = value_id or ''
                            continue
                        else:
                            value_id = self.resolve_field_values(field, a3erp_value, is_dict=True, company=company_id)
                            if value_id:
                                if 'TIPIVA' in field.a3erp_field_name and value_id: # EN CASO DE PASAR EL IVA
                                    values_to_update[field.odoo_field_name] = [(5, ), (4, value_id)] # ELIMINAR LOS REGISTROS ACTUALES, Y AÑADIR EL NUEVO
                                else:
                                    values_to_update[field.odoo_field_name] = value_id 
                    else:
                        if 'IMAGEN' in field.a3erp_field_name:
                            values_to_update[field.odoo_field_name] = a3erp_value.encode('latin-1')
                        elif 'AFESTOCK' in field.a3erp_field_name:
                            values_to_update[field.odoo_field_name] = 'consu' if a3erp_value == 'T' else 'service'
                        elif 'HAYNUMSERIE' in field.a3erp_field_name: 
                            values_to_update[field.odoo_field_name] = True if a3erp_value == 'T' else False
                        else: 
                            values_to_update[field.odoo_field_name] = a3erp_value.strip() if field.a3erp_field_name == 'CODART' else a3erp_value
                #CONTROL PARA LOS PRECIOS, PUEDE QUE LLEGUEN A 0
                elif 'PRC' in field.a3erp_field_name:
                    values_to_update[field.odoo_field_name] = a3erp_value
                    
        # /!\ SOLO PARA APEN: ARTICULO RENOVACION /!\
        if self.env.company.name in 'Apen':    
            if (a3erp_dict and a3erp_dict.get('APEN_CODARTCONT')) or (replog and replog.apen_codartcont):
                """Solo entra si hay valores en 'a3erp_dict' o en 'replog' y el campo en concreto que es 'APEN_CODARTCONT' o 'apen_codartcont' 
                tiene un valor, de otra manera se limpia el campo ya que se entiende que no tiene mantenimento.
                """
                values_to_update['descripcion_pedido'] = self.env.company.product_renovate_description
            else:
                values_to_update['descripcion_pedido'] = False
                values_to_update['articulo_mantenimiento_id'] = False
                values_to_update['meses_primera_facturacion'] = False
        
        return values_to_update
        
    def processs_replogs_refpro(self, repValues):
        """
        Procesar los RepLogs de referencias de proveedor. 
        Args:
            repValues (List): RepLogs de referencias. 
        """
        required_fields = self.env['a3erp.campos'].search([('table_name','=','refpro'), ('field_use', 'in', ('a3erp-odoo', False)), ('company_id', 'in', (False, self.company_id.id))])
        if not required_fields: # CAMPOS REQUERIDOS
            create_log.create_log(self, "ERROR", False, self._name, False, False, "No hay campos obligatorios informados para REFERENCIAS PROVEEDOR, revisar.") 
        else:
            for replog in repValues.sorted(lambda x: x.fecha and x.error == False, reverse=False):
                if replog.codart:
                    company_id = replog.company_id.id if replog.company_id else None
                    error = ""

                    product = self.search([('cod_articulo_a3', '=', replog.codart),('active','in', (False, True)), ('company_id','=', company_id)]) # PRODUCTO
                    if not product:
                        error = "Producto no encontrado"
                        self._log_and_continue(replog, f"El producto con codigo {replog.codart} no existe.")
                        replog.error = True                    

                    partner_id = self.env['res.partner'].search([('cod_proveed_a3', '=', replog.codpro), ('company_id','=', company_id)]) # PROVEEDOR DEL PRODUCTO 
                    if not partner_id:
                        error = "Proveedor no encontrado"
                        self._log_and_continue(replog, f"No se ha encontrado el proveedor con codigo {partner_id.cod_proveed_a3}.")
                        replog.error = True                   

                    try:
                        if not error:
                            if len(product) < 2:
                                product_supplier = product.seller_ids.filtered(lambda x: x.partner_id.cod_proveed_a3 == replog.codpro)
                                values_to_update = {}
                                if product_supplier and replog.movimiento in ('ALT','MOD'): # MODIFICAR REGISTRO EXISTENTE
                                    for field in required_fields:
                                        if field.relational_table:
                                            value_id = self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id
                                            values_to_update[field.odoo_field_name] = value_id
                                        else:
                                            values_to_update[field.odoo_field_name] = replog[field.mapped_name]

                                    product.write({'seller_ids': [(1, product_supplier.id, values_to_update)]})                                    

                                elif not product_supplier and replog.movimiento in ('ALT','MOD'): # CREAR NUEVA ENTRADA
                                    for field in required_fields:
                                        if field.relational_table:
                                            value_id = self.env[field.relational_table].search([(field.table_code, '=', replog[field.mapped_name])]).id
                                            values_to_update[field.odoo_field_name] = value_id
                                        else:
                                            values_to_update[field.odoo_field_name] = replog[field.mapped_name]

                                    product.write({
                                        'seller_ids': [(0,0, values_to_update)]
                                    })

                                elif product_supplier and replog.movimiento == 'BOR':
                                    product_supplier.unlink()    

                                replog.procesado = True
                                replog.error = False
                                self.env.cr.commit()
                                self._log_and_continue(replog, f"Registro procesado.")

                            else:                
                                self._log_and_continue(replog, f"El producto esta repetido.")
                                replog.error = True
                        else:
                            self._log_and_continue(replog, f"{error}")
                            replog.error = True

                    except Exception as e:
                        _logger.error(format(e))
                        replog.error = True
                        self._log_and_continue(replog, format(e))
                        create_log.create_log(self, "ERROR", False, self._name, replog.id, replog.descart, format(e)) 
                else:
                    self._log_and_continue(replog, f"No hay un codigo de producto.")

    def process_replogs_productos(self, repValues):
        """ Metodo para procesar los replogs de productos. 
        Args:
            repValues (List): Lista de replogs a procesar. 
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'productos')
        if not required_fields_by_company: # CAMPOS REQUERIDOS
            create_log.create_log(self, "ERROR", False, self._name, False, "No hay campos requeridos para Productos.") 
        else:
            ordenados = sorted(
                [x for x in repValues if not x.error],
                key=lambda x: x.fecha, reverse = False
            )
            for replog in ordenados:
                new_prod = {}
                if replog.codart:
                    company_id = replog.company_id.id if replog.company_id else None
                    required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                    required_fields = [obj for obj in required_fields if obj.a3erp_field_name not in ('CENTROCOSTEC','CENTROCOSTEC2','CENTROCOSTEC3')]
                    product = self.search([('cod_articulo_a3', '=', replog.codart),('active','in', (False, True)), ('company_id','=', company_id)])
                    try:  
                        if replog.descart:          
                            if len(product) < 2: #CONTROLAR SI HAY MAS DE UN PRODUCTO CON ESTE CODART               
                                if product and replog.movimiento == 'BOR' or replog.obsoleto == 'T': # PRODUCTO BORRADO EN A3 O OBSOLETO
                                    product.last_date_update = datetime.now()
                                    product.active = False

                                elif product and replog.movimiento in ('ALT','MOD'): # PRODUCTO EXISTENTE MODIFICADO O CREADO DE NUEVO EN A3
                                    values_to_update = {
                                        'last_date_update': datetime.now(), 
                                        'active': True, 
                                        'company_id': company_id, 
                                        "queue_state": "FINALIZADO"
                                    }
                                    values_to_update = self.prepare_values_to_update_product(
                                        required_fields,
                                        company_id,
                                        replog=replog,
                                        values_to_update=values_to_update
                                    )
                                            
                                    product.update(values_to_update)
                                    self._log_and_continue(replog, "Producto actualizado correctamente.")

                                elif not product and replog.movimiento in ('ALT','MOD'): # PRODUCTO NUEVO EN A3 Y EN ODOO
                                    new_prod = {
                                        'last_date_update': datetime.now(), 
                                        'cod_articulo_a3': replog.codart, 
                                        'company_id': replog.company_id.id, 
                                        "queue_state": "FINALIZADO"
                                    }                            
                                    for field in required_fields:
                                        if field.default_value:
                                            default = field.default_value.split('|',1)
                                            new_prod[field.odoo_field_name] = default[0]
                                            continue
                                        
                                        if replog[field.mapped_name]:
                                            if field.relational_table:
                                                if 'carac' in field.odoo_field_name:
                                                    value_id = self.get_caracteristica(field.table_code, field.relational_table, field.a3erp_field_name, replog[field.mapped_name], company_id)
                                                    new_prod[field.odoo_field_name] = value_id or ''
                                                    continue
                                                value_id = self.resolve_field_values(field,replog)

                                                if value_id:
                                                    if 'TIPIVA' in field.a3erp_field_name: # EN CASO DE PASAR EL IVA
                                                        new_prod[field.odoo_field_name] = [(4, value_id)] # ELIMINAR LOS REGISTROS ACTUALES, Y AÑADIR EL NUEVO
                                                    else:
                                                        new_prod[field.odoo_field_name] = value_id
                                            else:
                                                if 'IMAGEN' in field.a3erp_field_name:
                                                    new_prod[field.odoo_field_name] = replog[field.mapped_name].encode('latin-1')
                                                elif 'AFESTOCK' in field.a3erp_field_name:
                                                    new_prod[field.odoo_field_name] = 'consu' if replog[field.mapped_name] == 'T' else 'service'
                                                else: 
                                                    new_prod[field.odoo_field_name] = replog[field.mapped_name]
                                                    
                                        # /!\ SOLO PARA APEN: ARTICULO RENOVACION /!\
                                        if 'APEN_CODARTCONT' in field.a3erp_field_name and replog[field.mapped_name]:
                                            new_prod['descripcion_pedido'] = self.env.company.product_renovate_description
                                            #values_to_update['descripcion_pedido'] = DESCRIPTION_RENOVACION
                                            
                                    try:
                                        product = self.create(new_prod)
                                        self._log_and_continue(replog, f"Producto creado correctamente.")
                                    except Exception as e:
                                        _logger.info(format(e))
                                        self._log_and_continue(replog, format(e))
                                        continue
                                    
                                replog.procesado = True
                                replog.error = False
                                self.env.cr.commit()
                                # PROCESAR LOS IDIOMAS DESPUES DE LOS PRODUCTOS
                                self.process_replogs_idioma(product=product)
                            else:           
                                self._log_and_continue(replog, f"El codigo de Producto {replog.codart} esta duplicado. Revisar")    
                                replog.error = True
                        else:
                            self._log_and_continue(replog, f"El Producto no tiene un nombre.")    
                            replog.error = True

                    except Exception as e:
                        _logger.info(format(e))
                        create_log.create_log(self, "ERROR", False, replog._name, replog.id, replog.descart, format(e), company_id) 
                        replog.error = True
                        self._log_and_continue(replog, format(e))
                    finally:
                        continue
                else:
                    self._log_and_continue(replog, f"No hay un codigo de producto.")
    
    def process_replogs_alarmas(self, repValues):
        """
            Procesar solo los replogs de Alarmas de Productos.
        Args:
            repValues (List): Lista de RepLogs.
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'alarmas')
        if not required_fields_by_company:
            create_log.create_log(self, "ERROR", False, self._name, False, "No hay campos de Alarmas informados.")
        else:
            filtered_replogs = [replog for replog in repValues if replog.codartv]
            sorted_filtered_replogs = sorted(filtered_replogs, key=lambda x: x.fecha and x.error == False, reverse=False)
            for replog in sorted_filtered_replogs:

                company_id = replog.company_id.id or None
                required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                try:
                    product_id = self.get_product_by_cod_a3(replog.codartv, company_id)
                    if product_id and replog.movimiento in ('ALT', 'MOD'):                 
                        values_to_update = {
                            "last_date_update": datetime.now(),
                            'sale_line_warn': 'warning',
                            'sale_line_warn_msg': replog.alarmaofe                           
                        }
                        product_id.update(values_to_update)

                        replog.procesado = True
                        replog.error = False
                        self.env.cr.commit()
                    elif not product_id:
                        self._log_and_continue(replog, f"El Producto {replog.codartv} no existe.")    
                        replog.error = True
                    else:
                        continue
                except Exception as e:
                    _logger.info(format(e))
                    replog.error = True
                    self._log_and_continue(replog, format(e))    
                    create_log.create_log(self, "ERROR", False, self._name, replog.id, replog.nomcli, format(e), company_id)
                    continue

    def process_opcionales(self, values):
        """Procesar los productos opcionales para cada producto que tenga esa caracteristica 2.
        Args:
            values (List): Lista de valores.
        """
        categ = False
        products_categ = self.env['product.template']
        ordenados = sorted(
            [x for x in values if not x.error],
            key=lambda x: x.cod_categoria
        )
        for record in ordenados:
            company_id = record.company_id.id if record.company_id else None
            try:
                if categ != record.cod_categoria:
                    categ = record.cod_categoria    
                    products_categ = self.search([('carac2_id.cod_carac','=', categ)])
                
                if products_categ and record.cod_art_opcional:
                    product_template = self.get_product_by_cod_a3(record.cod_art_opcional,company_id).id
                    for product in products_categ:
                        optionals_ids = product.optional_product_ids.ids
                        if product_template not in optionals_ids:
                            product.update({'optional_product_ids': [(6,0, optionals_ids + [product_template])]})
                        
                else:
                    self._log_and_continue(record, f"No se ha encontrado ningún producto con la Caracteristica 2: {categ}")
                
                record.error = False
                record.procesado = True
                self.env.cr.commit()
                
            except Exception as e:
                _logger.info(format(e))
                create_log.create_log(self, "ERROR", False, record._name, record.id, record.cod_categoria, format(e), company_id) 
                record.error = True
                self._log_and_continue(record, format(e))
            finally:
                continue
        
    # LAS TRADUCCIONES SE PROCESAN CON LOS PRODUCTOS DESPUES DE CREAR O ACTUALIZAR
    def process_replogs_idioma(self, product=False, repLogs=False):
        """Procesar las traducciones de los nombres y descripciones de productos.
        Args:
            product (Object): Producto objetivo.
        """
        replogs = repLogs or self.env['a3erp.idioma'].search([('codart', '=' , product.cod_articulo_a3),('procesado', '=', False)])
        ordenados = sorted(
            [x for x in replogs if not x.error],
            key=lambda x: x.fecha, reverse = False
        )
        for replog in ordenados:
            try:
                if replog.movimiento in ("ALT", "MOD"):  # IDIOMA MODIFICADO
                    if not product:
                        company_id = replog.company_id.id if replog.company_id else None
                        product = self.get_product_by_cod_a3(replog.codart, company_id)
                        if not product:
                            self._log_and_continue(replog, f"Producto con CODART {replog.codart} no encontrado.")
                            continue
                        
                    """NOMBRE PRODUCTO"""
                    field = product._fields["name"]
                    translations = field._get_stored_translations(product)
                    if translations:
                        translations[LANGMAPPER.traducir(replog["codidioma"], "a3erp")] = replog["descart"] if replog["descart"] else ''
                    else:
                        translations = {LANGMAPPER.traducir(replog["codidioma"], "a3erp") : replog["descart"] if replog["descart"] else ''}

                    product.env.cache.update_raw(
                        product, field, [translations], dirty=True
                    )
                    product.modified(["name"])
                    """DESCRIPCION PRODUCTO"""
                    if 'description_sale_as_note' in product._fields:
                        value = 'description_sale_as_note'
                        field = product._fields["description_sale_as_note"]
                    else:
                        value = 'description_sale'
                        field = product._fields["description_sale"]
                        
                    translations = field._get_stored_translations(product)
                    if translations:
                        translations[LANGMAPPER.traducir(replog["codidioma"], "a3erp")] = replog["texto"] if replog["texto"] else ''
                    else:
                        translations = {LANGMAPPER.traducir(replog["codidioma"], "a3erp") : replog["texto"] if replog["texto"] else ''}

                    product.env.cache.update_raw(
                        product, field, [translations], dirty=True
                    )
                    product.modified([value])

                    self.env.cr.commit()
                    self._log_and_continue(replog, "Producto actualizado correctamente.")
                    replog.procesado = True
                    replog.error = False
                elif replog.movimiento == "BOR":  # IDIOMA BORRADO
                    replog.unlink()
                    self.env.cr.commit()
            except Exception as e:
                _logger.info(format(e))
                create_log.create_log(self,"ERROR",False, replog._name, replog.id, replog.descart,format(e), replog.company_id.id)
                self._log_and_continue(replog, format(e))
                replog.error = True

    def resolve_field_values(self, field, replog, is_dict=False, company=False):
        """Metodo para añadir condiciones especiales de los campos.
        Args:
            field (Object): Registro del Mappeado.
            replog (Object): Registro del replogs.
        Returns:
            String: Devuelve el valor buscado
        """
        code = replog if is_dict else replog[field.mapped_name]
        company_id = company if is_dict else replog.company_id.id
        if 'company_id' in self.env[field.relational_table]._fields:
            return self.env[field.relational_table].search([(field.table_code, '=', code.strip()), ('company_id','=', company_id)]).id
        else:
            return self.env[field.relational_table].search([(field.table_code, '=', code.strip())]).id                

    @api.model
    def get_product_by_cod_a3(self, cod_articulo, company):
        return self.search([('cod_articulo_a3','=',cod_articulo),('company_id','=', company)], limit=1)

    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        """Añadir CODART de a3ERP para buscar productos en las lineas."""
        args = args or []
        if not name:
            return super().name_search(name, args, operator, limit)

        if name:
            domain = ['|', '|' , '|' , ('name', operator, name), ('default_code', operator, name), ('barcode', operator, name), ('cod_articulo_a3', operator, name)]
            if args:
                domain = ['&'] + args + domain
            records = self.search_fetch(domain, ['display_name'], limit=limit)
            return [(record.id, record.display_name) for record in records.sudo()]

    def get_caracteristica(self, table_code, modelo, a3_field, valor, company_id):
        """Buscar y devolver la caracteristica correspondientes.
        Args:
            table_code (String): Codigo de busqueda en la tabla de.
            modelo (String): Modelo de busqueda.
            a3_field (String): Nombre del campo.
            valor (String): Codigo de caracteristica.
        Returns:
            Int: Caracteristica encontrada.
        """
        match = re.match(r"CAR(\d+)(_ORG)?", a3_field)
        if match:
            # El grupo 1 contiene el número
            num_carac = int(match.group(1)) 

        carac_id = self.env[modelo].search([('num_carac','=',num_carac),('tip_carac','=','A'),(table_code,'=', valor.strip()), ('company_id','=', company_id)]).id        
        return carac_id or False  

    def write(self, values):
        result = super(ProductTemplate, self).write(values)
        for record in self:
            if not record.a3erp_active_company:
                return result
            ctx = self.env.context.get('values_from_a3')
            if ctx or self.env.user.id == self.env.ref('base.user_root').id or self.env.user.has_group('tl_conn_a3erp.group_a3erp'):
                return result
            if (
                "cod_articulo_a3" in values
                or "queue_state" in values
                or "a3erp_error_simple" in values
                or "a3erp_error_extend" in values
                or "last_date_update" in values
                or "id_queue" in values
                or "optional_product_ids" in values
                or "a3erp_product_stock" in values
            ):
                return result

            if record.queue_state in ("PENDIENTE"):
                raise ValidationError("No se puede modificar el Producto. Esta en cola de creción.")
            else:
                return result
    
    def copy(self, default=None):
        default = dict(default or {})
        
        return super(ProductTemplate, self).copy(default)
    
    @api.constrains('carac2_id')
    def _check_carac2_id(self):
        """Actualizar productos opcionales segun los que ya tienen esa misma caracteristica.
        """
        for record in self:
            if not record.a3erp_active_company:
                return
            if record.carac2_id:
                related_products = self.env['product.template'].search([
                    ('carac2_id.id', '=', record.carac2_id.id),
                    ('id', '!=', record.id) 
                ])
                
                optional_products = related_products.mapped('optional_product_ids')
                if optional_products and record.optional_product_ids.ids != optional_products.ids:
                    record.optional_product_ids = [(6, 0, optional_products.ids)]
    
    @api.constrains('cod_articulo_a3')
    def _check_cod_articulo_a3(self):
        for record in self:
            if not record.default_code and record.cod_articulo_a3:
                record.default_code = record.cod_articulo_a3
    
    # METODOS STOCK
    def get_all_product_stock(self):
        """Recoger todos los Productos que tienen un STOCK superior a 0 en a3ERP. Antes de actualizar el valor, poner a 0 el campo en todos los Productos."""
        
        companies = self.env['res.company'].search([('a3erp_active_company', '=', True)])
        for company in companies:
            headers = {'Authorization': f'Bearer {company.a3erp_token}','Content-Type': 'application/json'}
        
            cola_state = MensajeSolicitudGet(company.a3erp_company_id, [], "",[])        
            response = requests.get(GETALL_STOCK.format(company.a3erp_url), json=cola_state.to_json(), verify=False, headers=headers, timeout=10)        
            if response.status_code == 200:
                return_message = MensajeRetorno = json.loads(response.text)
                
                if return_message['message'] == "Sin Errores":
                    lista_logs = return_message['result']
                
                    query = f"UPDATE product_template SET a3erp_product_stock = 0 WHERE company_id = {company.id};"
                    self.env.cr.execute(query)
                    
                    none_products = self.update_product_stock(lista_logs, company.id)
                    if none_products:
                        lista = ', '.join(f"{x}" for x in none_products)
                        create_log.create_log(self, "WARNING", "GET", self, False, "STOCK", f"Los siguientes Articulos no se han encontrado a la hora de actualizar el Stock: {lista}", company.id)
                    
                elif return_message['message'] == "Error":
                    create_log.create_log(self, "WARNING", "GET", self, False, "STOCK", f"{return_message['result']}", company.id)
                    
            elif response.status_code == 401: # CONSULTA NO AUTORIZADA
                create_log.create_log(self, "ERROR", "GET", self._name, False, "STOCK", "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.")
                
            elif response.status_code == 400: # CONSULTA CON ERRORES DE ENVIO
                return_message = json.loads(response.text)['errors']
                error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
                create_log.create_log(self, "ERROR", "GET", self, False, "STOCK", return_message[error_key][0], company.id)
                
            else:
                create_log.create_log(self, "ERROR", "GET", self, False, "STOCK", response.reason, company.id)
        
    def update_product_stock(self, stockList, company_id):
        """Actualizar el campo de STOCK para todos los productos que esten en la lista.
        Args:
            stockList (List): Lista de registros.
            company_id (Integer): Id de la compañia.
        Returns:
            List: Lista de productos no procesados.
        """
        none_products = []
        products = 0
        for record in stockList:
            product = self.get_product_by_cod_a3(record.get('codart').strip(),company_id)
            if product:
                product.update({'a3erp_product_stock': record.get('stock')})
                products +=1 
            else:
                none_products.append(record.get('codart').strip())        
        
        create_log.create_log(self, "INFO", "GET", self, False, "STOCK", f"STOCK de productos actualizados: {products}", company_id)
        
        return none_products
    
    def get_product_detail_stock(self):
        """Consultar el stock DETALLADO del Articulo directamente a a3ERP."""
        
        headers = {'Authorization': f'Bearer {self.company_id.a3erp_token}','Content-Type': 'application/json'}
        if self.cod_articulo_a3:
            cola_state = MensajeSolicitudGet(self.company_id.a3erp_company_id, [], cuadrar(self.cod_articulo_a3, 15),[])        
        else:
            raise UserError('El producto no tiene un CODART asignado.')
        
        try:
            response = requests.get(GETBYCODE_STOCKRESERVA.format(self.company_id.a3erp_url), json=cola_state.to_json(), verify=False, headers=headers, timeout=10)        
            if response.status_code == 200: # CONSULTA SIN ERRORES
                return_message = MensajeRetorno = json.loads(response.text)  
                        
                if return_message['message'] == "Sin Errores":
                    if return_message['result']:
                        record = return_message['result'][0]
                        
                        warehouse_description = self._detailed_warehouse_description(return_message['result'])
                        
                        record['UnidadesStock'] = sum(d['UnidadesStock'] for d in return_message['result'])                        
                        
                        self.update({'a3erp_product_stock': record.get('UnidadesStock')})
                        forecast_stock = record.get('UnidadesStock') + ((record.get('compras') or 0) - (record.get('ventas') or 0))
                        
                        value = self.env['product.stock.wizard'].sudo().create({
                            'real_stock' : record.get('UnidadesStock'),
                            'sold_units' : record.get('ventas'),
                            'date_next_sale' : datetime.strptime(record.get('Prox_Ven'),'%Y-%m-%dT%H:%M:%S') if record.get('Prox_Ven') else False,
                            'purchase_units' : record.get('compras'),
                            'date_next_purchase' : datetime.strptime(record.get('Prox_Com'),'%Y-%m-%dT%H:%M:%S') if record.get('Prox_Com') else False,
                            'forecast_stock' : forecast_stock,
                            'description': warehouse_description
                        })
                
                        return {
                            'type': 'ir.actions.act_window',
                            'name': f'Stock real del Producto: {self.name}',
                            'res_model': 'product.stock.wizard',
                            'view_mode': 'form',
                            'target': 'new',
                            'res_id': value.id
                        }
                    else:
                        raise UserError('Este producto no tiene registros entrados en STOCK.') 
                    
                elif return_message['message'] == "Error":
                    create_log.create_log(self, "WARNING", "POST" ,self._name, False, False, return_message['result'], self.company_id.id)
                
            elif response.status_code == 404: # CONSULTA NO AUTORIZADA
                raise UserError('Producto no encontrado.') 
            
            elif response.status_code == 401: # CONSULTA NO AUTORIZADA
                create_log.create_log(self, "ERROR", "GET", self._name, False, False, "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.")
                
            elif response.status_code == 400: # CONSULTA CON ERRORES DE ENVIO
                return_message = json.loads(response.text)['errors']
                error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
                create_log.create_log(self, "ERROR", "GET" ,self._name, False, False, return_message[error_key][0], self.company_id.id)
        
        except Exception as e:
            raise UserError(format(e))
        
    def _detailed_warehouse_description(self, stock_list):
        """Devolver una descripcion detallada del stock por almacenes para el campo HTML."""
        description = ""
        for warehouse in stock_list:
            description += f"""
                <div style='border-bottom:1px solid #ccc; padding:4px 0;'>
                    <b>Almacén:</b> 
                    <span style='display:inline-block;width:300px;'>{warehouse.get('Descalm')}</span> 
                    <b>Cantidad disponible:</b> {warehouse.get('UnidadesStock')}
                </div>
            """

        return description
            