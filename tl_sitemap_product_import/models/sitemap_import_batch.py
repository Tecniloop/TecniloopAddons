import logging

import requests

from odoo import _, api, fields, models
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SitemapImportBatch(models.Model):
    _name = 'sitemap.import.batch'
    _description = 'Lote de importación de productos (una sincronización de una fuente)'
    _order = 'create_date desc'

    name = fields.Char(
        string='Referencia', copy=False,
        default=lambda self: fields.Datetime.now().strftime('Lote %Y-%m-%d %H:%M:%S'))
    source_id = fields.Many2one(
        'sitemap.import.source', string='Fuente', required=True, ondelete='cascade', index=True)
    trigger = fields.Selection([
        ('manual', 'Manual'),
        ('cron', 'Automático'),
    ], string='Origen', default='manual', required=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('queued_collect', 'Recopilación en cola'),
        ('collecting', 'Recopilando URLs'),
        ('previewing', 'Obteniendo vistas previas'),
        ('ready', 'Listo para revisar'),
        ('error', 'Error'),
    ], string='Estado', default='draft', index=True)

    date_start = fields.Datetime(string='Inicio')
    date_end = fields.Datetime(string='Fin de vistas previas')

    category_filter = fields.Char(
        string='Filtro de categoría',
        help='Solo se incluirán URLs que contengan este texto, p. ej. "mujer/calzado/zapatillas".')
    url_limit = fields.Integer(string='Límite de URLs (0 = todas)', default=0)
    force_update = fields.Boolean(string='Forzar nueva vista previa aunque no haya cambios')

    error_message = fields.Text(string='Error')

    staging_ids = fields.One2many('sitemap.product.staging', 'batch_id', string='Productos')
    staging_count = fields.Integer(compute='_compute_staging_stats', string='Total')
    pending_count = fields.Integer(compute='_compute_staging_stats', string='Pendientes')
    preview_ready_count = fields.Integer(compute='_compute_staging_stats', string='Con vista previa')
    imported_count = fields.Integer(compute='_compute_staging_stats', string='Importados')
    skipped_count = fields.Integer(compute='_compute_staging_stats', string='Sin cambios')
    error_count = fields.Integer(compute='_compute_staging_stats', string='Errores')
    queued_count = fields.Integer(compute='_compute_staging_stats', string='En cola')
    processing_count = fields.Integer(compute='_compute_staging_stats', string='Procesando')
    collect_job_uuid = fields.Char(string='Trabajo de recopilación', readonly=True, copy=False)
    numeric_scan_total_blocks = fields.Integer(
        string='Bloques de escaneo', readonly=True, copy=False)
    numeric_scan_completed_blocks = fields.Integer(
        string='Bloques completados', readonly=True, copy=False)
    numeric_scan_found_count = fields.Integer(
        string='Artículos encontrados', readonly=True, copy=False)

    @api.depends('staging_ids.state')
    def _compute_staging_stats(self):
        """Compute counters with one grouped query instead of prefetching every staging row.

        Besides being faster for large catalogues, this avoids making the batch list depend
        on unrelated stored columns of ``sitemap.product.staging`` being prefetched.
        """
        counters = {batch.id: {} for batch in self}
        if self.ids:
            grouped = self.env['sitemap.product.staging']._read_group(
                [('batch_id', 'in', self.ids)],
                ['batch_id', 'state'],
                ['__count'],
            )
            for batch, state, count in grouped:
                counters.setdefault(batch.id, {})[state] = count

        for batch in self:
            states = counters.get(batch.id, {})
            batch.staging_count = sum(states.values())
            batch.pending_count = states.get('pending', 0)
            batch.preview_ready_count = states.get('preview_ready', 0)
            batch.imported_count = states.get('imported', 0)
            batch.skipped_count = states.get('skipped', 0)
            batch.error_count = states.get('error', 0)
            batch.queued_count = (
                states.get('queued_preview', 0) + states.get('queued_import', 0)
            )
            batch.processing_count = states.get('previewing', 0) + states.get('importing', 0)

    def _get_service(self):
        """Devuelve el conector Python correspondiente a la fuente de este lote."""
        self.ensure_one()
        return self.env[self.source_id.connector_model]


    def _restore_missing_collect_jobs(self):
        """Restore queued batches when their collection job was deleted."""
        queued = self.filtered(lambda batch: batch.state == 'queued_collect') if self else self.search([
            ('state', '=', 'queued_collect')
        ])
        uuids = list(filter(None, queued.mapped('collect_job_uuid')))
        existing = set(self.env['queue.job'].sudo().search([
            ('uuid', 'in', uuids)
        ]).mapped('uuid')) if uuids else set()
        restored = self.env['sitemap.import.batch']
        for batch in queued:
            if not batch.collect_job_uuid or batch.collect_job_uuid not in existing:
                batch.write({
                    'state': 'draft',
                    'collect_job_uuid': False,
                    'error_message': _('El trabajo de recopilación ya no existe; el lote ha vuelto a borrador.'),
                })
                restored |= batch
        return restored

    def action_restore_previous_state(self):
        restored_batches = self._restore_missing_collect_jobs()
        restored_rows = self.mapped('staging_ids')._missing_job_rows()
        row_count = len(restored_rows)
        if restored_rows:
            restored_rows.action_restore_previous_state()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Estados restaurados'),
                'message': _('%s lotes y %s productos han retrocedido al proceso anterior.') % (
                    len(restored_batches), row_count),
                'type': 'success' if restored_batches or row_count else 'warning',
                'sticky': False,
            },
        }

    def action_collect_urls(self):
        self.ensure_one()
        self.write({
            'state': 'queued_collect',
            'date_start': fields.Datetime.now(),
            'error_message': False,
        })
        job = self.with_delay(
            priority=10,
            max_retries=max(self.source_id.http_retry_count or 3, 1),
            identity_key=f"sitemap_collect_{self.id}",
            description=_("Recopilar URLs sitemap: %s") % self.source_id.name,
        )._job_collect_urls()
        self.collect_job_uuid = job.uuid
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recopilación en cola'),
                'message': _('El lote se procesará en segundo plano.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def _job_collect_urls(self):
        """Pide al conector de la fuente la lista de URLs de producto y crea una fila de
        staging (sin vista previa todavía, sin crear ningún producto) por cada una."""
        self.ensure_one()
        service = self._get_service()
        source = self.source_id
        self.write({'state': 'collecting', 'date_start': fields.Datetime.now(), 'error_message': False})
        try:
            if not service.check_robots(source, source.sitemap_index_url):
                raise UserError(
                    'El robots.txt del sitio no permite el acceso automatizado a esta URL. '
                    'Revisa la opción "Respetar robots.txt" en la fuente, o el permiso del '
                    'sitio de origen.')

            if getattr(service, '_uses_numeric_scanner', lambda _source: False)(source):
                self._queue_numeric_scan(service)
                return True

            entries = service.get_product_entries(
                source, category_filter=self.category_filter or None, limit=self.url_limit or 0)
            if not entries:
                raise UserError(
                    'No se ha encontrado ninguna URL de producto. Revisa la URL del sitemap y '
                    'el conector configurado en la fuente.')

            existing_urls = set(self.staging_ids.mapped('url'))
            vals_list = [{
                'batch_id': self.id,
                'url': entry['url'],
                'sitemap_lastmod': entry['lastmod'],
            } for entry in entries if entry['url'] not in existing_urls]
            if vals_list:
                self.env['sitemap.product.staging'].create(vals_list)

            self.write({'state': 'previewing'})
            self.action_fetch_all_previews()
        except UserError:
            self.write({'state': 'error'})
            raise
        except Exception as exc:
            _logger.exception('Error recopilando URLs (fuente %s)', self.source_id.name)
            response = getattr(exc, 'response', None)
            transient = isinstance(exc, (requests.Timeout, requests.ConnectionError)) or getattr(
                response, 'status_code', None
            ) in {429, 500, 502, 503, 504}
            if transient:
                self.write({'state': 'queued_collect', 'error_message': str(exc)[:4000]})
                raise RetryableJobError(str(exc)) from exc
            self.write({'state': 'error', 'error_message': str(exc)[:4000]})
            raise UserError(f'Error al recopilar las URLs del sitemap: {exc}') from exc

    def _queue_numeric_scan(self, service):
        """Divide el rango configurado por el usuario en trabajos reintentables."""
        self.ensure_one()
        source = self.source_id
        start, end = service._numeric_scan_bounds(source)
        block_size = max(int(service._numeric_scan_block_size(source) or 250), 1)
        if start > end:
            self.write({
                'state': 'ready',
                'date_end': fields.Datetime.now(),
                'numeric_scan_total_blocks': 0,
                'numeric_scan_completed_blocks': 0,
                'numeric_scan_found_count': 0,
                'error_message': False,
            })
            return True
        blocks = [(first, min(first + block_size - 1, end))
                  for first in range(start, end + 1, block_size)]
        self.write({
            'state': 'collecting',
            'numeric_scan_total_blocks': len(blocks),
            'numeric_scan_completed_blocks': 0,
            'numeric_scan_found_count': 0,
            'error_message': False,
        })
        for first, last in blocks:
            self.with_delay(
                priority=12,
                max_retries=max(source.http_retry_count or 3, 1),
                identity_key=f'sitemap_numeric_scan_{self.id}_{first}_{last}',
                description=_('Escanear artículos %d-%d: %s') % (
                    first, last, source.name),
            )._job_scan_numeric_block(first, last)
        return True

    def _job_scan_numeric_block(self, first, last):
        """Comprueba HTML bruto y solo crea staging para artículos existentes."""
        self.ensure_one()
        source = self.source_id
        service = self._get_service()
        session = service._get_session(source)
        existing_urls = set(self.staging_ids.mapped('url'))
        vals_list = []
        try:
            for article_number in range(int(first), int(last) + 1):
                url = service._numeric_scan_url(source, article_number)
                try:
                    response = service._http_get(session, url, source)
                except requests.HTTPError as exc:
                    status = getattr(getattr(exc, 'response', None), 'status_code', None)
                    if status in (404, 410):
                        continue
                    raise
                content = response.content or b''
                # Requisito funcional: esta comprobación se realiza antes de
                # lxml, JSON-LD, imágenes o cualquier otro análisis.
                if service._numeric_page_missing(content):
                    continue
                if not service._numeric_page_matches_source(content):
                    continue
                canonical = service._canonical_url(response.url) or url
                if canonical in existing_urls:
                    continue
                existing_urls.add(canonical)
                vals_list.append({
                    'batch_id': self.id,
                    'url': canonical,
                    'sitemap_lastmod': False,
                })

            rows = self.env['sitemap.product.staging'].create(vals_list) if vals_list else self.env['sitemap.product.staging']
            if rows:
                rows.action_queue_preview()

            # Incremento atómico: varios bloques pueden finalizar a la vez.
            self.env.cr.execute(
                """
                UPDATE sitemap_import_batch
                   SET numeric_scan_completed_blocks = COALESCE(numeric_scan_completed_blocks, 0) + 1,
                       numeric_scan_found_count = COALESCE(numeric_scan_found_count, 0) + %s
                 WHERE id = %s
             RETURNING numeric_scan_completed_blocks, numeric_scan_total_blocks
                """,
                [len(vals_list), self.id],
            )
            completed, total = self.env.cr.fetchone()
            self.invalidate_recordset([
                'numeric_scan_completed_blocks', 'numeric_scan_found_count',
            ])
            # Progreso informativo por fuente, actualizado atómicamente porque
            # distintos bloques pueden terminar simultáneamente.
            self.env.cr.execute(
                """
                UPDATE sitemap_import_source
                   SET numeric_scan_last_article = GREATEST(
                       COALESCE(numeric_scan_last_article, 0), %s
                   )
                 WHERE id = %s
                """,
                [int(last), source.id],
            )
            source.invalidate_recordset(['numeric_scan_last_article'])
            if completed >= total:
                self.write({'state': 'previewing'})
                self._update_queue_completion()
            return len(vals_list)
        except Exception as exc:
            _logger.exception(
                'Error escaneando rango %d-%d para %s', first, last, source.name)
            response = getattr(exc, 'response', None)
            transient = isinstance(exc, (requests.Timeout, requests.ConnectionError)) or getattr(
                response, 'status_code', None
            ) in {429, 500, 502, 503, 504}
            if transient:
                raise RetryableJobError(str(exc)) from exc
            self.write({'error_message': str(exc)[:4000]})
            raise

    def action_fetch_previews(self, limit=None):
        self.ensure_one()
        source = self.source_id
        run_limit = source.products_per_run if limit is None else limit
        pending = self.staging_ids.filtered(lambda r: r.state in ('pending', 'error'))
        if run_limit and run_limit > 0:
            pending = pending[:run_limit]
        if pending:
            pending.action_queue_preview()
        self._update_queue_completion()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Vistas previas en cola'),
                'message': _('%s fichas se han enviado a la cola.') % len(pending),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_fetch_all_previews(self):
        self.ensure_one()
        return self.action_fetch_previews(limit=0)

    def _update_queue_completion(self):
        for batch in self:
            active = batch.staging_ids.filtered(
                lambda r: r.state in ('pending', 'queued_preview', 'previewing')
            )
            if not active and batch.state not in ('draft', 'queued_collect', 'collecting', 'error'):
                batch.write({'state': 'ready', 'date_end': fields.Datetime.now()})
                if batch.source_id.auto_archive_discontinued:
                    batch._archive_discontinued()

    def action_requeue_errors(self):
        self.ensure_one()
        errors = self.staging_ids.filtered(lambda r: r.state == 'error')
        if errors:
            errors.action_requeue_failed()
        return True

    def action_view_jobs(self):
        self.ensure_one()
        uuids = list(filter(None, [self.collect_job_uuid] + self.staging_ids.mapped('preview_job_uuid') + self.staging_ids.mapped('import_job_uuid')))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Trabajos del lote'),
            'res_model': 'queue.job',
            'view_mode': 'list,form',
            'domain': [('uuid', 'in', uuids)] if uuids else [('id', '=', 0)],
        }

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Productos de este lote',
            'res_model': 'sitemap.product.staging',
            'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)],
        }

    def _archive_discontinued(self):
        self.ensure_one()
        current_urls = self.staging_ids.mapped('url')
        if not current_urls:
            return
        stale = self.env['product.template'].search([
            ('sitemap_source_id', '=', self.source_id.id),
            ('sitemap_source_url', 'not in', current_urls),
            ('active', '=', True),
        ])
        if stale:
            stale.write({'active': False})
            _logger.info(
                'Sitemap import (%s): %s productos archivados por no estar ya en el sitemap.',
                self.source_id.name, len(stale))

    @api.model
    def _cron_fetch_pending_previews(self):
        batches = self.search([('state', 'in', ['previewing', 'collecting'])], order='create_date asc')
        for batch in batches:
            try:
                if batch.state in ('draft', 'queued_collect'):
                    batch.action_collect_urls()
                elif batch.state == 'previewing':
                    batch.action_fetch_previews()
            except Exception:
                _logger.exception('Error obteniendo vistas previas del lote %s', batch.id)

    @api.model
    def _cron_create_scheduled_sync(self):
        sources = self.env['sitemap.import.source'].search([('auto_sync_enabled', '=', True)])
        for source in sources:
            batch = self.create({'trigger': 'cron', 'source_id': source.id})
            try:
                batch.action_collect_urls()
            except Exception:
                _logger.exception('Error iniciando la sincronización periódica de la fuente %s', source.name)
