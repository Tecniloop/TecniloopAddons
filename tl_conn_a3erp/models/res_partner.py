from odoo.exceptions import MissingError, UserError, ValidationError
from odoo import fields, models, api, _
from .web_service import *
from .mapper_campos import TypeMapper, LangMapper
from . import create_log
import requests,json,logging, re
from datetime import datetime, timedelta
import inspect

_logger = logging.getLogger(__name__)

NAX_CLIENTES = "{}/clientes/nax"
GETBYCODE_CLIENTES = "{}/clientes/getbycode"
NAX_CONTACTOS = "{}/contactos/nax"
GETBYCODE_CONTACTOS = "{}/contactos/getbycode"
GETBYCODE_PROVEEDORES = "{}/proveedores/getbycode"
GETNUM_DIRENT = "{}/dirent/getnextnumdir"
GETBYCODE_DIRENT = "{}/dirent/getbycode"
GET_SITUACIONRIESGO = "{}/clientes/getSituacionRiesgo"
NAX_DIRENT = "{}/dirent/nax"
ESTADO_COLA = "{}/cola/getEstadoCola"
MAPPER = TypeMapper()
LANGMAPPER = LangMapper()

campos_ignorados = {
    "cod_cliente_a3",
    "queue_state",
    "a3erp_error_simple",
    "a3erp_error_extend",
    "last_date_update",
    "id_queue",
    "child_ids",
    "lang",
}

class ResPartner(models.Model):
    _inherit = ['res.partner']

    contacto_sin_cliente_notificado = fields.Boolean(default = False) # BORRAR A LA V18
    a3erp_active_company = fields.Boolean(
        related="company_id.a3erp_active_company",
        readonly=True,
    )
    company_id = fields.Many2one(comodel_name='res.company', default=lambda self: self.env.company)
    cod_cliente_a3 = fields.Char(string='Cod. Cliente a3ERP',copy=False)
    cod_proveed_a3 = fields.Char(string='Cod.Proveedor a3ERP',copy=False)
    cod_contacto_a3 = fields.Char(string='Id. Contacto a3ERP',copy=False)
    tipo_entidad_contacto = fields.Char(string='Tipo Entidad del Contacto',copy=False)
    id_contacto_relacion = fields.Char(string='Id Relacion',copy=False)    
    cod_dirent_a3 = fields.Char(string='Cod.Dirección Entrega a3ERP',copy=False)

    last_date_update = fields.Datetime(string='Fecha Última Actualización', help="Fecha de última actualización con los datos de a3ERP.",copy=False)
    a3erp_error_simple = fields.Text(string='Error',copy=False)
    a3erp_error_extend = fields.Text(string='Error Extenso',copy=False)
    json_content_send = fields.Text(string='Contenido del Json enviado', readonly=True,copy=False)
    id_queue = fields.Char(string='ID Cola',copy=False)
    queue_state = fields.Selection(string='Estado traspaso Cola', selection=[('PENDIENTE', 'PENDIENTE'), ('ERROR', 'INCIDENCIA'), ('FINALIZADO', 'FINALIZADO')], help="Estado de la peticion en la cola de creacion de la NAX.", track_visibility='onchange',copy=False)

    cod_tarifa_a3 = fields.Char(string='Cod. Tarifa a3ERP', default=None,copy=False)
    # OBSOLETOS
    cod_fam_desc = fields.Char('Cod. Familia Desc. a3ERP', copy=False)
    pricelist_desc_fam_id = fields.Many2one(string='Tarifa Familia Desc. a3ERP', comodel_name='product.pricelist', ondelete='set null', domain="[('a3erp_pricelist_type', '=', 'descuentos_fam')]",copy=False)

    cargo_id = fields.Many2one(string='Cargo',comodel_name='res.cargos',ondelete='set null', track_visibility='onchange')
    send_email = fields.Boolean(string='Permitir Publicidad', default=False, copy=False, help='Permitir recibir publicidad por email. Alimentado con el valor de a3ERP.')
    
    # CARACTERISTICAS
    carac1_id = fields.Many2one(string='Carac. 1',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',1),('tip_carac','=','C')])
    carac2_id = fields.Many2one(string='Carac. 2',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',2),('tip_carac','=','C')])
    carac3_id = fields.Many2one(string='Carac. 3',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',3),('tip_carac','=','C')])
    carac4_id = fields.Many2one(string='Carac. 4',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',4),('tip_carac','=','C')])
    carac5_id = fields.Many2one(string='Carac. 5',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',5),('tip_carac','=','C')])
    carac6_id = fields.Many2one(string='Carac. 6',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',6),('tip_carac','=','C')])
    carac7_id = fields.Many2one(string='Carac. 7',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',7),('tip_carac','=','C')])
    carac8_id = fields.Many2one(string='Carac. 8',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',8),('tip_carac','=','C')])
    carac9_id = fields.Many2one(string='Carac. 9',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',9),('tip_carac','=','C')])
    carac10_id = fields.Many2one(string='Carac. 10',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',10),('tip_carac','=','C')]) 

    carac1_org_id = fields.Many2one(string='Carac. Org. 1',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',1),('tip_carac','=','O')])
    carac2_org_id = fields.Many2one(string='Carac. Org. 2',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',2),('tip_carac','=','O')])
    carac3_org_id = fields.Many2one(string='Carac. Org. 3',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',3),('tip_carac','=','O')])
    carac4_org_id = fields.Many2one(string='Carac. Org. 4',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',4),('tip_carac','=','O')])
    carac5_org_id = fields.Many2one(string='Carac. Org. 5',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',5),('tip_carac','=','O')])
    carac6_org_id = fields.Many2one(string='Carac. Org. 6',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',6),('tip_carac','=','O')])
    carac7_org_id = fields.Many2one(string='Carac. Org. 7',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',7),('tip_carac','=','O')])
    carac8_org_id = fields.Many2one(string='Carac. Org. 8',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',8),('tip_carac','=','O')])
    carac9_org_id = fields.Many2one(string='Carac. Org. 9',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',9),('tip_carac','=','O')])
    carac10_org_id = fields.Many2one(string='Carac. Org. 10',comodel_name='res.caracteristicas',ondelete='set null', domain=[('num_carac','=',10),('tip_carac','=','O')]) 
    
    def _compute_display_name(self):
        """Compute just the display name of the delivery partner."""
        for record in self:
            if record.type == 'delivery':
                record.display_name = f"{record.name}, {record.contact_address_complete}"
            else:
                super(ResPartner, record)._compute_display_name()
    
    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        if not name:
            return super().name_search(name, args, operator, limit)

        if name:
            domain = ["|","|","|","|","|","|",
                ("complete_name", operator,name),
                ("name", operator, name),
                ("comercial", operator, name),
                ("vat", operator, name),
                ("email", operator, name),
                ("phone", operator, name),
                ("cod_cliente_a3", "=", name)]
            
            if args:
                domain = ['&'] + args + domain
            records = self.search_fetch(domain, ['display_name'], limit=limit)
            return [(record.id, record.display_name) for record in records.sudo()]
    
    def check_contacts(self):
        """Comprueba si el cliente tiene al menos un Contacto creado."""
        if not self.child_ids.filtered(lambda x: x.type in ('contact','other')):
            return False
        return True
    
    def create_list_to_send(self):
        """Crea una lista de campos/valores del Cliente para enviar con la oferta y crear en a3erp.
        Returns:
            List: Lista de Campos o False
        """
        list_parametros = [] # GUARDAR LOS VALORES QUE PASAMOS A a3ERP
        empty_mandatory_fields = [] # GUARDAR LOS CAMPOS DE ODOO QUE SON OBLIGATORIOS PASAR Y ESTAN VACIOS
        #required_fields = self.env['a3erp.campos'].search([('table_name', '=', 'clientes'), ('field_use', 'in', ('odoo-a3erp', False)),('company_id', 'in', (False, self.company_id.id))])
        required_fields = self.env['a3erp.campos'].get_required_values_send(self.company_id.id, 'clientes')
        # VALIDAR SI HAY ALGUN CAMPO ENTRADO EN LA VISTA DE CAMPOS
        if not required_fields:
            create_log.create_log(self, "ERROR", "POST", self._name, False, False, "No hay campos de CLIENTES informados, revisar.", self.company_id.id)

        for field in required_fields:
            if field.odoo_field_name: # SI NO TIENE CAMPO DE ODOO, TIENE VALOR POR DEFECTO
                if self[field.odoo_field_name]:
                    campo_a3 = MAPPER.traducir_campo(self._fields[field.odoo_field_name].type)  # MAPPEAR EL TIPO DEL CAMPO
                    if field.relational_table:
                        if 'CODIDIOMA' in field.a3erp_field_name:
                            list_parametros.append(Parametro(field.a3erp_field_name, LANGMAPPER.traducir(self[field.odoo_field_name]), campo_a3))
                        else:
                            list_parametros.append(Parametro(field.a3erp_field_name, self[field.odoo_field_name][field.table_code], campo_a3))
                    else:
                        if 'APEN_EXENTOCANON' in field.a3erp_field_name:
                            list_parametros.append(Parametro(field.a3erp_field_name, 'N' if self[field.odoo_field_name] else 'S', 'STRING'))
                        else:
                            list_parametros.append(Parametro(field.a3erp_field_name, self[field.odoo_field_name], campo_a3))
                elif not self[field.odoo_field_name] and field.mandatory_field:
                    empty_mandatory_fields.append(self.company_id.get_field_translations(field.odoo_field_name,self))

            elif field.default_value:
                default, campo_a3 = field.default_value.split('|',1)
                list_parametros.append(Parametro(field.a3erp_field_name, default, campo_a3))   

        if empty_mandatory_fields:
            fields = ', '.join(empty_mandatory_fields)
            self.message_post(message_type='comment', body=f"Los siguientes campos son requeridos y estan vacíos: '{fields}'")
            create_log.create_log(self, "ERROR", "POST", self._name, self.id, self.name, f"Los siguientes campos son requeridos y estan vacíos: '{fields}'", self.company_id.id)
        else:
            return list_parametros
        
        self.env.cr.commit()
        return False

    def action_a3erp_syncro(self):
        """Envia el Cliente/Contacto a la cola del Web Service para ser procesado y creado."""
        headers = {'Authorization': f'Bearer {self.company_id.a3erp_token}','Content-Type': 'application/json'}
        list_parametros = [] # GUARDAR LOS VALORES QUE PASAMOS A a3ERP
        empty_mandatory_fields = [] # GUARDAR LOS CAMPOS DE ODOO QUE SON OBLIGATORIOS PASAR Y ESTAN VACIOS
        response = requests.post
        try:
            # /!\ DIFERENCIAMOS CLIENTES DE CONTACTOS
            if self.company_type == 'company':  # CLIENTES
                if self.company_id.a3erp_contact_required and not self.check_contacts():
                    msg = f"Tiene que haber almenos 1 Contacto para poder dar de alta en a3ERP."
                    self.message_post(message_type='comment', body=msg)
                    raise ValidationError(msg)

                #required_fields = self.env['a3erp.campos'].search([('table_name', '=', 'clientes'), ('field_use', 'in', ('odoo-a3erp', False)), ('company_id', 'in', (False, self.company_id.id))])
                required_fields = self.env['a3erp.campos'].get_required_values_send(self.company_id.id, 'clientes')
                # VALIDAR SI HAY ALGUN CAMPO ENTRADO EN LA VISTA DE CAMPOS
                if not required_fields:
                    create_log.create_log(self, "ERROR", "POST", self._name, False, False, "No hay campos de CLIENTES informados, revisar.", self.company_id.id)
                    return

                for field in required_fields:
                    if field.odoo_field_name: # SI NO TIENE CAMPO DE ODOO, TIENE VALOR POR DEFECTO
                        if self[field.odoo_field_name]:
                            campo_a3 = MAPPER.traducir_campo(self._fields[field.odoo_field_name].type)  # MAPPEAR EL TIPO DEL CAMPO
                            if field.relational_table:
                                if 'CODIDIOMA' in field.a3erp_field_name:
                                    list_parametros.append(Parametro(field.a3erp_field_name, LANGMAPPER.traducir(self[field.odoo_field_name]), campo_a3))
                                else:
                                    list_parametros.append(Parametro(field.a3erp_field_name, self[field.odoo_field_name][field.table_code], campo_a3))
                            else:
                                if 'APEN_EXENTOCANON' in field.a3erp_field_name:
                                    list_parametros.append(Parametro(field.a3erp_field_name, 'N' if self[field.odoo_field_name] else 'S', 'STRING'))
                                else:
                                    if field.odoo_field_name in ('phone','mobile'):
                                        list_parametros.append(Parametro(field.a3erp_field_name, self[field.odoo_field_name].replace(" ", ""), campo_a3))
                                    else:
                                        list_parametros.append(Parametro(field.a3erp_field_name, self[field.odoo_field_name], campo_a3))
                        elif not self[field.odoo_field_name] and field.mandatory_field:
                            empty_mandatory_fields.append(self.company_id.get_field_translations(field.odoo_field_name,self))

                    elif field.default_value:
                        default, campo_a3 = field.default_value.split('|',1)
                        list_parametros.append(Parametro(field.a3erp_field_name, default, campo_a3))   

                if empty_mandatory_fields:
                    fields = ', '.join(empty_mandatory_fields)
                    msg = f"Los siguientes campos son requeridos y estan vacíos: '{fields}'"
                    self.message_post(message_type='comment', body=msg)
                    create_log.create_log(self, "ERROR", "POST", self._name, self.id, self.name, msg)
                    return msg
                else:    
                    post_cliente = MensajeSolicitudPost(self.company_id.a3erp_company_id, "ALTA", ENTIDADCLIENTES, list_parametros)
                    response = requests.post(NAX_CLIENTES.format(self.company_id.a3erp_url), json=post_cliente.to_json(), verify=False, headers=headers, timeout=10)
                    self.json_content_send = json_list_to_json_dump(post_cliente.to_json())
            else:  # CONTACTOS 
                """Se pueden modificar o crear"""
                if self.parent_id.cod_cliente_a3:
                    #required_fields = self.env['a3erp.campos'].search([('table_name', '=', 'contactos'), ('field_use', 'in', ('odoo-a3erp', False)), ('company_id', 'in', (False, self.company_id.id))])
                    required_fields = self.env['a3erp.campos'].get_required_values_send(self.company_id.id, 'contactos')
                    if not required_fields:
                        create_log.create_log(self, "ERROR", "POST", self._name, False, False, "No hay campos obligatorios para CONTACTOS informados, revisar.", self.company_id.id)
                        return

                    for field in required_fields:
                        if field.odoo_field_name: # SI NO TIENE CAMPO DE ODOO, TIENE VALOR POR DEFECTO
                            if self[field.odoo_field_name]:
                                campo_a3 = MAPPER.traducir_campo(self._fields[field.odoo_field_name].type)  # MAPPEAR EL TIPO DEL CAMPO
                                if field.relational_table:
                                    if 'CODIDIOMA' in field.a3erp_field_name:
                                        list_parametros.append(Parametro(field.a3erp_field_name, LANGMAPPER.traducir(
                                            self[field.odoo_field_name]), campo_a3))
                                    else:
                                        list_parametros.append(Parametro(
                                            field.a3erp_field_name, self[field.odoo_field_name][field.table_code], campo_a3))
                                else:
                                    list_parametros.append(Parametro(field.a3erp_field_name, self[field.odoo_field_name], campo_a3))
                            elif 'ENVIAREMAIL' in field.a3erp_field_name:
                                list_parametros.append(Parametro(field.a3erp_field_name, 'TRUE' if self.send_email else 'FALSE', 'BOOLEAN'))

                            elif not self[field.odoo_field_name] and field.mandatory_field:
                                empty_mandatory_fields.append(self.company_id.get_field_translations(field.odoo_field_name,self))

                        elif field.default_value:
                            default, campo_a3 = field.default_value.split('|',1)
                            list_parametros.append(Parametro(field.a3erp_field_name, default, campo_a3))

                    if self.cod_contacto_a3:
                        list_parametros.append(Parametro("CODIGO", self.cod_contacto_a3, "INTEGER"))
                        list_parametros.append(Parametro("IDCONTACTORELACION", self.id_contacto_relacion, "INTEGER"))
                        TIPO = "MODIFICAR"
                    else:
                        TIPO = "ALTA"

                    if empty_mandatory_fields:
                        fields = ', '.join(empty_mandatory_fields)
                        self.message_post(message_type='comment', body=f"Los siguientes campos son requeridos y estan vacíos: '{fields}'")
                        create_log.create_log(self, "ERROR", "POST", self._name, self.id, self.name, f"Los siguientes campos son requeridos y estan vacíos: '{fields}'", self.company_id.id)
                        return f"Los siguientes campos son requeridos y estan vacíos: '{fields}'"
                    else:    
                        list_parametros.append(Parametro("CODCLI", cuadrar(self.parent_id.cod_cliente_a3), "STRING"))
                        post_contacto = MensajeSolicitudPost(self.company_id.a3erp_company_id, TIPO, ENTIDADCONTACTOS, list_parametros)
                        response = requests.post(NAX_CONTACTOS.format(self.company_id.a3erp_url), json=post_contacto.to_json(), verify=False, headers=headers, timeout=10)
                        self.json_content_send = json_list_to_json_dump(post_contacto.to_json())
                else:
                    self.message_post(message_type='comment', body=f"El Cliente padre no tiene un codigo de a3ERP.")
                    return

            self.a3erp_error_simple, self.a3erp_error_extend = "", ""
            if response.status_code == 200:  # CONSULTA SIN ERRORES
                return_message = MensajeRetorno = json.loads(response.text)
                # ACTUALIZAR CAMPOS SI EL MENSAJE ES SIN ERRORES
                if return_message['message'] == "Sin Errores":
                    self.id_queue = return_message['result']
                    self.queue_state = "PENDIENTE"
                    self.message_post(message_type='comment', body=f"Respuesta a3ERP: {return_message['message']}")
                    return True
                
                elif return_message['message'] == "Error":
                    self.queue_state = "ERROR"
                    self.a3erp_error_simple = return_message['result']
                    # self.message_post(message_type='comment', body=f"Respuesta a3ERP: {return_message['message']} - {return_message['result']}")
                    create_log.create_log(self, "WARNING", "POST", self._name, self.id, self.name, return_message['result'], self.company_id.id)

            elif response.status_code == 400:
                return_message = json.loads(response.text)['errors']
                error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
                # self.message_post(message_type='comment', body=f"Error de Datos: {return_message[error_key][0]}")
                self.a3erp_error_extend = return_message[error_key][0]
                create_log.create_log(self, "ERROR", "POST", self._name, self.id, self.name, return_message[error_key][0], self.company_id.id)

            elif response.status_code == 401:
                msg = "Unauthorized: Usuario o Contraseña erroneos o Token Expirado."
                create_log.create_log(self, "ERROR", "POST", self._name, self.id, self.name, msg, self.company_id.id)
                self.a3erp_error_extend = msg
                self.message_post(message_type='comment', body=msg)

        except Exception as e:
            _logger.error(format(e))
            create_log.create_log(self, "ERROR", "POST", self._name, self.id, self.name, format(e), self.company_id.id)
            self.a3erp_error_extend = format(e)
        finally:
            self.env.cr.commit()

    def get_cola_state(self):
        self.company_id.get_cola_state(self)

    def get_contacts_to_syncro(self):
        """Recoger todos los CONTACTOS con fecha de escritura de hace 2 dias, y que la fecha de ultima sincronización es mas pequeña que la de escritura o esta vacia. """
        if not self:
            TWO_DAYS_AGO = datetime.now() - timedelta(days=2)
            contacts = self.search([('write_date','>=',TWO_DAYS_AGO),('parent_id','!=', False), ('type','in',('contact','other')), ('company_type','=','person'), ('write_uid','!=',1)]).filtered(lambda x: x.last_date_update == False or x.last_date_update < x.write_date)
        else:
            contacts = self
        for contact in contacts.filtered(lambda x: x.a3erp_active_company == True):
            if contact.parent_id and contact.type in ('contact','other'):
                contact.action_a3erp_syncro()

    def get_a3erp_contact_data(self):
        """Actualizar directamente el Contacto/Cliente/Direccion/Proveedor con los datos de a3ERP.
        Returns:
            Notification: Notificacion con mensaje final. 
        """
        tabla,url,key = None, None, None
        if self.cod_cliente_a3:
            tabla = 'clientes'
            url = GETBYCODE_CLIENTES
            key = cuadrar(self.cod_cliente_a3)
        elif self.cod_contacto_a3:
            tabla = 'contactos'
            url = GETBYCODE_CONTACTOS
            key = self.id_contacto_relacion.strip()
        elif self.cod_dirent_a3:
            tabla = 'dirent'
            url = GETBYCODE_DIRENT
            key = self.cod_dirent_a3.strip()

        if tabla and url and key:
            notType,msg = None,None
            response, requiredFields = self.env['a3erp.replogs'].get_a3erp_record_data(tabla, url, self.company_id, key)
            if isinstance(response[0], dict):
                response = response[0]
                values_to_update = {"last_date_update": datetime.now()}
                values_to_update = self.prepare_values_to_update_partner(
                    requiredFields,
                    self.company_id.id,
                    a3erp_dict=response,
                    values_to_update=values_to_update,
                )
                record_active = response.get('BLOQUEADO') 
                if record_active == 'T':
                    values_to_update['active'] = False
                elif record_active == 'F':
                    values_to_update['active'] = True

                try:
                    self.sudo().with_context(dict(values_from_a3=True)).write(values_to_update)
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
                    'sticky': True,
                }
            }
            return notification

    def action_a3erp_send_delivery_address(self):
        """Envía la dirección de entrega a a3ERP"""
        self.ensure_one()

        if self.type != 'delivery' or not self.parent_id:
            raise ValidationError("Este botón solo es válido para direcciones de entrega.")

        if not self.parent_id.cod_cliente_a3:
            raise ValidationError("El cliente padre no está sincronizado con a3ERP.")

        headers = {
            'Authorization': f'Bearer {self.company_id.a3erp_token}',
            'Content-Type': 'application/json'
        }

        list_parametros = []
        empty_mandatory_fields = []

        try:
            # Campos configurados para DIRECCIONES
            required_fields = self.env['a3erp.campos'].get_required_values_send(
                self.company_id.id, 'dirent'
            )

            if not required_fields:
                raise ValidationError("No hay campos configurados para direcciones de entrega.")

            for field in required_fields:
                if field.odoo_field_name:
                    if self[field.odoo_field_name]:
                        campo_a3 = MAPPER.traducir_campo(
                            self._fields[field.odoo_field_name].type
                        )

                        if field.relational_table:
                            value = self[field.odoo_field_name][field.table_code]
                        else:
                            value = self[field.odoo_field_name]

                        list_parametros.append(
                            Parametro(field.a3erp_field_name, value, campo_a3)
                        )

                    elif field.mandatory_field:
                        empty_mandatory_fields.append(
                            self.company_id.get_field_translations(
                                field.odoo_field_name, self
                            )
                        )

                elif field.default_value:
                    default, campo_a3 = field.default_value.split('|', 1)
                    list_parametros.append(
                        Parametro(field.a3erp_field_name, default, campo_a3)
                    )

            if empty_mandatory_fields:
                fields = ', '.join(empty_mandatory_fields)
                raise ValidationError(
                    f"Campos obligatorios sin informar: {fields}"
                )

            # Relación con cliente
            list_parametros.append(
                Parametro("CODCLI", cuadrar(self.parent_id.cod_cliente_a3), "STRING")
            )
            
            numdir = self._get_next_numdir(self.parent_id.cod_cliente_a3)
            if not numdir:
                raise ValidationError("No hay un NUMDIR valido para crear en este Cliente.")
            
            list_parametros.append(
                Parametro("NUMDIR", numdir, "INTEGER")
            )

            post_direccion = MensajeSolicitudPost(
                self.company_id.a3erp_company_id,
                "ALTA_DIRENT",
                ENTIDADDIRECCIONES,
                list_parametros
            )

            response = requests.post(
                NAX_DIRENT.format(self.company_id.a3erp_url),
                json=post_direccion.to_json(),
                verify=False,
                headers=headers,
                timeout=10
            )

            self.json_content_send = json_list_to_json_dump(
                post_direccion.to_json()
            )

            if response.status_code == 200:
                result = json.loads(response.text)
                if result.get('message') == "Sin Errores":
                    self.a3erp_error_simple = ""
                    self.a3erp_error_extend = ""
                    self.queue_state = "PENDIENTE"
                    self.id_queue = result.get('result')
                    self.message_post(message_type='comment', body=f"Respuesta a3ERP: {result['message']}")
                else:
                    self.queue_state = "ERROR"
                    self.a3erp_error_simple = result.get('result')
                    create_log.create_log(self, "WARNING", "POST", self._name, self.id, self.name, result['result'], self.company_id.id)
            else:
                self.queue_state = "ERROR"
                self.a3erp_error_extend = response.text
                self.message_post(message_type='comment', body=response.text)

        except Exception as e:
            _logger.exception(e)
            self.queue_state = "ERROR"
            self.a3erp_error_extend = str(e)
            raise ValidationError(format(e))

        finally:
            self.env.cr.commit()
    
    def process_replogs_partner(self, repValues):
        """Metodo para procesar los replogs de clientes/contactos/proveedores.
        Args:
            repValues (Object): Lista de replogs a procesar.
        """
        ordenados = sorted(
            [x for x in repValues if not x.error],
            key=lambda x: x.fecha
        )
        
        for replog in ordenados:
            new_cont = {}
            company_id = replog.company_id.id if replog.company_id else None
            if replog._name in ['a3erp.clientes', 'a3erp.contactos']:
                if replog._name == 'a3erp.clientes':
                    name_key = replog.nomcli
                    key_field, nifvalue, table_name = 'cod_cliente_a3', replog.nifcli, 'clientes'
                else:
                    name_key = replog.nombre
                    parent_cod = replog.codcli
                    if not parent_cod:

                        replog.message_post(
                            message_type='comment',
                            body="El Contacto no está relacionado a ningún Cliente."
                        )

                        replog.error = True
                        continue
                    
                    parent_records = self.search_partner_by_a3erp_codcli(replog.codcli, company_id)
                    
                    if len(parent_records) > 1:
                        replog.message_post(message_type='comment', body=f"Se encontraron múltiples clientes con el código {replog.codcli}")
                        replog.error = True
                        continue
                    elif not parent_records:
                        replog.message_post(message_type='comment', body=f"No se encontró el cliente con código {replog.codcli}")
                        replog.error = True
                        continue
                    
                    parent_id = parent_records.id                    
                    key_field, nifvalue, table_name = 'id_contacto_relacion', None, 'contactos'

            elif replog._name == 'a3erp.proveed':
                name_key = replog.nompro
                key_field, nifvalue, table_name = 'cod_proveed_a3', replog.nifpro, 'proveed'

            required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(replog, table_name)
            required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
            try:
                domain = [('active', 'in', (False, True)), ('company_id', '=', company_id)]
                if not table_name == 'contactos':
                    key, mapped_key = getattr(replog, 'codcli' if replog._name != 'a3erp.proveed' else 'codpro'), 'codcli' if replog._name != 'a3erp.proveed' else 'codpro'
                    if key:
                        partner = self.search(domain + [(key_field, '=', key)])
                        # NOTE: Quitada la comprobacion del NIF. Comprobar solo el CODCLI ya que es el campo clave. 
                        # Puede que el mismo NIF este en distintos clientes y no es correcto actualizar el cliente que tenga ese NIF.
                        if not partner and nifvalue:
                            partners_by_vat = self.search(domain + [('vat', '=', nifvalue)]).filtered(lambda x: x.company_type == 'company')
                            """valid_partners = partners_by_vat.filtered(
                                lambda p: not p[key_field] or p[key_field] == key
                            )
                            if len(valid_partners) == 1:
                                partner = valid_partners
                            else:
                                partner = self.env['res.partner']"""
                    else:
                        replog.unlink()
                        continue
                else:
                    #key = replog.idcontacto
                    key = replog.idcontactorelacion
                    partner = self.search([(key_field, '=', key),('parent_id.cod_cliente_a3','=', replog.codcli)] + domain)

                if name_key:
                    if len(partner) > 1: # SI AUN FILTRANDO POR CODIGO SIGUE HABIENDO VARIOS CLIENTES/CONTACTOS, FILTRAR POR NOMBRE
                        partner = partner.filtered(lambda x: x.name == name_key)

                    # CONTROLAR SI HAY MAS DE UN PARTNER CLAVE
                    if required_fields and len(partner) < 2:
                        if partner and (replog.movimiento == 'BOR' or replog.obsoleto in (1,'T')):  # CLIENTE BORRADO EN A3
                            partner.last_date_update = datetime.now()
                            partner.active = False

                        # PARTNER EXISTENTE MODIFICADO O CREADO DE NUEVO EN A3
                        elif partner and replog.movimiento in ('ALT', 'MOD'):
                            values_to_update = {
                                "last_date_update": datetime.now(),
                                "company_id": company_id,
                                "active": True,
                                "queue_state": "FINALIZADO",
                            }                         
                            values_to_update = self.prepare_values_to_update_partner(
                                required_fields,
                                company_id,
                                replog=replog,
                                values_to_update=values_to_update
                            )
                            partner.write(values_to_update)
                            replog.message_post(message_type='comment', body="Registro actualizado.")

                        # PARTNER NUEVO EN A3 Y EN ODOO
                        elif not partner and replog.movimiento in ('ALT', 'MOD'):
                            new_cont = {
                                "last_date_update": datetime.now(),
                                "company_id": replog.company_id.id,
                                "type": 'contact',
                                "company_type": (
                                    "person" if table_name == "contactos" else "company"
                                ),
                                "queue_state": "FINALIZADO",
                            }
                            if replog._name == 'a3erp.proveed':
                                new_cont['supplier_rank'] = 1
                            elif replog._name == 'a3erp.clientes':
                                new_cont['customer_rank'] = 1      

                            for field in required_fields:
                                if field.default_value:
                                    default = field.default_value.split('|',1)
                                    new_cont[field.odoo_field_name] = default[0]
                                    continue

                                if replog[field.mapped_name]:
                                    if field.relational_table:
                                        if 'carac' in field.odoo_field_name:
                                            value_id = self.get_caracteristica(field.table_code, field.relational_table, field.a3erp_field_name, replog[field.mapped_name], company_id)
                                        else:
                                            value_id = self.resolve_field_values(field, replog)

                                        if value_id:
                                            new_cont[field.odoo_field_name] = value_id
                                    else:
                                        if "TARIFA" in field.a3erp_field_name:
                                            new_cont[field.odoo_field_name] = replog[field.mapped_name].strip()
                                        elif "APEN_EXENTOCANON" in field.a3erp_field_name:
                                            new_cont[field.odoo_field_name] = True if replog[field.mapped_name] == 'N' else False
                                        else:
                                            new_cont[field.odoo_field_name] = replog[field.mapped_name]        
                                elif "APEN_EXENTOCANON" in field.a3erp_field_name:
                                    new_cont[field.odoo_field_name] = True

                            self.create(new_cont)
                            replog.message_post(message_type='comment', body="Registro creado.")

                        replog.procesado = True
                        replog.error = False
                        self.env.cr.commit()

                    else:
                        error = f"No hay campos obligatorios informados para {table_name} revisar." if not required_fields else f"El {table_name} con codigo {key} o VAT {nifvalue} esta duplicado. Revisar"
                        replog.message_post(message_type='comment', body=f"{error}")
                        replog.error = True
                else:
                    #replog.message_post(message_type='comment', body=f"El registro no tiene un nombre establecido.")
                    #replog.error = True
                    replog.unlink()

            except Exception as e:
                _logger.info(format(e))
                self._handle_error(replog, e)
            finally:
                continue

    def prepare_values_to_update_partner(self, required_fields, company_id, replog=False, a3erp_dict=False, values_to_update=False):
        """
            Actualiza el diccionario de valores 'values_to_update' con los campos de Odoo correspondientes
            basados en los datos del 'RepLogs' y, en su defecto, usando 'a3erp_dict' si actualizamos desde la ficha del registro.

            :param required_fields: Lista de objetos con la definición de los campos requeridos.
            :param company_id: ID de la compañía para búsquedas relacionadas.
            :param replog: Replog con los datos nuevos.
            :param a3erp_dict: Diccionario adicional con datos de a3ERP (usado si 'replog' no tiene valores).
            :param values_to_update: Diccionario con los valores a actualizar en el partner de Odoo.
            :return: Diccionario 'values_to_update' actualizado.
        """      
        for field in required_fields:
            fieldKey = self.translate_field(field.a3erp_field_name)                
            if not a3erp_dict and field.default_value:
                default = field.default_value.split('|',1)
                values_to_update[field.odoo_field_name] = default[0]
                continue

            # Verificar si el campo existe en replog y tiene valor
            replog_value = replog[field.mapped_name] if replog else None

            if replog_value:
                if field.relational_table:
                    if 'carac' in field.odoo_field_name:
                        value_id = self.get_caracteristica(field.table_code, field.relational_table, field.a3erp_field_name, replog[field.mapped_name], company_id)
                    else:
                        value_id = self.resolve_field_values(field, replog)

                    if value_id:
                        values_to_update[field.odoo_field_name] = value_id
                else:
                    if "TARIFA" in field.a3erp_field_name:
                        values_to_update[field.odoo_field_name] = replog[field.mapped_name].strip()
                    elif "APEN_EXENTOCANON" in field.a3erp_field_name:
                        values_to_update[field.odoo_field_name] = True if replog[field.mapped_name] in ('N','')  else False
                    else:
                        values_to_update[field.odoo_field_name] = replog[field.mapped_name]

            # Si no hay valor en replog, pero hay a3erp_dict, buscar en a3erp_dict                
            elif a3erp_dict and fieldKey in a3erp_dict:         
                a3erp_value = a3erp_dict[fieldKey].strip() if 'COD' in fieldKey else a3erp_dict[fieldKey]
                # Actualizar values_to_update con el valor del a3erp_dict
                if a3erp_value:
                    if field.relational_table:
                        if 'carac' in field.odoo_field_name:
                            value_id = self.get_caracteristica(
                                field.table_code, field.relational_table,
                                fieldKey, a3erp_value, company_id)
                        else:
                            value_id = self.resolve_field_values(field, a3erp_dict, is_dict=True, company=company_id)

                        if value_id:
                            values_to_update[field.odoo_field_name] = value_id
                    else:
                        if "TARIFA" in field.a3erp_field_name:
                            values_to_update[field.odoo_field_name] = a3erp_value.strip()
                        elif "APEN_EXENTOCANON" in field.a3erp_field_name:
                            values_to_update[field.odoo_field_name] = True if a3erp_value in ('N', '') else False
                        else:
                            values_to_update[field.odoo_field_name] = a3erp_value

            elif "APEN_EXENTOCANON" in field.a3erp_field_name:
                values_to_update[field.odoo_field_name] = True

        return values_to_update

    def _handle_error(self, replog, error):
        """Manejar errores durante el procesamiento."""
        replog.error = True
        replog.message_post(message_type='comment', body=format(error))
        create_log.create_log(self, "ERROR", False, self._name, replog.id, replog.nomcli, format(error), replog.company_id.id)

    def process_replogs_dirent(self, repValues):
        """
            Processar los replogs de direcciones de entrega.
        Args:
            repValues (List): Lista de RepLogs a preocesar.
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'dirent')
        if not required_fields_by_company:
            create_log.create_log(self, "ERROR", False, self._name, False,False, "No hay campos de Direcciones informados.") 
        else:
            ordenados = sorted(
                [x for x in repValues if not x.error],
                key=lambda x: x.fecha , reverse=False
            )   

            for replog in ordenados:              
                company_id = replog.company_id.id if replog.company_id else None
                required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                defecto_field = next((field for field in required_fields if 'DEFECTO' in field.a3erp_field_name), None)
                try:
                    delivery_address = self.search([('cod_dirent_a3', '=', replog.iddirent), ('active', 'in', (False, True)), ('company_id', 'in', (False, replog.company_id.id))])
                    if len(delivery_address) < 2:
                        parent_id = self.search_partner_by_a3erp_codcli(replog.codcli, company_id)
                        if delivery_address and (replog.movimiento == 'BOR' or replog.obsoleto == 'T'):  # DIRECCION BORRADA O OBSOLETA EN A3
                            delivery_address.last_date_update = datetime.now()
                            delivery_address.active = False
                        
                        elif delivery_address and replog.movimiento in ('ALT', 'MOD'):
                            values_to_update = {
                                "cod_dirent_a3": replog.iddirent,
                                "last_date_update": datetime.now(),
                                "company_id": replog.company_id.id,
                                "active": True,
                            }
                            for field in required_fields:
                                if replog[field.mapped_name]:
                                    if field.relational_table:
                                        value_id = self.resolve_field_values(field, replog)
                                        values_to_update[field.odoo_field_name] = value_id if value_id else ''
                                    else:
                                        values_to_update[field.odoo_field_name] = replog[field.mapped_name]
                            delivery_address.write(values_to_update)
                            replog.message_post(message_type='comment', body="Registro actualizado.")
                        
                        elif not delivery_address and replog.movimiento in ('ALT', 'MOD'):
                            #parent_id = self.search_partner_by_a3erp_codcli(replog.codcli, company_id).id
                            if parent_id:
                                new_address = {
                                    "last_date_update": datetime.now(),
                                    "company_id": replog.company_id.id,
                                    "company_type": "person",
                                    "type": "delivery",
                                }
                                for field in required_fields:
                                    if replog[field.mapped_name]:
                                        if field.relational_table:
                                            value_id = self.resolve_field_values(field, replog)
                                            new_address[field.odoo_field_name] = value_id if value_id else ''
                                        else:
                                            new_address[field.odoo_field_name] = replog[field.mapped_name]
                                delivery_address = self.create(new_address)
                                replog.message_post(message_type='comment', body="Registro creado.")
                            else:
                                mensaje_existente = replog.message_ids.filtered(
                                    lambda m:
                                      f"No se ha encontrado el Cliente al que pertenece {replog.codcli}." in m.body
                                )
                                if not mensaje_existente:
                                    replog.message_post(message_type='comment', body=f"No se ha encontrado el Cliente al que pertenece {replog.codcli}.")
                                replog.error = True
                                continue
                        
                        if defecto_field and replog[defecto_field.mapped_name] == 'T':
                            self._set_default_partner_shipping(parent_id, delivery_address)
                        
                        replog.procesado = True
                        replog.error = False
                        self.env.cr.commit()
                    else:
                        replog.message_post(message_type='comment', body=f"Hay mas de una Direccion de Entrega con esa ID {replog.iddirent}.")
                        replog.error = True
                except Exception as e:
                    _logger.info(format(e))
                    self._handle_error(replog, e)
                finally:
                    continue

    def process_replogs_alarmas(self, repValues):
        """
            Procesar solo los replogs de Alarmas de Clientes.
        Args:
            repValues (List): Lista de RepLogs.
        """
        required_fields_by_company = self.env['a3erp.campos'].get_required_values_receive(repValues, 'alarmas')
        if not required_fields_by_company:
            create_log.create_log(self, "ERROR", False, self._name, False, "No hay campos de Alarmas informados.")
        else:
            filtered_replogs = [replog for replog in repValues if replog.codcli]
            sorted_filtered_replogs = sorted(filtered_replogs, [x for x in repValues if not x.error], key=lambda x: x.fecha, reverse=False)
            for replog in sorted_filtered_replogs:
                company_id = replog.company_id.id or None
                # required_fields = required_fields_by_company.get(company_id, self.env['a3erp.campos'])
                try:
                    partner_id = self.search_partner_by_a3erp_codcli(replog.codcli, company_id)
                    if partner_id and replog.movimiento in ('ALT', 'MOD'):                 
                        values_to_update = {        
                            "last_date_update": datetime.now(),
                            'sale_warn': 'warning',
                            'sale_warn_msg': replog.alarmaofe                           
                        }
                        partner_id.update(values_to_update)

                        replog.procesado = True
                        replog.error = False
                        self.env.cr.commit()
                    elif not partner_id:
                        replog.message_post(message_type='comment', body=f"El Cliente {replog.codcli} no existe.")
                        replog.error = True
                    else:
                        continue

                except Exception as e:
                    _logger.info(format(e))
                    self._handle_error(replog, e)
                finally:
                    continue

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
            # El grupo 1 contiene el número, el grupo 2 contiene '_ORG' si existe
            num_carac = int(match.group(1)) 
            tip_carac = 'O' if match.group(2) else 'C' 

        carac_id = self.env[modelo].search([('num_carac','=',num_carac),('tip_carac','=',tip_carac),(table_code,'=', valor.strip()),('company_id','=', company_id)]).id        
        return carac_id or False        

    # AÑADIR CAMPOS ESPECIALES
    def resolve_field_values(self, field, replog, is_dict=False, company=False):
        """Metodo para añadir condiciones especiales de los campos.
        Args:
            field (Object): Registro del Mappeado.
            replog (Object): Registro del replogs.
        Returns:
            String: Devuelve el valor buscado
        """
        key = self.translate_field(field.a3erp_field_name)
        code = (replog[key if key else field.a3erp_field_name] if is_dict else replog[field.mapped_name])
        code = code.strip() if isinstance(code, str) else code
        company_id = company if is_dict else replog.company_id.id
        codpais = replog['CODPAIS'] if is_dict else replog['codpais']
        if 'CODPROVI' in field.a3erp_field_name:  # CODIGO PROVINCIA
            return self.env[field.relational_table].search([(field.table_code, '=', code), ('country_id.code', '=', codpais)]).id
        elif 'CODIDIOMA' in field.a3erp_field_name:  # TRADUCIR IDIOMA
            return LANGMAPPER.traducir(code, 'a3erp')
        elif 'FAMCLIDESC' in field.a3erp_field_name:
            # if 'company_id' in self.env[field.relational_table]._fields:
            #     return self.env[field.relational_table].search([(field.table_code, '=', code), ('a3erp_pricelist_type','=','descuentos_fam'),('company_id','=', company_id)]).id    
            # else:
            #     return self.env[field.relational_table].search([(field.table_code, '=', code), ('a3erp_pricelist_type','=','descuentos_fam')]).id        
            return self.env[field.relational_table].search([(field.table_code, '=', code), ('company_id','=', company_id)]).id    
        else:
            if 'company_id' in self.env[field.relational_table]._fields:
                return self.env[field.relational_table].search([(field.table_code, '=', code), ('company_id','=', company_id)]).id
            else:
                return self.env[field.relational_table].search([(field.table_code, '=', code)]).id

    def search_partner_by_a3erp_codcli(self, codCli, company_id):
        """Devuelve el Cliente filtrado segun el CODCLI.
        Args:
            codCli (String): CodCLi del cliente
            company_id (Integer): Compañia objetivo
        Returns:
            Object: Devuelve el cliente encontrado.
        """
        return self.search([('cod_cliente_a3', '=', codCli), ('company_id','in', (company_id, False))])

    def _set_default_partner_shipping(self, parent_id, delivery_address):
        """Llenar el campo de la OCA partner_delivery_id con la direccion por defecto que viene de a3ERP.
        Args:
            parent_id (Obj): Padre de la direccion de entrega.
            delivery_address (Obj): Direccion de envio 
        """
        default_shipping = parent_id.partner_delivery_id == delivery_address
        if not default_shipping:
            parent_id.write({'partner_delivery_id': delivery_address.id})     
    
    #OBSOLETO
    #@api.constrains('cod_tarifa_a3')
    def _update_standard_pricelist(self):
        """Actualizar la tarifa estandard informada en la tarifa de precios especiales del cliente."""
        for record in self:
            if not record.a3erp_active_company:
                return
            if record.property_product_pricelist.a3erp_pricelist_type == 'precios_esp':
                partner_special_pricelist = record.property_product_pricelist
                standard_pricelist_line = partner_special_pricelist.item_ids.filtered(lambda x: x.base_pricelist_id.a3erp_pricelist_type == 'standard')  # OBTENER LA LINEA DONDE ESTA LA TARIFA ESTANDARD INFORMADA
                new_pricelist = self.env['product.pricelist'].search([('a3erp_pricelist_code', '=', record.cod_tarifa_a3), ('a3erp_pricelist_type','=','standard'), ('company_id','in', (self.company_id.id, False))])
                if standard_pricelist_line.base_pricelist_id != new_pricelist:
                    if new_pricelist:
                        try:
                            if standard_pricelist_line:
                                partner_special_pricelist.write({'last_date_update': datetime.now()})
                                standard_pricelist_line.write({'base_pricelist_id': new_pricelist.id})
                            else:
                                new_line = {
                                    'compute_price': 'formula',
                                    'base': 'pricelist',
                                    'base_pricelist_id': new_pricelist.id,
                                    'applied_on': '3_global',
                                    'date_start': datetime.now() + timedelta(days=-2),
                                }

                                partner_special_pricelist.write({
                                    'last_date_update': datetime.now(),
                                    'item_ids': [(0, 0, new_line)]
                                })
                        except Exception as e:
                            create_log.create_log(self, "ERROR", False, partner_special_pricelist._name, False, partner_special_pricelist.name, f"Error actualizando Tarifa Estandard: {format(e)}", self.company_id.id)
                    else:
                        create_log.create_log(self, "ERROR", False, partner_special_pricelist._name, False, partner_special_pricelist.name,f"La tarifa estandard con codigo {record.cod_tarifa_a3} no existe.", self.company_id.id)
            else:
                if record.cod_tarifa_a3:
                    standard_pricelist = self.env['product.pricelist'].search([('a3erp_pricelist_code', '=', record.cod_tarifa_a3), ('a3erp_pricelist_type','=','standard'), ('company_id','in', (self.company_id.id, False))])
                    if standard_pricelist:
                        record.update({'property_product_pricelist': standard_pricelist.id})
     
    #OBSOLETO
    #@api.constrains('pricelist_desc_fam_id')
    def _update_pricelist_desc_fam_id(self):
        """Actualizar la tarifa de Descuento Familia de Cliente en la Tarifa de Cliente."""
        for record in self:
            if not record.a3erp_active_company:
                return
            if record.pricelist_desc_fam_id:
                partner_special_pricelist = record.property_product_pricelist  # TARIFA CLIENTE
                if partner_special_pricelist.a3erp_pricelist_type == "precios_esp":
                    discount_pricelist_line = (
                        partner_special_pricelist.item_ids.filtered(lambda x: x.base_pricelist_id.a3erp_pricelist_type == "descuentos_fam"))  # OBTENER LA LINEA DONDE ESTA LA TARIFA ESTANDARD INFORMADA

                    if discount_pricelist_line and discount_pricelist_line.base_pricelist_id != record.pricelist_desc_fam_id:
                        """ACTUALIZAR LINEA TARIFA FAMILIA CLIENTE"""
                        partner_special_pricelist.write(
                            {
                                "last_date_update": datetime.now(),
                                "item_ids": [(1, discount_pricelist_line.id, {"base_pricelist_id": record.pricelist_desc_fam_id.id})]
                            }
                        )

                    elif not discount_pricelist_line:
                        """AÑADIR LINEA TARIFA FAMILIA CLIENTE"""
                        try:
                            new_line = {
                                "compute_price": "formula",
                                "base": "pricelist",
                                "base_pricelist_id": record.pricelist_desc_fam_id.id,
                                "applied_on": "3_global",
                                "date_start": datetime.now() + timedelta(days=-2),
                            }
                            partner_special_pricelist.write(
                                {
                                    "last_date_update": datetime.now(),
                                    "item_ids": [(0, 0, new_line)],
                                }
                            )
                        except Exception as e:
                            create_log.create_log(self,"ERROR",False,record._name,False,record.name,f"Error actualizando Tarifa de Cliente: {format(e)}",self.company_id.id,)

                else:
                    partner_pricelist = self.create_simple_partner_pricelist(partner=self)
                    record.write({"property_product_pricelist": partner_pricelist.id})
                    self._update_pricelist_desc_fam_id()
            else:
                record.message_post(message_type='comment', body=f"La tarifa Familia Descuento {record.pricelist_desc_fam_id.id} no existe.")
                # create_log.create_log(self,"ERROR",False, record._name, record.id, record.name,f"La tarifa Familia Descuento {record.pricelist_desc_fam_id.id} no existe.",self.company_id.id,)

    def create_simple_partner_pricelist(self, partner):
        """Crear tarifa simple de cliente.
        Args:
            partner (Object): Cliente que se acaba de crear
        Returns:
            Object: Tarifa
        """
        try:
            pricelist = self.env['product.pricelist'].create({
                'name': partner.name,
                'a3erp_pricelist_type':'precios_esp',
                'partner_id': partner.id,
                'last_date_update': datetime.now(),
                'company_id': partner.company_id.id
            })
            return pricelist
        except Exception as e:
            create_log.create_log(self, "ERROR", False, self._name, False, self.name, f"{format(e)}.", partner.company_id.id)    

    def write(self, values):
        result = super(ResPartner, self).write(values)
        for record in self:
            
            """Actualizar el comercial de los contactos hijos si se actualiza en el cliente padre."""
            if 'user_id' in values and self.cod_cliente_a3 and self.child_ids:
                for child in record.child_ids:
                    if not child.cod_cliente_a3:
                        child.user_id = values['user_id']                
            
            if not record.company_id.a3erp_active_company:
                return result

            if (
                self.env.context.get('values_from_a3') or
                self.env.user.id == self.env.ref('base.user_root').id or
                self.env.user.has_group('tl_conn_a3erp.group_a3erp') or
                self.env.context.get('force_email') or
                self.env.context.get('params') 
            ):
                return result

            stack = inspect.stack()
            if any('base_partner_merge' in frame.filename for frame in stack):
                return result

            if any(campo in values for campo in campos_ignorados):
                return result

            if record.queue_state == 'PENDIENTE' or record.cod_cliente_a3:
                raise ValidationError('No se puede modificar el Cliente. Ya se ha enviado a a3ERP.')

            return result
    
    def copy(self, default=None):
        default = dict(default or {})
        return super(ResPartner, self).copy(default)

    def translate_field(self,field):
        """Devuelve el campo de a3ERP informado en el mappeo de campos sin la tabla delante. (Solo algunos casos)
        Args:
            field (String): Campo a3erp con la tabla.
        Returns:
            String: Nombre del campo
        """
        match = re.search(r'\sas\s*(\w+)$|\.(\w+)$|(\w+)$', field, re.IGNORECASE)
        if match:
            fieldKey = next((group for group in match.groups() if group), None)
            return fieldKey
        return False
    
    def _get_next_numdir(self, codcli):
        headers = {
            'Authorization': f'Bearer {self.company_id.a3erp_token}',
            'Content-Type': 'application/json'
        }
        
        numdir_cliente = MensajeSolicitudGet(self.company_id.a3erp_company_id,[],cuadrar(codcli))    
             
        response = requests.post(
            GETNUM_DIRENT.format(self.company_id.a3erp_url),
            json=numdir_cliente.to_json(),
            verify=False,
            headers=headers,
            timeout=10
        )
        result = json.loads(response.text)
        return result['result'][0]['Column1']       
    
    def get_a3erp_riesgo_cliente(self):
        """
            Consulta en a3ERP:
                - Situación de riesgo (riesgo consumido)
                - Datos del cliente (riesgo máximo)

        Returns:
            dict: {
                'riesgo_consumido': float,
                'riesgo_maximo': float
            }
        """
        self.ensure_one()

        if not self.cod_cliente_a3:
            return {
                'riesgo_consumido': 0.0,
                'riesgo_maximo': 0.0,
            }

        headers = {
            'Authorization': f'Bearer {self.company_id.a3erp_token}',
            'Content-Type': 'application/json'
        }

        codcli = cuadrar(self.cod_cliente_a3)

        try:
            list_parametros = []
            list_parametros.append(Parametro("CODCLI", codcli, "STRING"))
            # CONSULTA SITUACION RIESGO
            riesgo_request = MensajeSolicitudGetParams(
                self.company_id.a3erp_company_id,
                list_parametros
            )

            response_riesgo = requests.get(
                GET_SITUACIONRIESGO.format(self.company_id.a3erp_url),
                json=riesgo_request.to_json(),
                verify=False,
                headers=headers,
                timeout=5
            )

            if response_riesgo.status_code != 200:
                _logger.error(
                    "Error A3ERP Situación Riesgo (%s): %s",
                    response_riesgo.status_code,
                    response_riesgo.text
                )
                return False

            riesgo_data = json.loads(response_riesgo.text)

            riesgo_consumido = 0.0
            if riesgo_data.get('result'):
                data = riesgo_data.get('result')[0]
                total_sin_anticipos = sum(
                    value for key, value in data.items()
                    if key != 'ANTICIPOS'
                )
                anticipos_con_iva = data.get('ANTICIPOS', 0) * 1.21
                riesgo_consumido = total_sin_anticipos - anticipos_con_iva

            # CONSULTA DATOS CLIENTE
            cliente_request = MensajeSolicitudGet(
                self.company_id.a3erp_company_id,
                ['RIESGOCON'],
                codcli
            )

            response_cliente = requests.post(
                GETBYCODE_CLIENTES.format(self.company_id.a3erp_url),
                json=cliente_request.to_json(),
                verify=False,
                headers=headers,
                timeout=5
            )

            if response_cliente.status_code != 200:
                _logger.error(
                    "Error A3ERP Datos Cliente (%s): %s",
                    response_cliente.status_code,
                    response_cliente.text
                )
                return False

            cliente_data = json.loads(response_cliente.text)

            riesgo_maximo = 0.0
            if cliente_data.get('result'):
                riesgo_maximo = float(
                    cliente_data['result'][0].get('RIESGOCON', 0.0)
                )

            return {
                'riesgo_consumido': riesgo_consumido,
                'riesgo_maximo': riesgo_maximo,
            }

        except Exception as e:
            _logger.exception(e)
            create_log.create_log(self,"ERROR","GET",self._name,self.id,self.name,str(e),self.company_id.id)
            #raise ValidationError(str(e)) 
         
    # OBSOLETO: TRANSFORMAR TODOS LOS CAMPOS EN READONLY CUANDO SE ENTRA A LA VISTA
    """@api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'form': 
            for node in arch.xpath("//field"):
                exist_readonly = node.attrib.get('readonly','')
                domain = "queue_state in ('PENDIENTE') or cod_cliente_a3"
                if exist_readonly:
                    combined_readonly = "{} or {}".format(exist_readonly, domain)
                    node.attrib['readonly'] = str(combined_readonly)
                else:
                    node.attrib['readonly'] = str(domain)
                #node.set('edit','false')
        return arch, view"""

class Followers(models.Model):
   _inherit = 'mail.followers'

   @api.model
   def create(self, vals):
        if 'res_model' in vals and 'res_id' in vals and 'partner_id' in vals:
            dups = self.env['mail.followers'].search([('res_model', '=',vals.get('res_model')),
                                           ('res_id', '=', vals.get('res_id')),
                                           ('partner_id', '=', vals.get('partner_id'))])
            if len(dups):
                for p in dups:
                    p.unlink()
        return super(Followers, self).create(vals)
