from odoo.exceptions import MissingError, UserError, ValidationError
from odoo import fields,models,api, _
from .web_service import *
from . import create_log
from .mapper_campos import TypeMapper
import requests, json, logging

_logger = logging.getLogger(__name__)

NAX_OFERTAS = "{}/ofertav/nax"
NAX_PEDIDOS = "{}/pedidov/nax"
NAX_OFERTAS_CLIENTES = "{}/ofertav/naxCliente&Documento"
NAX_PEDIDOS_CLIENTES = "{}/pedidov/naxCliente&Documento"
ESTADO_COLA = "{}/cola/getEstadoCola"
CONSULTA_OFERTA = "{}/ofertav/getbycode"
CONSULTA_PEDIDO = "{}/pedidov/getbycode"
GET_PRECIOVENTA = "{}/articulo/getPrcVenta"
CAMPOS_CABECERA = ["CABECERA.TIPOCONT","CABECERA.NUMDOC", "CABECERA.SERIE"]
MAPPER = TypeMapper()
CANON_MODULE_NAME = "tl_products_obligatorios"

class SaleOrder(models.Model):
    _inherit = ['sale.order']

    a3erp_active_company = fields.Boolean(
        related="company_id.a3erp_active_company",
        readonly=True,
    )
    ref_ofev_a3 = fields.Char(string='Nº documento a3ERP', help="Tipo/Serie/Nº Documento", copy=False)
    id_queue = fields.Char(string='ID Cola',copy=False)
    queue_state = fields.Selection(
        string="Estado traspaso Cola",
        selection=[
            ("ESPERA", "EN ESPERA"),
            ("PENDIENTE", "PENDIENTE"),
            ("ERROR", "INCIDENCIA"),
            ("FINALIZADO", "FINALIZADO"),
        ],
        help='Estado de la peticion en la cola de creacion de la NAX.\n'
        'EN ESPERA: Pedido con Articulos pendientes de crear en a3ERP.\n'
        'PENDIENTE: Pedido enviado a a3ERP para procesar.\n'
        'INCIDENCIA: Pedido con incidencia/falta de datos.\n'
        'FINALIZADO: Pedido ya procesado.',
        track_visibility="onchange",
        copy=False
    )
    check_waiting_sales = fields.Boolean(copy=False)
    a3erp_error_simple = fields.Text(string='Error',copy=False)
    a3erp_error_extend = fields.Text(string='Error Extenso',copy=False)
    json_content_send = fields.Text(string='Contenido del Json enviado', readonly=True,copy=False)
    date_send = fields.Datetime(string='Fecha de Envio', help="Fecha de traspaso a a3ERP.",copy=False)
    is_kit = fields.Boolean(
        string='Es un KIT',
        help="Indica si este presupuesto/pedido es un kit, por lo que se creara en a3ERP como un kit.",
        copy=False,
    )
    kit_description = fields.Text(
        string='Descripción del Kit',
        help="Descripción del producto kit que se enviara a a3ERP.",
        copy=False,
    )
    show_update_partner = fields.Boolean(string='Ha cambiado el cliente', default=False)    
    a3erp_credit = fields.Float(string="Crédito Consumido")
    a3erp_max_credit = fields.Float(string="Crédito Máximo")
    credit_display = fields.Html(
        string="Situación Riesgo",
        compute="_compute_credit_display",
        store=False
    )
    credit_exceeded = fields.Boolean(
        compute="_compute_credit_display",
        store=True
    ) 
    
    def action_a3erp_send_confirm(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirmar envío',
            'res_model': 'a3erp.send.confirm.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'active_model': self._name,
            }
        }
    
    def process_waiting_sales(self):
        """Recibimos todos los pedidos en estado por de ESPERA, si sus articulos ya se han creado en a3, se envia a la cola."""
        for sale in self:
            context = self.env.context.get("automatic") # LA EJECUCION ES DEL CRON O MANUAL DESDE EL DOCUMENTO
            products_sin_codart = sale.check_products_without_codart()
            if context:
                if not products_sin_codart:
                    response = sale.with_context(waiting_function=True).action_a3erp_send()
                    if response:
                        if "type" in response:
                            continue
                        sale._log_and_continue(sale, response)
                elif not sale.check_waiting_sales:
                    sale._log_and_continue(sale, "Hay productos pendientes de crearse en a3ERP.")
                    sale.check_waiting_sales = True
            else:
                if not products_sin_codart:
                    response =  sale.with_context(waiting_function=True).action_a3erp_send()

                    if response and 'params' in response:
                        raise ValidationError(response['params']['message'])
                else:
                    raise MissingError("Hay productos pendientes de crearse en a3ERP.")

    def _open_confirmation_wizard(self, productos_sin_codart, record):
        """Abre el asistente de confirmación cuando faltan códigos de artículo en productos."""
        lista = '\n'.join(f"- {x.name}" for x in productos_sin_codart)
        value = self.env['sale.confirmation.wizard'].sudo().create({'message': f'{lista}'})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirmar Acción',
            'res_model': 'sale.confirmation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'productos_sin_codart': productos_sin_codart.ids, 'model_name': record._name, 'sale_order_id': record.id},
            'res_id': value.id
        }

    def _log_and_continue(self, record, message):
        """Publica un mensaje solo si no existe ya en el chatter."""
        existing_message = self.env['mail.message'].search([
            ('model', '=', record._name),
            ('res_id', '=', record.id),
            ('body', '=', message),
        ], limit=1)

        if not existing_message:
            record.message_post(
                message_type='comment',
                body=message,
            )

    def action_a3erp_send(self):
        """Antes de enviar el documento se comprueba de que tipo es. Si es pedido de Venta se tiene que crear antes el cliente y contacto.
        Hasta que no existen el Cliente y el contacto informado, el pedido no se puede tramitar.
        """
        for record in self:
            waiting_function = self.env.context.get("waiting_function") # LA EJECUCION VIENE DEL BOTON O DE LA TAREA PROGRAMADA
            a3erp_order_type = record.company_id.a3erp_sale_order_type
            record_partner_id = record.partner_id.parent_id if record.partner_id.parent_id else record.partner_id # CLIENTE, YA SEA PADRE DEL CONTACTO/CLIENTE DEL PEDIDO
            if a3erp_order_type == 'orders':
                # COMPROVAR QUE EL CLIENTE TIENE UN CODIGO DE A3
                if not record_partner_id.cod_cliente_a3:
                    if record_partner_id.queue_state == 'ERROR':
                        msg = f"INCIDENCIA: Cliente {record_partner_id.name}: \n" + "Revisar cliente."
                        if waiting_function:
                            return msg
                        else:
                            raise ValidationError(msg)

                    if not record_partner_id.id_queue or record_partner_id.queue_state != 'PENDIENTE':
                        partner_response = record_partner_id.action_a3erp_syncro()
                        if partner_response == True:
                            record._log_and_continue(record, f"ALERTA: Cliente {record_partner_id.name} en la Cola de creación.")
                            record.queue_state = 'ESPERA'
                            continue
                        else:
                            msg = f"INCIDENCIA: Cliente {record_partner_id.name}: \n" + "Revisar cliente."

                        if waiting_function:
                            return msg
                        else:
                            raise ValidationError(msg)

                    else:
                        record._log_and_continue(record, f"ALERTA: Cliente {record_partner_id.name} en la Cola de creación.")
                    continue
                
                if record_partner_id.company_id.a3erp_contact_required:
                    if not record_partner_id.check_contacts():
                        return "El Cliente debe tener almenos 1 Contacto para ser enviado a a3ERP."

                    if 'contact_partner_id' in record:
                        contact = record.contact_partner_id or record.partner_id
                    else:
                        contact = record.partner_id
                        
                    # COMPROVAR QUE EL CONTACTO TIENE UN CODIGO DE A3
                    if not contact.cod_contacto_a3:
                        if record_partner_id.queue_state == 'ERROR':
                            msg = f"INCIDENCIA: Contacto {contact.name}: \n" + "Revisar contacto."
                            if waiting_function:
                                return msg
                            else:
                                raise ValidationError(msg)

                        if not contact.id_queue or contact.queue_state != 'PENDIENTE':
                            """Comprovar primero los campos obligatorios del pedido antes de enviar el contacto."""
                            value = record.with_context(check_required_fields=True).send_a3erp_order()
                            if value == True:
                                contact_response = contact.action_a3erp_syncro()
                            else:
                                return value
                            
                            if contact_response == True:
                                record._log_and_continue(record, f"ALERTA: Contacto {contact.name} en la Cola de creación.")
                                record.queue_state = 'ESPERA'
                                continue
                            else:
                                msg = f"INCIDENCIA: Contacto {contact.name}: \n" + "Revisar contacto."

                            if waiting_function:
                                return msg
                            else:
                                raise ValidationError(msg)
                        else:
                            record._log_and_continue(record, f"ALERTA: Contacto {contact.name} en la Cola de creación.")
                        continue
                
                return record.send_a3erp_order()
            else:
                return record.send_a3erp_order()

    def send_a3erp_order(self):
        """Envia el pedido a la cola del Web Service para ser procesado y creado."""
        for record in self:
            productos_sin_codart = record.check_products_without_codart()
            if productos_sin_codart:
                return self._open_confirmation_wizard(productos_sin_codart, record)

            headers = {'Authorization': f'Bearer {record.company_id.a3erp_token}','Content-Type': 'application/json'}
            PLAN_FIELD_MAP = {
                self.env.ref('tl_conn_a3erp.analytic_plan_1').id: 'CENTROCOSTE',
                self.env.ref('tl_conn_a3erp.analytic_plan_2').id: 'CENTROCOSTE2',
                self.env.ref('tl_conn_a3erp.analytic_plan_3').id: 'CENTROCOSTE3',
            }
            cabecera_documento, lineas_documento = [],[]
            empty_mandatory_fields = [] # GUARDAR LOS CAMPOS DE ODOO QUE SON OBLIGATORIOS PASAR Y ESTAN VACIOS
            response = False
            break_record = False # SABER SI SALIR DE LA ITERACION ACTUAL
            record.a3erp_error_simple, record.a3erp_error_extend = "", ""

            required_cabeofv = record.env['a3erp.campos'].get_required_values_send(record.company_id.id, 'cabeofev')
            required_cabepedv = False
            a3erp_order_type = self.company_id.a3erp_sale_order_type # SI ENVIAMOS EL DOCUMENTO COMO OFERTA O COMO PEDIDO
            if a3erp_order_type == 'orders':
                required_cabepedv = record.env['a3erp.campos'].get_required_values_send(record.company_id.id, 'cabepedv')
                """SI ENVIAMOS COMO PEDIDO EXCLUIMOS EL CAMPO FECHA CADUCIDAD"""
                required_cabeofv = required_cabeofv.filtered(lambda field: field.a3erp_field_name != 'FECCADUCI')

            required_lineofer = record.env['a3erp.campos'].get_required_values_send(record.company_id.id, 'lineofer')
            # VALIDAR SI HAY ALGUN CAMPO ENTRADO EN LA VISTA DE CAMPOS
            if not required_cabeofv or not required_lineofer:
                self._log_and_continue(record, "No hay campos obligatorios informados para OFERTA/LINEOFER, revisar.")
                continue

            # /!\ CODCLI CABECERA
            """COGER Y/O COMPROVAR SI EL CLIENTE YA EXISTE EN A3ERP."""
            codcli_missing = False
            record_partner_id = record.partner_id.parent_id if record.partner_id.parent_id else record.partner_id # CLIENTE, YA SEA PADRE DEL CONTACTO o CLIENTE DEL PEDIDO
            if record_partner_id.is_company:
                if record_partner_id.cod_cliente_a3:
                    cabecera_documento.append(Parametro("CODCLI", cuadrar(record_partner_id.cod_cliente_a3), "STRING"))
                else:
                    codcli_missing = True
                    if not record_partner_id.check_contacts():
                        raise ValidationError(_("El Cliente debe tener almenos 1 Contacto para ser enviado a a3ERP."))
                    
            elif not record_partner_id.is_company and not record_partner_id.parent_id:
                raise ValidationError(_("El Contacto no esta asociado a ningún Cliente."))
                
            # if record_partner_id:
            #     if record_partner_id.parent_id.cod_cliente_a3:
            #         cabecera_documento.append(Parametro("CODCLI", cuadrar(record_partner_id.cod_cliente_a3), "STRING"))
            #     else:
            #         codcli_missing = True

            if codcli_missing:
                lista_parametros = record_partner_id.create_list_to_send()
                if not lista_parametros:
                    msg = "No se ha podido enviar la Oferta, revisar el Cliente."
                    raise ValidationError(msg)

            try:
                # AÑADIR KIT A LA CABECERA
                if self.is_kit:
                    kit_product = self._get_kit_product()
                    kis_desc = self.kit_description or False
                    if kit_product:
                        cabecera_documento.append(Parametro("KITCAB", kit_product, "STRING"))
                        if kis_desc:
                            cabecera_documento.append(Parametro("KITCABDESC", kis_desc, "STRING"))
                    else:
                        if not kit_product:
                            raise ValidationError(_("No se ha encontrado un producto KIT."))
                        else:
                            raise ValidationError(_("Cuando se envia un KIT tiene que haber una primera SECCION con la descripción del KIT."))

                # /!\ CAMPOS OFERTA CABECERA
                for field in required_cabeofv:
                    if field.odoo_field_name: # SI NO TIENE CAMPO DE ODOO, TIENE VALOR POR DEFECTO
                        if record[field.odoo_field_name]:
                            if field.relational_table:
                                if record[field.odoo_field_name][field.table_code]:
                                    campo_a3 = MAPPER.traducir_campo(record[field.odoo_field_name]._fields[field.table_code].type) # MAPPEAR EL TIPO DEL CAMPO
                                    if field.a3erp_field_name == 'IDDIRENT':
                                        cabecera_documento.append(Parametro(field.a3erp_field_name, record[field.odoo_field_name][field.table_code].replace('.', ','), "DECIMAL"))
                                    elif field.a3erp_field_name == 'CODPER':
                                        cabecera_documento.append(Parametro(field.a3erp_field_name, cuadrar(record[field.odoo_field_name][field.table_code]), campo_a3))
                                    else:
                                        cabecera_documento.append(Parametro(field.a3erp_field_name, record[field.odoo_field_name][field.table_code], campo_a3))
                                continue

                            campo_a3 = MAPPER.traducir_campo(record._fields[field.odoo_field_name].type) # MAPPEAR EL TIPO DEL CAMPO
                            if field.a3erp_field_name == 'NUMDOC':
                                solo_digitos = ''.join(filter(str.isdigit, str(record[field.odoo_field_name])))
                                cabecera_documento.append(
                                    Parametro(field.a3erp_field_name,solo_digitos,campo_a3)
                                )
                            elif "date" in record._fields[field.odoo_field_name].type:
                                fecha = convertir_fecha(record[field.odoo_field_name])
                                cabecera_documento.append(Parametro(field.a3erp_field_name, fecha, campo_a3))
                            else:
                                cabecera_documento.append(Parametro(field.a3erp_field_name, record[field.odoo_field_name], campo_a3))

                        elif not record[field.odoo_field_name] and field.mandatory_field:
                            empty_mandatory_fields.append(record.company_id.get_field_translations(field.odoo_field_name,record))
                            break_record = True

                    elif field.default_value:
                        default, campo_a3 = field.default_value.split('|',1)
                        cabecera_documento.append(Parametro(field.a3erp_field_name, default, campo_a3))

                # /!\ CAMPOS PEDIDO CABECERA
                if required_cabepedv:
                    for obj in cabecera_documento:
                        if obj.campo == 'FECHA':
                            obj.valor = convertir_fecha(datetime.now())
                            break

                    for field in required_cabepedv:
                        # SI NO TIENE CAMPO DE ODOO, TIENE VALOR POR DEFECTO
                        if field.odoo_field_name:
                            if field.a3erp_field_name in ('CENTROCOSTE','CENTROCOSTE2','CENTROCOSTE3'):
                                cuenta_analitica = True
                                continue
                            if record[field.odoo_field_name]:
                                if field.relational_table:
                                    if record[field.odoo_field_name][field.table_code]:
                                        campo_a3 = MAPPER.traducir_campo(record[field.odoo_field_name]._fields[field.table_code].type) # MAPPEAR EL TIPO DEL CAMPO
                                        cabecera_documento.append(Parametro(field.a3erp_field_name, record[field.odoo_field_name][field.table_code], campo_a3))
                                    continue

                                campo_a3 = MAPPER.traducir_campo(record._fields[field.odoo_field_name].type) # MAPPEAR EL TIPO DEL CAMPO
                                if field.a3erp_field_name == 'NUMDOC':
                                    solo_digitos = ''.join(filter(str.isdigit, str(record[field.odoo_field_name])))
                                    cabecera_documento.append(
                                        Parametro(field.a3erp_field_name,solo_digitos,campo_a3)
                                    )
                                # CONVERTIR FECHA
                                elif "date" in record._fields[field.odoo_field_name].type:
                                    fecha = convertir_fecha(record[field.odoo_field_name])
                                    cabecera_documento.append(Parametro(field.a3erp_field_name, fecha, campo_a3))
                                
                                # CAMPOS EXTRA DE CLIENTES: REQUIEREN TRATAMIENTO ESPECIAL
                                # APEN: CAMPO DE LA SERIE
                                elif 'pc_series_sale' in field.odoo_field_name:
                                    if record[field.odoo_field_name]:
                                        cabecera_documento.append(Parametro(field.a3erp_field_name, "PC", 'STRING'))
                                    continue
                                # APEN: PASAR EL CONTACTO
                                elif 'partner_id' in field.odoo_field_name:
                                    contact = record.contact_partner_id or record.partner_id
                                    cabecera_documento.append(Parametro(field.a3erp_field_name, contact.cod_contacto_a3, 'FLOAT'))
                                    cabecera_documento.append(Parametro('APEN_INFOCONTACTO', contact.name, 'STRING'))
                                # IN2: CAMPO FORMA DE ENTREGA
                                elif 'in2_delivery_type' in field.odoo_field_name:
                                    cabecera_documento.append(Parametro(field.a3erp_field_name, "IN2", "STRING"))
                                else:
                                    cabecera_documento.append(Parametro(field.a3erp_field_name, record[field.odoo_field_name], campo_a3))

                            # SI NO HAY VALOR, COMPROVAMOS SI HAY VALOR POR DEFECTO
                            elif field.default_value:
                                default, campo_a3 = field.default_value.split('|',1)
                                cabecera_documento.append(Parametro(field.a3erp_field_name, default, campo_a3))

                            elif not record[field.odoo_field_name] and field.mandatory_field:
                                empty_mandatory_fields.append(record.company_id.get_field_translations(field.odoo_field_name,record))
                                break_record = True

                        elif field.default_value:
                            default, campo_a3 = field.default_value.split('|',1)
                            cabecera_documento.append(Parametro(field.a3erp_field_name, default, campo_a3))

                if break_record:
                    fields = ', '.join(empty_mandatory_fields)
                    msg = f"Los siguientes campos de CABECERA son requeridos y estan vacíos: '{fields}'"
                    self._log_and_continue(record, msg)
                    raise ValidationError(_(msg))
                
                if self.env.context.get('check_required_fields'):
                    return True

                # NOTE: CAMPOS LINEA
                empty_mandatory_fields = []
                for line in sorted(record.order_line, key=lambda x: x.sequence, reverse=False):
                    linea = []
                    empty_codart = False # SABER SI SALIR DE LA ITERACION ACTUAL EN CASO DE CODART VACÍO
                    if line.display_type in ('line_section', 'line_subsection'): # SECCION
                        product = self._get_a3erp_section_product(line, record.company_id)
                        linea.append(Parametro("CODART", cuadrar(product.cod_articulo_a3), "STRING"))
                        linea.append(Parametro("DESCLIN", line.name, "STRING"))
                    elif line.display_type == 'line_note': # NOTA
                        partes = line.name.split('\n', 1)
                        linea.append(Parametro("CODART", cuadrar(record.company_id.a3erp_note_product_id.cod_articulo_a3), "STRING"))
                        if len(partes)>1:
                            linea.append(Parametro("TEXTO", line.name, "STRING"))
                        else:
                            linea.append(Parametro("DESCLIN", line.name, "STRING"))
                    else: # PRODUCTO
                        if not line.product_id.cod_articulo_a3:
                            self._log_and_continue(record, f"El Producto {line.product_id.name} no tiene un CODART de a3ERP.")
                            empty_codart = True
                        else:
                            linea.append(Parametro("CODART", cuadrar(line.product_id.cod_articulo_a3, 15), "STRING"))
                            cuenta_analitica = False
                            for field in required_lineofer:
                                if line[field.odoo_field_name]:
                                    campo_a3 = MAPPER.traducir_campo(line._fields[field.odoo_field_name].type) # MAPPEAR EL TIPO DEL CAMPO
                                    if record.company_id.module_is_installed(CANON_MODULE_NAME) and 'id_producto_padre' in field.odoo_field_name:
                                        linea.append(Parametro(field.a3erp_field_name, line[field.odoo_field_name], campo_a3))
                                        continue

                                    if 'name' in field.odoo_field_name:
                                        lines = line.name.split("\n")
                                        lang = record.partner_id.lang or self.env.user.lang or 'es_ES'
                                        
                                        first = lines[0] if len(lines) > 0 else ''
                                        second = lines[1] if len(lines) > 1 else False
                                        third = "\n".join(lines[2:]) if len(lines) > 2 else False
                                        
                                        if first != line.with_context(lang=lang).product_id.display_name:
                                            second = "\n".join(lines[1:]) if len(lines) > 1 else False
                                            short_description = first
                                            large_text = second
                                        else:
                                            short_description = second
                                            if not second:
                                                short_description = first
                                            large_text = third                                        
                                        
                                        if len(short_description) > 100:
                                            short_description = short_description[:100]
                                            large_text = short_description + "\n" + (large_text or "")
                                        
                                        linea.append(Parametro(field.a3erp_field_name, short_description, campo_a3))
                                        if large_text:
                                            linea.append(Parametro('TEXTO', large_text, campo_a3))
                                    else:
                                        if "analytic_distribution" in field.odoo_field_name and line[field.odoo_field_name]: # DISTRIBUCION ANALITICA
                                            cuenta_analitica = True
                                        else:
                                            linea.append(Parametro(field.a3erp_field_name, line[field.odoo_field_name], campo_a3))
                                
                                elif not line[field.odoo_field_name] and field.mandatory_field:
                                    empty_mandatory_fields.append(record.company_id.get_field_translations(field.odoo_field_name,line))
                                    break_record = True

                                elif 'price_unit' in field.odoo_field_name:
                                    campo_a3 = MAPPER.traducir_campo(line._fields[field.odoo_field_name].type) # MAPPEAR EL TIPO DEL CAMPO
                                    linea.append(Parametro(field.a3erp_field_name, line[field.odoo_field_name], campo_a3))

                                elif 'purchase_price' in field.odoo_field_name:
                                    campo_a3 = MAPPER.traducir_campo(line._fields[field.odoo_field_name].type)
                                    linea.append(Parametro(field.a3erp_field_name, line[field.odoo_field_name], campo_a3))

                            if cuenta_analitica: # SI LA CUENTA ANALITICA ES REQUERIDA
                                analytic_data = line.analytic_distribution 
                                if isinstance(analytic_data, dict) and analytic_data:
                                    AnalyticAccount = record.env['account.analytic.account']

                                    for key in analytic_data.keys():
                                        for id_str in key.split(','):
                                            if not id_str.strip().isdigit():
                                                continue

                                            analytic_account = (
                                                AnalyticAccount
                                                .browse(int(id_str))
                                                .exists()
                                            )

                                            if not analytic_account or not analytic_account.code:
                                                continue

                                            a3_field_name = PLAN_FIELD_MAP.get(analytic_account.plan_id.id)

                                            # Plan no relevante → ignorar
                                            if not a3_field_name:
                                                continue

                                            field = required_lineofer.filtered(lambda f: f.a3erp_field_name == a3_field_name)[:1]

                                            if field:
                                                linea.append(
                                                    Parametro(
                                                        field.a3erp_field_name,
                                                        analytic_account.code,
                                                        "STRING"
                                                    )
                                                )

                                    """# Limitamos a máximo 3 centros de coste
                                    analytic_ids = analytic_ids[:3]

                                    # Mapeamos cada cuenta al campo correspondiente
                                    # Obtenemos los fields relacionados a centros de coste en orden
                                    centro_fields = required_lineofer.filtered(lambda x: x.odoo_field_name == 'analytic_distribution')
                                    centro_fields = centro_fields[:len(analytic_ids)]  # Evitamos index error si hay menos de 3 fields configurados

                                    for field, analytic_id in zip(centro_fields, analytic_ids):
                                        analytic_account = record.env['account.analytic.account'].browse(analytic_id)
                                        if analytic_account and analytic_account.plan_id in valid_plans and analytic_account.code:
                                            linea.append(Parametro(field.a3erp_field_name, analytic_account.code, "STRING"))"""

                    lineas_documento.append(linea)

                #NOTE: CENTRO DE COSTE A NIVEL DE CABECERA
                if cuenta_analitica:
                    AnalyticAccount = record.env['account.analytic.account']

                    plan_values = {}

                    for line in record.order_line:
                        analytic_data = line.analytic_distribution

                        if not isinstance(analytic_data, dict) or not analytic_data:
                            continue

                        for key in analytic_data.keys():
                            for id_str in key.split(','):
                                if not id_str.strip().isdigit():
                                    continue

                                analytic_account = AnalyticAccount.browse(int(id_str)).exists()

                                if not analytic_account or not analytic_account.code:
                                    continue

                                plan_id = analytic_account.plan_id.id

                                if plan_id not in PLAN_FIELD_MAP:
                                    continue

                                plan_values.setdefault(plan_id, set()).add(analytic_account.code)

                    # Decidir qué enviar
                    for plan_id, codes in plan_values.items():
                        # Solo si hay UN único centro de coste
                        if len(codes) == 1:
                            code = next(iter(codes))
                            a3_field_name = PLAN_FIELD_MAP[plan_id]

                            field = required_cabepedv.filtered(
                                lambda f: f.a3erp_field_name == a3_field_name
                            )[:1]

                            if field:
                                cabecera_documento.append(
                                    Parametro(
                                        a3_field_name,
                                        code,
                                        "STRING"
                                    )
                                )                            
                         
                if empty_codart or break_record:
                    if break_record:
                        fields = ', '.join(empty_mandatory_fields)
                        msg = f"Los siguientes campos de LINEOFEV son requeridos y estan vacíos: '{fields}'"
                        self._log_and_continue(record, msg)
                        raise ValidationError(_(msg))
                    raise ValidationError(_("Hay un Articulo que no tiene nu CODART."))
                         
                else:
                    document_json = ''
                    if not codcli_missing:
                        ENTIDAD = ENTIDADOFERTA if a3erp_order_type == 'quotation' else ENTIDADPEDIDOS
                        NAX = NAX_OFERTAS if a3erp_order_type == 'quotation' else NAX_PEDIDOS
                        documento_post = MensajeSolicitudPostDocumento(record.company_id.a3erp_company_id, "ALTA", ENTIDAD, Documento(cabecera_documento, lineas_documento))
                        document_json = post_documento_to_json(documento_post)
                        response = requests.post(NAX.format(record.company_id.a3erp_url), json=document_json, verify=False, headers=headers, timeout=10)
                    else:
                        ENTIDAD = ENTIDADOFERTACLIENTE if a3erp_order_type == 'quotation' else ENTIDADPEDIDOSCLIENTE
                        NAX = NAX_OFERTAS_CLIENTES if a3erp_order_type == 'quotation' else NAX_PEDIDOS_CLIENTES
                        alta_cliente_documento = AltaDocumento(parametros=lista_parametros, documento=Documento(cabecera_documento, lineas_documento))
                        documento_post = MensajeSolicitudPostAltaYDocumento(record.company_id.a3erp_company_id, "ALTA", ENTIDAD, altaDocumento=alta_cliente_documento)
                        document_json = mensaje_solicitud_post_alta_y_documento_to_json(documento_post)
                        response = requests.post(NAX.format(record.company_id.a3erp_url), json=document_json, verify=False, headers=headers, timeout=10)

                    record.json_content_send = json_list_to_json_dump(document_json)

                if response.status_code == 200:  # CONSULTA AUTORIZADA
                    return_message = MensajeRetorno = json.loads(response.text)

                    # ACTUALIZAR CAMPOS SI EL MENSAJE ES SIN ERRORES
                    if return_message["message"] == "Sin Errores":
                        record.id_queue = return_message["result"]
                        record.queue_state = "PENDIENTE"
                        record.date_send = datetime.now()
                        self._log_and_continue(record, f"Respuesta a3ERP: {return_message['message']}")
                        if codcli_missing:
                            notification = {
                                'type': 'ir.actions.client',
                                'tag': 'display_notification',
                                'params': {
                                    'title': _('Warning'),
                                    'type': 'warning',
                                    'message': 'El Cliente no existe en a3ERP.\nSe han enviado los datos del Cliente junto con la Oferta.',
                                    'sticky': False,
                                }
                            }
                            return notification

                    elif return_message["message"] == "Error":
                        record.queue_state = "ERROR"
                        record.a3erp_error_simple = return_message["result"]
                        create_log.create_log(record,"WARNING","POSTDOCUMENTO",record._name,record.id,record.name,return_message["result"], record.company_id.id)

                elif response.status_code == 401:  # CONSULTA NO AUTORIZADA
                    record.queue_state = "ERROR"
                    record.a3erp_error_simple = "Unauthorized: Usuario o Contraseña erroneos o Token Expirado."

                elif response.status_code == 400:  # CONSULTA CON ERRORES DE ENVIO
                    return_message = json.loads(response.text)["errors"]
                    error_key = next((key for key in return_message.keys() if key != "mensaje"),None,)
                    record.a3erp_error_extend = json.dumps(return_message, indent=4) + '\n' + json.dumps(document_json, indent=4)
                    create_log.create_log(record,"ERROR","POSTDOCUMENTO",record._name,record.id,record.name,return_message[error_key][0], record.company_id.id)

            except Exception as e:
                _logger.error(format(e))
                create_log.create_log(record, "ERROR", "POSTDOCUMENTO", record._name, record.id, record.name, format(e), record.company_id.id)
                record.a3erp_error_extend = format(e)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Alerta'),
                        'type': 'warning',
                        'message': format(e),
                        'sticky': True,
                    }
                }

    def _get_a3erp_section_product(self, line, company):
        """Buscar el articulo seccion en ajustes."""
        if line.collapse_composition and company.a3erp_section_collapsed_product_id:
            return company.a3erp_section_collapsed_product_id
        return company.a3erp_section_product_id

    def get_cola_state(self):
        self.company_id.get_cola_state(self)

    def get_doc_values(self, idOfe):
        """Consultar Valores deL documento mediante el ID que recibimos.
        Args:
            idOfe (String): ID del documento.
        Returns:
            String: Devuelve el Número, Serie y Tipo contable del documento.
        """
        headers = {'Authorization': f'Bearer {self.company_id.a3erp_token}','Content-Type': 'application/json'}
        cola_state = MensajeSolicitudGet(self.company_id.a3erp_company_id, CAMPOS_CABECERA, str(idOfe))
        a3erp_order_type = self.company_id.a3erp_sale_order_type
        try:
            if a3erp_order_type == 'orders':
                response = requests.get(CONSULTA_PEDIDO.format(self.company_id.a3erp_url), json=cola_state.to_json(), verify=False, headers=headers, timeout=10)
            else:
                response = requests.get(CONSULTA_OFERTA.format(self.company_id.a3erp_url), json=cola_state.to_json(), verify=False, headers=headers, timeout=10)

            if response.status_code == 200: # CONSULTA SIN ERRORES
                return_message = MensajeRetorno = json.loads(response.text)

                if return_message['message'] == "Sin Errores":
                    result = return_message['result']
                    tipocont = result[0].get('TIPOCONT')
                    numdoc = int(result[0].get('NUMDOC'))
                    serie = result[0].get('SERIE')

                    return str(f"{tipocont}/{serie}/{numdoc}" if serie else f"{tipocont}//{numdoc}")

                elif return_message['message'] == "Error":
                    create_log.create_log(self, "ERROR", "GET", self._name, self.id, self.name, {return_message['result']}, self.company_id.id)

                elif response.status_code == 401: # CONSULTA NO AUTORIZADA
                    create_log.create_log(self, "ERROR", "GET", self._name, False, False, "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.")

            elif response.status_code == 400: # CONSULTA CON ERRORES DE ENVIO
                message = json.loads(response.text)['errors']
                error_key = next((key for key in message.keys() if key != 'mensaje'), None)
                self._log_and_continue(self, f"Error Consulta Cola: {message[error_key][0]}")
                create_log.create_log(self, "ERROR", "GET", self._name, self.id, self.name, format(e), self.company_id.id)

            return False

        except Exception as e:
            _logger.error(format(e))
            create_log.create_log(self, "ERROR", "GET", self._name, self.id, self.name, format(e), self.company_id.id)
            return False

    def check_products_without_codart(self):
        """Busca los productos que no tienen un CODART, osea, se han creado en Odoo
        Args:
            order_lines (List): Lineas del pedido.
        Returns:
            List: Lista de productos.
        """
        return self.order_line.filtered(lambda x: (x.product_template_id.cod_articulo_a3 == False or x.product_template_id.cod_articulo_a3) and x.product_template_id.queue_state in ('PENDIENTE', 'ERROR', False)).product_template_id

    def update_partner_codcli(self, codcli):
        """Actualiza la ficha del cliente cuando este se crea junto a la oferta.
        Args:
            codcli (String): CodCli que se ha generado.
        """
        partner_to_update = self.partner_id.parent_id if self.partner_id.parent_id else self.partner_id
        partner_to_update.write({
            'last_date_update': datetime.now(),
            'cod_cliente_a3': codcli,
            'queue_state': 'FINALIZADO'
        })

    def _get_kit_product(self):
        """Devuelve el producto kit a utilizar, según si es un kit Hardware o un kit normal."""
        kit_product = False

        value = any(line.product_id.carac2_id.cod_carac == 'SIS_KD' for line in self.order_line)
        if value:
            kit_product = self.env['product.template'].search([('cod_articulo_a3', '=', 'FORMHW')], limit=1).cod_articulo_a3
        else:
            kit_product = self.env['product.template'].search([('cod_articulo_a3', '=', 'FORM')], limit=1).cod_articulo_a3

        return kit_product

    def write(self, values):
        """Tener en cuenta la plantilla de presupuesto y cliente para que recaulcule los precios y descuentos."""
        result = super(SaleOrder, self).write(values)

        if 'sale_order_template_id' in values:
            self.order_line.with_context(recompute=True)._onchange_product_id_uom_qty()            

        return result

    @api.onchange('partner_id')
    def _onchange_partner_id_show_update_price_buton(self):
        # Mostrar el boton para actualizar precios
        self.show_update_partner = bool(self.order_line)
        
        # Consultar el riesgo del cliente
        if not self.partner_id:
            self.a3erp_credit = 0.0
            self.a3erp_max_credit= 0.0
            return

        try:
            riesgo_data = self.partner_id.get_a3erp_riesgo_cliente()
            if not riesgo_data:
                return

            self.a3erp_credit = riesgo_data.get('riesgo_consumido', 0.0)
            self.a3erp_max_credit= riesgo_data.get('riesgo_maximo', 0.0)
            
        except Exception as e:
            _logger.error(
                "Error A3ERP Situación Riesgo: %s",
                format(e),
            )
    
    @api.depends('a3erp_credit', 'a3erp_max_credit')
    def _compute_credit_display(self):
        for order in self:
            order.credit_exceeded= order.a3erp_credit > order.a3erp_max_credit
            
            color_class = 'class="text-danger"' if order.credit_exceeded else 'class="text-success"'

            order.credit_display = (
                f"<h6 {color_class}><strong>Consumido: {order.a3erp_credit:,.2f} € / "
                f"Máximo: {order.a3erp_max_credit:,.2f} €</strong></h6>"
            )
        
    @api.constrains('queue_state')
    def _check_state(self):
        for record in self:
            if not record.a3erp_active_company:
                return
            if record.queue_state == 'ERROR' and record.id_queue:
                template = self.env.ref('tl_conn_a3erp.email_template_sale_order_queue_error_user_id')
                if template:
                    template.sudo().send_mail(record.id, force_send=True)

    def unlink(self):
        """Heredado. No permitir borrar el documento si ya esta enviado a a3ERP.
        Raises:
            UserError: Error.
        Returns:
            Super: Super
        """
        for order in self:
            if order.ref_ofev_a3:
                raise UserError('No se puede borrar esta Documento de Venta. Ya ha estado vinculada con un Documento de A3ERP.')
        return super(SaleOrder, self).unlink()

    def action_recompute_order_lines_price(self):
        self.order_line.with_context(recompute=True)._onchange_product_id_uom_qty()
        self.show_update_partner = False
        
class SaleOrderLine(models.Model):
    _inherit = ['sale.order.line']

    product_state = fields.Selection(related='product_template_id.queue_state',readonly=True,store=True)
    codart_product = fields.Char(related='product_template_id.cod_articulo_a3',readonly=True,store=True)

    def get_product_stock(self):
       return self.product_id.get_product_detail_stock()    
   
    def write(self, values):
        """Tener en cuenta la plantilla de presupuesto y cliente para que recalcule los precios y descuentos."""
        result = super(SaleOrderLine, self).write(values)
            
        return result
       
    @api.onchange('product_id','product_uom_qty')
    def _onchange_product_id_uom_qty(self):
        context = dict(self.env.context or {})
        if self and not self[0].order_id.a3erp_active_company:
            return
        for line in self:
            if not line.product_id:
                continue
            # SIEMPRE EJECUTAR SI SE MODIFICA EL product_id AUNQUE a3erp_price_policy NO ESTE ACTIVADO
            if self._origin and self._origin.product_id != line.product_id:
                values = line._get_product_price_discount()
                if not values:
                    continue
                elif 'tag' in values:
                    return {
                        'warning': {
                            'title': 'Warning',
                            'message': values.get('params', {}).get('message', 'Error desconocido'),
                        }
                    }
                elif values:
                    price = values.get('PRECIO', 0.0)
                    discount = values.get('DESC1', 0.0)
                    line.write({
                        'price_unit': price,
                        'discount': discount,
                        'margin_percent': (line.product_id.a3erp_product_margin / 100) or 0.0
                    })
                    # DEPENDE DEL MODULO sale_triple_discount
                    if 'discount2' in self.env['sale.order.line']._fields:
                        line.discount2 = values.get('DESC2', 0.0)
                        line.discount3 = values.get('DESC3', 0.0)

            # MANTENER VERSION ORIGINAL 
            if not line.ids or (line.ids and line.company_id.a3erp_price_policy) or context.get('recompute', False):
                values = line._get_product_price_discount()
                if not values:
                    continue
                elif 'tag' in values:
                    return {
                        'warning': {
                            'title': 'Warning',
                            'message': values.get('params', {}).get('message', 'Error desconocido'),
                        }
                    }
                elif values:
                    price = values.get('PRECIO', 0.0)
                    discount = values.get('DESC1', 0.0)
                    line.write({
                        'price_unit': price,
                        'discount': discount,
                        'margin_percent': (line.product_id.a3erp_product_margin / 100) or 0.0
                    })
                    # DEPENDE DEL MODULO sale_triple_discount
                    if 'discount2' in self.env['sale.order.line']._fields:
                        line.discount2 = values.get('DESC2', 0.0)
                        line.discount3 = values.get('DESC3', 0.0)
                
    def _get_product_price_discount(self):
        """Obtener el precio de venta y descuento del producto mediante a3ERP."""

        partner_id = self.order_partner_id.parent_id if self.order_partner_id.parent_id else self.order_partner_id
        
        cod_articulo = self.product_id.cod_articulo_a3
        cod_cliente = partner_id.cod_cliente_a3
        pricelist_code = partner_id.cod_tarifa_a3

        if not cod_articulo or not cod_cliente or not pricelist_code:
            return False


        headers = {'Authorization': f'Bearer {self.company_id.a3erp_token}','Content-Type': 'application/json'}
        list_parametros = []

        list_parametros.append(Parametro("CODCLI", cuadrar(cod_cliente), "STRING"))
        list_parametros.append(Parametro("CODART", cuadrar(cod_articulo, 15), "STRING"))
        list_parametros.append(Parametro("TARIFA", cuadrar(pricelist_code), "STRING"))
        list_parametros.append(Parametro("MONEDA", "EURO", "STRING"))
        list_parametros.append(Parametro("UNIDADES", self.product_uom_qty, "FLOAT"))
        list_parametros.append(Parametro("FECHA", datetime.now().strftime("%d/%m/%Y"), "STRING"))

        try:
            get_prcventa = MensajeSolicitudGetParams(self.company_id.a3erp_company_id, list_parametros)
            response = requests.get(GET_PRECIOVENTA.format(self.company_id.a3erp_url), json=get_prcventa.to_json(), verify=False, headers=headers, timeout=3)
            if response.status_code == 200:
                return_message = MensajeRetorno = json.loads(response.text)

                if return_message['message'] == "Sin Errores":
                    result = return_message['result'][0]
                    return result

                elif return_message['message'] == "Error":
                    create_log.create_log(self, "WARNING", "POST", self._name, self.id, self.name, return_message['result'], self.company_id.id)
                    raise UserError(_("Error al obtener el precio de venta del producto: %s") % format(return_message['result']))

            elif response.status_code == 400:
                return_message = json.loads(response.text)['errors']
                error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
                _logger.error(return_message[error_key][0])
                create_log.create_log(self, "ERROR", "POST", self._name, self.id, self.name, return_message[error_key][0], self.company_id.id)

            elif response.status_code == 401:
                msg = "Unauthorized: Usuario o Contraseña erroneos o Token Expirado."
                create_log.create_log(self, "ERROR", "POST", self._name, self.id, self.name, msg, self.company_id.id)
                _logger.error(msg)
                #self.order_id.message_post(message_type='comment', body=msg)

        except Exception as e:
            _logger.error(format(e))
            #self.order_id.message_post(message_type='comment', body=format(e))
            return { 
                'type' : 'ir.actions.client' , 
                'tag' : 'display_notification' , 
                'params' : { 
                    'title' : 'Warning' , 
                    'message' : f'Error Obteniendo el precio: {format(e)}' , 
                    'type' : 'warning' , 
                    'sticky' : True , 
                } , 
            }
            return "ConnectTimeoutError"
            #raise UserError(_("Error al obtener el precio de venta del producto: %s") % format(e))

        return False
