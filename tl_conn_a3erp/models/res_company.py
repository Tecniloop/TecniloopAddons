from odoo import fields, models, api, _
import requests
from datetime import datetime
import json, re
from .web_service import *
from . import create_log
import logging, time
import urllib3

urllib3.disable_warnings()

_logger = logging.getLogger(__name__)

URL_LOGIN = '{}/inicio/iniciarSesion'
DATOS_REQURIDOS = '{}/datosrequeridos/getrequeridos'
ESTADO_COLA = "{}/cola/getEstadoCola"

class ResCompany(models.Model):        
    _inherit = "res.company"
    
    a3erp_active_company = fields.Boolean(string='Activar sincronización a3ERP', help='Esta opcion permite activar para esta empresa la sincronización de información entre Odoo y a3ERP.')
    a3erp_canon_company = fields.Boolean(string='Activar CANON', help='Diferenciar si la empresa trabaja con CANON o no.')
    a3erp_codart_type = fields.Selection(
        string='Codigos de Articulos',
        selection=[('manual', 'Manual'), ('auto', 'Automatic')],
        help='Al dar de alta Articulos en a3ERP, permitir enviar un codigo de Articulo desde Odoo, o que se genere automaticamente.'
    )    
    a3erp_sale_order_type = fields.Selection(string='Tipo de Documento de Venta', 
                                            help='Determinamos si la empresa envia a a3ERP los documentos de Venta como Ofertas aceptadas o como Pedidos aceptados.', 
                                            selection=[('quotation', 'Ofertas'), ('orders', 'Pedidos')], 
                                            default='quotation')
    a3erp_purchase_order_type = fields.Selection(string='Tipo de Documento de Compra', 
                                        help='Determinamos si la empresa envia a a3ERP los documentos de Compra como Pedidos de Compra o como Albaranes de Compra.', 
                                        selection=[('purchase', 'Pedido'), ('picking', 'Albarán')], 
                                        default='purchase')
    a3erp_price_policy = fields.Boolean(
        string='Política de Precios: Recalcular precio unitario al modificar las unidades?', 
        help="Si esta opción esta activada, cada vez que se modifican las unidades se recalcula el precio unitario, \nen caso contrario, solo se modificara el precio unitario la primera vez que se crea la linea.",
        default=False
    )
    
    a3erp_token = fields.Text(string='Web Service Token')
    a3erp_user = fields.Char(string='Usuario')
    a3erp_password = fields.Char(string='Contraseña')    
    a3erp_url = fields.Char(string='URL WebService')    
    a3erp_company_id = fields.Integer(string='ID Empresa A3')
    
    a3erp_contact_required = fields.Boolean(string='Se requiere Contacto', default=False, help="El Cliente requiere de mínimo un Contacto para procesar un Pedido suyo Odoo -> a3ERP.")  
    
    a3erp_note_product_id = fields.Many2one(string='Producto Nota',comodel_name='product.template',ondelete='set null')
    a3erp_section_product_id = fields.Many2one(string='Producto Seccion',comodel_name='product.template', ondelete='set null')    
    a3erp_section_collapsed_product_id = fields.Many2one(string='Producto Seccion Colapsada',comodel_name='product.template', ondelete='set null')    
    
    @api.model
    def authentication_webservice(self):
        """Hace el login en el Web service para recibir el token. Se tiene que ejecutar cada 2 horas."""
        companies = self.search([('a3erp_active_company', '=', True)])
        for company in companies:
            login_model = LoginModel(company.a3erp_user, company.a3erp_password)
            try:
                response = requests.post(URL_LOGIN.format(company.a3erp_url), json=login_model.to_json(), verify=False, timeout=10)
                
                if response.status_code == 200:
                    return_message = MensajeRetorno = json.loads(response.text)
                    
                    if return_message['success']:
                        company.write({'a3erp_token':return_message['result']}) 
                        create_log.create_log(self, "INFO", False, self._name, company.id, company.name, "Login correcto")

                    else:
                        company.a3erp_token = False         
                                
                elif response.status_code == 500:
                    _logger.info(response.reason)
                    create_log.create_log(self, "ERROR", "POST", self._name, company.id, False, response.reason)
                
                else:
                    _logger.info(response.reason)
                    create_log.create_log(self, "ERROR", "POST", self._name, company.id, False, response.reason)
                       
            except Exception as e: 
                _logger.info(format(e))
                create_log.create_log(self, "ERROR", "POST", self._name, company.id, False, format(e))
    
    def get_cola_state(self, modelObject):
        """
        Consulta el estado de los registros de manera massiva mediante una accion planificada.
        También sirve para consultar el estado de los registros desde dentro de ellos.
        Args:
            modelObject (List): Lista de registros a consultar.
        """       
        for record in modelObject: 
            if not record.id_queue:
                continue
            headers = {'Authorization': f'Bearer {record.company_id.a3erp_token}','Content-Type': 'application/json'}
            cola_state = MensajeSolicitudGet(record.company_id.a3erp_company_id, [], record.id_queue)
            
            try:
                response = requests.post(ESTADO_COLA.format(record.company_id.a3erp_url), json=cola_state.to_json(), verify=False, headers=headers, timeout=10) 
                
                record.a3erp_error_simple, record.a3erp_error_extend = "", ""
                if response.status_code == 200: # CONSULTA AUTORIZADA
                    return_message = MensajeRetorno = json.loads(response.text)
                    
                    if return_message['message'] == "Sin Errores": # CONSULTA SIN ERRORES
                        message = json.loads(return_message['result'])
                        #record.queue_state = message['ESTADOPETICION']
                        dict_values = self.parse_message_return(message)
                        
                        if message['ESTADOPETICION'] == 'PENDIENTE':
                            continue
                        
                        elif message['ESTADOPETICION'] == 'FINALIZADO':
                            ## DIFERENCIAR MODELOS
                            if record._name == 'res.partner':
                                record.last_date_update = datetime.now()
                                if not record.parent_id:
                                    record.cod_cliente_a3 = dict_values.get('CODCLI')
                                    contact_list = record.env['res.partner'].search([('parent_id','=', record.id),('type','in',('contact','other')), ('company_type','=','person')]) # CUANDO RECIBIMOS EL CODCLI ENVIAMOS LOS CONTACTOS
                                    for contact in contact_list:
                                        contact.action_a3erp_syncro()
                                else:
                                    if message['TIPOPETICION'] == 'ALTA':
                                        record.cod_contacto_a3 = dict_values.get('CODIGO')
                                        record.id_contacto_relacion = dict_values.get('IDCONTACTORELACION')
                                    elif message['TIPOPETICION'] == 'ALTA_DIRENT':
                                        record.cod_dirent_a3 = dict_values.get('CODIGO')
                                    else:
                                        record.message_post(message_type='comment', body=f"Contacto y Relacion actualizados.")
                                        
                            elif record._name == 'sale.order':
                                record.ref_ofev_a3 = record.get_doc_values(dict_values.get('IDDOC'))
                            
                            elif record._name == 'purchase.order':
                                record.id_document = record.get_doc_values(dict_values.get('IDDOC')) # Guardamos el ID documento.
                                record.ref_ofev_a3 = record.get_doc_values(dict_values.get('IDDOC'))
                            
                            elif record._name == 'product.template':
                                record.last_date_update = datetime.now()
                                if message['TIPOPETICION'] == 'ALTA':
                                    record.cod_articulo_a3 = dict_values.get('CODART')      
                                    record.action_send_translt()
                                record.action_send_refpro()
                            
                            record.message_post(
                                message_type='comment',
                                body=(f"Estado Cola: {message['ESTADOPETICION']}")
                            )
                            
                        elif message['ESTADOPETICION'] == 'ERROR':
                            record.a3erp_error_simple = message['MENSAJERETORNO']
                            message['DATOSPETICION'] = json.loads(message['DATOSPETICION']) #DESERIALIZAR LOS SUBCAMPOS
                            record.a3erp_error_extend = json.dumps(message, indent=4)
                            record.message_post(message_type='comment', body=f"Estado Cola: {message['ESTADOPETICION']}")
                            create_log.create_log(record, "ERROR", False, record._name, record.id, record.name, f"Estado Cola: {message['MENSAJERETORNO']}", record.company_id.id )
                            
                        if record._name == 'sale.order' and dict_values and 'CODCLI' in dict_values:
                            record.update_partner_codcli(dict_values.get('CODCLI')) 
                        
                        record.queue_state = message['ESTADOPETICION']
                        record.id_queue = ""
                        
                    elif return_message['message'] == "Error": # CONSULTA CON ERRORES
                        record.queue_state = "ERROR"
                        record.a3erp_error_simple = return_message['result']
                        create_log.create_log(record, "WARNING", "POST", record._name, record.id, record.name, {return_message['result']}, record.company_id.id)
                    
                elif response.status_code == 401: # CONSULTA NO AUTORIZADA
                    create_log.create_log(record, "ERROR", "GET", False, False, record.name, "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.")
                    record.a3erp_error_simple = "Unauthorized: Usuario o Contraseña erroneos o Token Expirado."
                     
                elif response.status_code == 400: # CONSULTA CON ERRORES DE ENVIO
                    message = json.loads(response.text)['errors']
                    error_key = next((key for key in message.keys() if key != 'mensaje'), None)
                    record.a3erp_error_extend = message[error_key][0]
                    create_log.create_log(record, "ERROR", "GET", record._name, record.id, record.name, {message[error_key][0]}, record.company_id.id)
                else:
                    message = response.reason
                    record.a3erp_error_extend = message
                    create_log.create_log(record, "ERROR", "GET", record._name, record.id, record.name, message, record.company_id.id)
                    _logger.info(format(message))
                        
            except Exception as e: 
                _logger.info(format(e))
                create_log.create_log(record, "ERROR", "GET", record._name, record.id, record.name, format(e), record.company_id.id)
                record.a3erp_error_extend = format(e)
            
            finally:
                self.env.cr.commit()
    
    def module_is_installed(self, module_name):
        """Comprovar si el modulo esta instalado
        Args:
            module_name (String): Nombre del modulo
        Returns:
            Boolean: True o False
        """
        module = self.env['ir.module.module'].search([('name', '=', module_name)])
        if not module or module.state != 'installed': 
            return False
        else:
            return True
    
    def parse_message_return(self, message):
        """Transformar el mensaje de la cola en valores usables.
        Args:
            message (dict): Mensaje de la cola.
        Returns:
            dict: Devuelve un diccionario de valores.
        """
        mensaje_retorno = message.get('MENSAJERETORNO')
        if mensaje_retorno:
            if ';' in mensaje_retorno:
                resultados = {}
                partes = mensaje_retorno.split(';')
                for parte in partes:
                    if ':' in parte:  
                        clave, valor = map(str.strip, parte.split(':', 1))  # Dividir solo en el primer ':'
                        resultados[clave] = valor
                return resultados
            else:
                if ':' in mensaje_retorno:
                    clave, valor = map(str.strip, mensaje_retorno.split(':', 1))
                    return {clave: valor}
                else:
                    # Si no hay ':' tratar como un valor único sin clave específica
                    return {'IDDOC': mensaje_retorno}
                
    def get_field_translations(self,field,record):
        """Devuelve el literal del campo traducido segun el contexto actual.
        Args:
            field (String): Campo
            record (Object): Registro
        Returns:
            String: Valor
        """
        value = record._fields[field].get_description(record.env)
        if value['string']:
            return value['string']        
        return False