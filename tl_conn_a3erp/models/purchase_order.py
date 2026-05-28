from odoo.exceptions import MissingError, UserError, ValidationError
from odoo import fields,models,api, _
from .web_service import *
from . import create_log
from .mapper_campos import TypeMapper
import requests, json, logging

_logger = logging.getLogger(__name__)

NAX_PEDIDOS = "{}/pedidoc/nax"
NAX_ALBARANES = "{}/albaranc/nax"
#NAX_PEDIDOS_CLIENTES = "{}/pedidoc/naxCliente&Documento"
ESTADO_COLA = "{}/cola/getEstadoCola"
CONSULTA_PEDIDOC = "{}/pedidoc/getbycode"
CONSULTA_ALBARANC = "{}/albaranc/getbycode"
CONSULTA_FACTURASC = "{}/Facturac/getlineasbyidpedc"
CAMPOS_CABECERA = ["CABECERA.TIPOCONT","CABECERA.NUMDOC", "CABECERA.SERIE"]
MAPPER = TypeMapper()

class PurchaseOrder(models.Model):
    _inherit = ['purchase.order']

    a3erp_active_company = fields.Boolean(
        related="company_id.a3erp_active_company",
        readonly=True,
    )
    ref_ofev_a3 = fields.Char(string='Nº documento a3ERP', help="Tipo/Serie/Nº Documento", copy=False)
    id_document = fields.Char(string='ID del Documento Generado', help="Id interno del documento generado en a3ERP.", copy=False)
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
    allow_send = fields.Boolean(string='Permitir enviar a a3ERP', compute="_compute_allow_send", store=False)
    
    @api.depends('partner_id')
    def _compute_allow_send(self):
        for record in self:
            record.allow_send = bool(record.partner_id.cod_proveed_a3)
    
    def _log_and_continue(self, record, message):
        """Publica un mensaje y continúa."""
        record.message_post(message_type='comment', body=message)
    
    def get_cola_state(self):
        self.company_id.get_cola_state(self)
        
    def unlink(self):
        """No permitir borrar el documento si ya esta enviado a a3ERP."""
        for order in self:
            if order.ref_ofev_a3:
                raise UserError('No se puede borrar esta Oferta de Venta. Ya ha estado vinculada con un Documento de A3ERP.')
        return super(PurchaseOrder, self).unlink()

    def send_a3erp_purchase_order(self):
        """Envía el pedido de compra a la cola del Web Service para ser procesado y creado en a3ERP."""

        for record in self:
            headers = {
                'Authorization': f'Bearer {record.company_id.a3erp_token}',
                'Content-Type': 'application/json'
            }
            PLAN_FIELD_MAP = {
                self.env.ref('tl_conn_a3erp.analytic_plan_1').id: 'CENTROCOSTE',
                self.env.ref('tl_conn_a3erp.analytic_plan_2').id: 'CENTROCOSTE2',
                self.env.ref('tl_conn_a3erp.analytic_plan_3').id: 'CENTROCOSTE3',
            }
            cabecera_documento = []
            lineas_documento = []
            empty_mandatory_fields = []
            response = False
            cuenta_analitica = False
            
            record.a3erp_error_simple = ""
            record.a3erp_error_extend = ""

            # Validar proveedor
            if not record.partner_id.cod_proveed_a3:
                raise ValidationError(_("El proveedor no tiene un código de proveedor a3ERP configurado."))

            cabecera_documento.append(Parametro("CODPRO", cuadrar(record.partner_id.cod_proveed_a3), "STRING"))

            # Obtener campos requeridos de cabecera y líneas
            required_cabepedc = record.env['a3erp.campos'].get_required_values_send(record.company_id.id, 'cabepedc')
            #TODO: De momento no coger los ID relacionales del CANON.
            required_lineofer = record.env['a3erp.campos'].get_required_values_send(record.company_id.id, 'lineofer').filtered(lambda x: x.line_field_use in ('purchase', '', False))

            if not required_cabepedc or not required_lineofer:
                raise ValidationError(_("Faltan campos requeridos para Cabecera o Lineas en la configuración de a3ERP."))

            # Procesar CABEPEDC (cabecera)
            for field in required_cabepedc:
                if field.odoo_field_name:
                    if field.a3erp_field_name in ('CENTROCOSTE','CENTROCOSTE2','CENTROCOSTE3'):
                        cuenta_analitica = True
                        continue
                    valor = record[field.odoo_field_name]
                    if valor:
                        if field.relational_table:
                            related = valor[field.table_code]
                            campo_a3 = MAPPER.traducir_campo(valor._fields[field.table_code].type)
                            cabecera_documento.append(Parametro(field.a3erp_field_name, related, campo_a3))
                        else:
                            campo_a3 = MAPPER.traducir_campo(record._fields[field.odoo_field_name].type)
                            if field.a3erp_field_name == 'NUMDOC':
                                solo_digitos = ''.join(filter(str.isdigit, str(valor)))
                                cabecera_documento.append(
                                    Parametro(field.a3erp_field_name,solo_digitos,campo_a3)
                                )
                            elif "date" in record._fields[field.odoo_field_name].type:
                                fecha = convertir_fecha(valor)
                                cabecera_documento.append(Parametro(field.a3erp_field_name, fecha, campo_a3))
                            else:
                                cabecera_documento.append(Parametro(field.a3erp_field_name, valor, campo_a3))
                    elif field.mandatory_field:
                        empty_mandatory_fields.append(record.company_id.get_field_translations(field.odoo_field_name, record))
                elif field.default_value:
                    default, campo_a3 = field.default_value.split('|', 1)
                    cabecera_documento.append(Parametro(field.a3erp_field_name, default, campo_a3))

            if empty_mandatory_fields:
                fields = ', '.join(empty_mandatory_fields)
                raise ValidationError(_(f"Los siguientes campos de CABEPEDC son requeridos y están vacíos: '{fields}'"))

            # Procesar líneas (LINEOFER)
            empty_mandatory_fields = []
            for line in sorted(record.order_line, key=lambda x: x.sequence):
                if not line.product_id.cod_articulo_a3:
                    productos_sin_codart = record.check_products_without_codart()
                    return self._open_confirmation_wizard(productos_sin_codart, record)
                    #raise ValidationError(_("El producto '%s' no tiene CODART configurado.") % line.product_id.display_name)

                linea = [Parametro("CODART", cuadrar(line.product_id.cod_articulo_a3, 15), "STRING")]
                cuenta_analitica = False    
                for field in required_lineofer:
                    if field.odoo_field_name:
                        valor = line[field.odoo_field_name]
                        if "analytic_distribution" in field.odoo_field_name and line[field.odoo_field_name]: # DISTRIBUCION ANALITICA
                            cuenta_analitica = True                            
                        elif valor:
                            campo_a3 = MAPPER.traducir_campo(line._fields[field.odoo_field_name].type)
                            linea.append(Parametro(field.a3erp_field_name, valor, campo_a3))
                        elif field.mandatory_field:
                            empty_mandatory_fields.append(record.company_id.get_field_translations(field.odoo_field_name, line))
                            
                    elif field.default_value:
                        default, campo_a3 = field.default_value.split('|', 1)
                        linea.append(Parametro(field.a3erp_field_name, default, campo_a3))
                    
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

                        field = required_cabepedc.filtered(
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
                            
            if empty_mandatory_fields:
                fields = ', '.join(empty_mandatory_fields)
                raise ValidationError(_(f"Los siguientes campos de LINEOFER son requeridos y están vacíos: '{fields}'"))

            try:                      
                documento_post = MensajeSolicitudPostDocumento(
                    record.company_id.a3erp_company_id,
                    "ALTA",
                    ENTIDADPEDIDOSC if record.company_id.a3erp_purchase_order_type == 'purchase' else ENTIDADALBARANESC,
                    Documento(cabecera_documento, lineas_documento)
                )
                
                url = NAX_ALBARANES if record.company_id.a3erp_purchase_order_type == 'picking' else NAX_PEDIDOS
                
                document_json = post_documento_to_json(documento_post)
                response = requests.post(url.format(record.company_id.a3erp_url),
                                        json=document_json,
                                        verify=False,
                                        headers=headers,
                                        timeout=10)

                record.json_content_send = json_list_to_json_dump(document_json)

                if response.status_code == 200:
                    return_message = json.loads(response.text)
                    
                    if return_message["message"] == "Sin Errores":
                        record.id_queue = return_message["result"]
                        record.queue_state = "PENDIENTE"
                        self._log_and_continue(record, f"Respuesta a3ERP: {return_message['message']}")
                        record.date_send = datetime.now()
                        
                    elif return_message["message"] == "Error":
                        record.queue_state = "ERROR"
                        record.a3erp_error_simple = return_message["result"]
                        create_log.create_log(record, "ERROR", "POSTDOCUMENTO", record._name, record.id, record.name, return_message["result"], record.company_id.id)

                elif response.status_code == 401:
                    record.queue_state = "ERROR"
                    record.a3erp_error_simple = "Unauthorized: Token expirado o incorrecto."

                elif response.status_code == 400:
                    return_message = json.loads(response.text)["errors"]
                    error_key = next((key for key in return_message.keys() if key != "mensaje"), None)
                    record.a3erp_error_extend = json.dumps(return_message, indent=4) + '\n' + json.dumps(document_json, indent=4)
                    create_log.create_log(record, "ERROR", "POSTDOCUMENTO", record._name, record.id, record.name, return_message[error_key][0], record.company_id.id)

            except Exception as e:
                _logger.exception("Error enviando pedido de compra a a3ERP: %s", e)
                record.queue_state = "ERROR"
                record.a3erp_error_extend = str(e)
                create_log.create_log(record, "ERROR", "POSTDOCUMENTO", record._name, record.id, record.name, str(e), record.company_id.id)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Alerta'),
                        'type': 'warning',
                        'message': str(e),
                        'sticky': True,
                    }
                }

    
    def check_products_without_codart(self):
        """Busca los productos que no tienen un CODART, osea, se han creado en Odoo
        Args:
            order_lines (List): Lineas del pedido.
        Returns:
            List: Lista de productos.
        """
        return self.order_line.filtered(lambda x: (x.product_id.cod_articulo_a3 == False or x.product_id.cod_articulo_a3) and x.product_id.queue_state in ('PENDIENTE', 'ERROR', False)).product_id
    
    def _open_confirmation_wizard(self, productos_sin_codart, record):
        """Abre el asistente de confirmación cuando faltan códigos de artículo en productos."""
        templates = productos_sin_codart.mapped('product_tmpl_id')
        lista = '\n'.join(f"- {x.name}" for x in templates)
        value = self.env['sale.confirmation.wizard'].sudo().create({'message': f'{lista}'})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirmar Acción',
            'res_model': 'sale.confirmation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'productos_sin_codart': templates.ids, 'model_name': record._name,'purchase_order_id': record.id},
            'res_id': value.id
        }
    
    def process_waiting_purchase(self):
        """Recibimos todos los pedidos en estado por de ESPERA, si sus articulos ya se han creado en a3, se envia a la cola."""
        for purchase in self:
            context = self.env.context.get("automatic") # LA EJECUCION ES DEL CRON O MANUAL DESDE EL DOCUMENTO
            products_sin_codart = purchase.check_products_without_codart()
            if context:
                if not products_sin_codart:
                    response = purchase.with_context(waiting_function=True).send_a3erp_purchase_order()
                    if response:
                        if "type" in response:
                            continue
                        purchase._log_and_continue(purchase, response)
                elif not purchase.check_waiting_sales:
                    purchase._log_and_continue(purchase, "Hay productos pendientes de crearse en a3ERP.")
                    purchase.check_waiting_sales = True
            else:
                if not products_sin_codart:
                    response =  purchase.with_context(waiting_function=True).send_a3erp_purchase_order()

                    if response and 'params' in response:
                        raise ValidationError(response['params']['message'])
                else:
                    raise MissingError("Hay productos pendientes de crearse en a3ERP.")
                
    def get_doc_values(self, idOfe):
        """Consultar Valores deL documento mediante el ID que recibimos.
        Args:
            idOfe (String): ID del documento.
        Returns:
            String: Devuelve el Número, Serie y Tipo contable del documento.
        """
        headers = {'Authorization': f'Bearer {self.company_id.a3erp_token}','Content-Type': 'application/json'}
        cola_state = MensajeSolicitudGet(self.company_id.a3erp_company_id, CAMPOS_CABECERA, str(idOfe))
        url = CONSULTA_ALBARANC if self.company_id.a3erp_purchase_order_type == 'picking' else CONSULTA_PEDIDOC
        
        try:
            response = requests.get(url.format(self.company_id.a3erp_url), json=cola_state.to_json(), verify=False, headers=headers, timeout=10)           

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
    
    def get_invoice_lines_summary(self, id_pedc, fields=["*"]):
        """
        Consulta las líneas de factura asociadas a un IDPEDC y devuelve un sumatorio
        de los campos: PRCMONEDA, UNIDADES, TIPIVA y BASEMONEDA.
        """

        self.ensure_one()

        headers = {
            'Authorization': f'Bearer {self.company_id.a3erp_token}',
            'Content-Type': 'application/json'
        }

        url = CONSULTA_FACTURASC.format(self.company_id.a3erp_url)
        payload = MensajeSolicitudGet(self.company_id.a3erp_company_id, fields, str(id_pedc))

        try:
            response = requests.get(
                url,
                json=payload.to_json(),
                verify=False,
                headers=headers,
                timeout=5
            )

            if response.status_code == 200:
                data = json.loads(response.text)

                if data.get("message") != "Sin Errores":
                    create_log.create_log(
                        self, "ERROR", "GET",
                        self._name, self.id, self.name,
                        data.get("result"), self.company_id.id
                    )
                    return False

                result_lines = data.get("result", [])

                total_precio = 0.0
                total_unidades = 0.0
                total_base = 0.0
                total_calculado = 0.0
                iva_breakdown = {}

                for line in result_lines:
                    precio = float(line.get("PRCMONEDA") or 0.0)
                    unidades = float(line.get("UNIDADES") or 0.0)
                    base = float(line.get("BASEMONEDA") or 0.0)
                    tipiva = line.get("TIPIVA") or "SIN_IVA"

                    total_precio += precio
                    total_unidades += unidades
                    total_base += base
                    total_calculado += precio * unidades

                    if tipiva not in iva_breakdown:
                        iva_breakdown[tipiva] = {
                            "base": 0.0,
                            "unidades": 0.0,
                            "total": 0.0,
                        }

                    iva_breakdown[tipiva]["base"] += base
                    iva_breakdown[tipiva]["unidades"] += unidades
                    iva_breakdown[tipiva]["total"] += precio * unidades

                return {
                    "total_precio": total_precio,
                    "total_unidades": total_unidades,
                    "total_base": total_base,
                    "total_calculado": total_calculado,
                    "iva_breakdown": iva_breakdown,
                }

            elif response.status_code == 401:
                create_log.create_log(
                    self, "ERROR", "GET",
                    self._name, self.id, self.name,
                    "Unauthorized: Token expirado o incorrecto.",
                    self.company_id.id
                )
                return False

            elif response.status_code == 400:
                error_data = json.loads(response.text)
                create_log.create_log(
                    self, "ERROR", "GET",
                    self._name, self.id, self.name,
                    json.dumps(error_data, indent=4),
                    self.company_id.id
                )
                return False

            return False

        except Exception as e:
            _logger.exception("Error consultando líneas de factura por IDPEDC: %s", e)
            create_log.create_log(
                self, "ERROR", "GET",
                self._name, self.id, self.name,
                str(e), self.company_id.id
            )
            return False