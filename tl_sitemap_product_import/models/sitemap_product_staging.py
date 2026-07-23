import logging

import requests

from odoo import _, api, fields, models
from odoo.addons.queue_job.exception import RetryableJobError

_logger = logging.getLogger(__name__)


class SitemapProductStaging(models.Model):
    _name = 'sitemap.product.staging'
    _description = 'Producto en vista previa (pendiente de selección/importación)'
    _order = 'id asc'
    _rec_name = 'url'

    batch_id = fields.Many2one('sitemap.import.batch', string='Lote', required=True, ondelete='cascade')
    source_id = fields.Many2one(
        'sitemap.import.source', string='Fuente', related='batch_id.source_id', store=True, index=True)
    url = fields.Char(string='URL', required=True, index=True)
    sitemap_lastmod = fields.Datetime(string='Última modificación (sitemap)')

    state = fields.Selection([
        ('pending', 'Pendiente de vista previa'),
        ('queued_preview', 'Vista previa en cola'),
        ('previewing', 'Obteniendo vista previa'),
        ('preview_ready', 'Vista previa lista'),
        ('queued_import', 'Importación en cola'),
        ('importing', 'Importando'),
        ('imported', 'Importado'),
        ('skipped', 'Sin cambios'),
        ('error', 'Error'),
    ], string='Estado', default='pending', index=True)
    result = fields.Selection([
        ('created', 'Creado'),
        ('updated', 'Actualizado'),
    ], string='Resultado')

    # Datos ligeros de vista previa: solo texto/números, nunca contenido binario.
    # La URL de la imagen principal se guarda como referencia (texto), pero su
    # contenido NO se descarga hasta que el producto se importa de verdad.
    name = fields.Char(string='Nombre')
    list_price = fields.Float(string='Precio')
    price_available = fields.Boolean(
        string='Precio publicado', default=True, required=True,
        help='Indica si la fuente publicó un precio fiable. Si no lo publicó, '
             'las actualizaciones conservan el precio que ya tenga el producto en Odoo.')
    currency_name = fields.Char(string='Moneda')
    category_path = fields.Char(string='Categoría (ruta)')
    style_code = fields.Char(string='Código de estilo')
    color_code = fields.Char(string='Código de color')
    description_preview = fields.Text(string='Descripción')
    short_description_preview = fields.Text(string='Descripción breve')
    full_description_preview = fields.Html(string='Descripción ampliada')
    attributes_json = fields.Text(
        string='Atributos técnicos (JSON)', readonly=True,
        help='Atributos informativos recuperados de la ficha, por ejemplo Escala 1:32.')
    product_length = fields.Float(string='Longitud del producto', readonly=True)
    product_height = fields.Float(string='Altura del producto', readonly=True)
    product_width = fields.Float(string='Anchura del producto', readonly=True)
    dimensional_uom_name = fields.Char(
        string='Unidad dimensional', readonly=True,
        help='Unidad común de longitud, altura y anchura que se aplicará mediante product_dimension.')
    packaging_length = fields.Float(string='Longitud del embalaje', readonly=True)
    packaging_height = fields.Float(string='Altura del embalaje', readonly=True)
    packaging_width = fields.Float(string='Anchura del embalaje', readonly=True)
    packaging_weight = fields.Float(string='Peso del embalaje', readonly=True)
    packaging_dimensional_uom_name = fields.Char(
        string='Unidad dimensional del embalaje', readonly=True)
    packaging_weight_uom_name = fields.Char(
        string='Unidad de peso del embalaje', readonly=True)
    main_image_url = fields.Char(string='URL imagen principal (no descargada)')
    image_urls_json = fields.Text(string='URLs de imágenes (JSON)', readonly=True)
    attachment_urls_json = fields.Text(string='Documentos detectados (JSON)', readonly=True)
    attachment_count = fields.Integer(string='Número de documentos', readonly=True)
    ean = fields.Char(
        string='EAN único', readonly=True,
        help='Solo se informa cuando la ficha publica exactamente un GTIN válido.')
    ean_count = fields.Integer(string='Número de EAN', readonly=True)
    ean_checked = fields.Boolean(
        string='EAN comprobado', readonly=True,
        help='La fuente fue consultada correctamente, aunque no publicara ningún EAN.')
    ean_variants_json = fields.Text(string='EAN por variante (JSON)', readonly=True)

    product_tmpl_id = fields.Many2one('product.template', string='Producto Odoo enlazado', readonly=True)
    error_message = fields.Text(string='Mensaje de error')
    preview_attempt_count = fields.Integer(
        string='Intentos de vista previa', readonly=True, default=0,
        help='Número de veces que se ha intentado procesar esta URL.')
    last_attempt_date = fields.Datetime(string='Último intento', readonly=True)
    preview_date = fields.Datetime(string='Fecha de vista previa')
    imported_date = fields.Datetime(string='Fecha de importación')

    preview_job_uuid = fields.Char(string='Trabajo de vista previa', readonly=True, copy=False)
    import_job_uuid = fields.Char(string='Trabajo de importación', readonly=True, copy=False)
    last_job_date = fields.Datetime(string='Último trabajo', readonly=True, copy=False)

    _batch_url_uniq = models.Constraint(
        'unique(batch_id, url)',
        message='Esta URL ya está en este lote.',
    )

    def _queue_identity(self, phase):
        self.ensure_one()
        return f"sitemap_product_{phase}_{self.id}"

    @staticmethod
    def _retryable_exception(exc):
        if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
            return True
        response = getattr(exc, 'response', None)
        return getattr(response, 'status_code', None) in {429, 500, 502, 503, 504}

    def action_queue_preview(self):
        jobs = 0
        for row in self:
            if row.state not in ('pending', 'error'):
                continue
            row.write({
                'state': 'queued_preview',
                'error_message': False,
                'last_job_date': fields.Datetime.now(),
            })
            job = row.with_delay(
                priority=20,
                max_retries=max(row.source_id.http_retry_count or 3, 1),
                identity_key=row._queue_identity('preview'),
                description=_('Vista previa sitemap: %s') % row.url,
            )._job_fetch_preview()
            row.preview_job_uuid = job.uuid
            jobs += 1
        return self._notification(
            _('Vistas previas en cola'),
            _('%s productos se han enviado a la cola.') % jobs,
        )

    def _job_fetch_preview(self):
        self.ensure_one()
        row = self.exists()
        if not row:
            return False
        row.write({
            'state': 'previewing',
            'last_job_date': fields.Datetime.now(),
            'error_message': False,
        })
        service = row.env[row.source_id.connector_model]
        try:
            service.refresh_staging_row(
                row,
                row.source_id,
                image_map={},
                force=row.batch_id.force_update,
            )
            if row.state == 'error' and any(
                token in (row.error_message or '')
                for token in ('HTTP 429', 'HTTP 500', 'HTTP 502', 'HTTP 503', 'HTTP 504', 'Timeout', 'ConnectionError')
            ):
                row.write({'state': 'queued_preview'})
                raise RetryableJobError(row.error_message or _('Error HTTP temporal.'))
        except RetryableJobError:
            raise
        except Exception as exc:
            if row._retryable_exception(exc):
                row.write({'state': 'queued_preview', 'error_message': str(exc)[:4000]})
                raise RetryableJobError(str(exc)) from exc
            row.write({
                'state': 'error',
                'error_message': ('%s: %s' % (exc.__class__.__name__, exc))[:4000],
                'last_attempt_date': fields.Datetime.now(),
            })
            raise
        row.batch_id._update_queue_completion()
        return True

    def action_import_selected(self):
        jobs = 0
        for row in self:
            if row.state not in ('preview_ready', 'error', 'imported'):
                continue
            if not row.name:
                continue
            row.write({
                'state': 'queued_import',
                'error_message': False,
                'last_job_date': fields.Datetime.now(),
            })
            job = row.with_delay(
                priority=30,
                max_retries=max(row.source_id.http_retry_count or 3, 1),
                identity_key=row._queue_identity('import'),
                description=_('Importar producto sitemap: %s') % (row.name or row.url),
            )._job_import_product()
            row.import_job_uuid = job.uuid
            jobs += 1
        return self._notification(
            _('Importación en cola'),
            _('%s productos se han enviado a la cola de importación.') % jobs,
        )

    def _job_import_product(self):
        self.ensure_one()
        row = self.exists()
        if not row:
            return False
        row.write({
            'state': 'importing',
            'last_job_date': fields.Datetime.now(),
            'error_message': False,
        })
        connector = row.env[row.source_id.connector_model]
        try:
            result = connector.import_staging_row(row, row.source_id, [])
            if result == 'error':
                raise ValueError(row.error_message or _('Error importando el producto.'))
        except Exception as exc:
            if row._retryable_exception(exc):
                row.write({'state': 'queued_import', 'error_message': str(exc)[:4000]})
                raise RetryableJobError(str(exc)) from exc
            row.write({
                'state': 'error',
                'error_message': ('%s: %s' % (exc.__class__.__name__, exc))[:4000],
            })
            raise
        row.batch_id._update_queue_completion()
        return result


    def _missing_job_rows(self):
        """Return rows whose queue state points to a job that no longer exists."""
        QueueJob = self.env['queue.job'].sudo()
        rows = self.filtered(lambda row: row.state in (
            'queued_preview', 'previewing', 'queued_import', 'importing'))
        uuids = set(filter(None, rows.mapped('preview_job_uuid') + rows.mapped('import_job_uuid')))
        existing_uuids = set(QueueJob.search([('uuid', 'in', list(uuids))]).mapped('uuid')) if uuids else set()
        missing = self.env['sitemap.product.staging']
        for row in rows:
            uuid = row.preview_job_uuid if row.state in ('queued_preview', 'previewing') else row.import_job_uuid
            if not uuid or uuid not in existing_uuids:
                missing |= row
        return missing

    def action_restore_previous_state(self):
        """Roll back queue states when their queue.job record was deleted."""
        restored = 0
        for row in self._missing_job_rows():
            if row.state in ('queued_preview', 'previewing'):
                row.write({
                    'state': 'pending',
                    'preview_job_uuid': False,
                    'error_message': _('El trabajo de vista previa ya no existe; se ha restaurado el estado pendiente.'),
                })
            else:
                row.write({
                    'state': 'preview_ready',
                    'import_job_uuid': False,
                    'error_message': _('El trabajo de importación ya no existe; se ha restaurado la vista previa lista.'),
                })
            restored += 1
        return self._notification(
            _('Estados restaurados'),
            _('%s registros han retrocedido al proceso anterior.') % restored,
            'success' if restored else 'warning',
        )

    @api.model
    def _cron_restore_missing_jobs(self):
        rows = self.search([('state', 'in', [
            'queued_preview', 'previewing', 'queued_import', 'importing'])])
        missing = rows._missing_job_rows()
        if missing:
            missing.action_restore_previous_state()
        self.env['sitemap.import.batch']._restore_missing_collect_jobs()
        return True

    def action_requeue_failed(self):
        preview_rows = self.filtered(lambda r: r.state == 'error' and not r.name)
        import_rows = self.filtered(lambda r: r.state == 'error' and r.name)
        if preview_rows:
            preview_rows.action_queue_preview()
        if import_rows:
            import_rows.action_import_selected()
        return self._notification(
            _('Trabajos reencolados'),
            _('%s registros se han vuelto a enviar a la cola.') % len(self),
        )

    def action_view_jobs(self):
        uuids = list(filter(None, self.mapped('preview_job_uuid') + self.mapped('import_job_uuid')))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Trabajos de importación'),
            'res_model': 'queue.job',
            'view_mode': 'list,form',
            'domain': [('uuid', 'in', uuids)] if uuids else [('id', '=', 0)],
        }

    @staticmethod
    def _notification(title, message, notification_type='success'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notification_type,
                'sticky': False,
            },
        }
