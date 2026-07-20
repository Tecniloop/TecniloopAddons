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

    @api.depends('staging_ids.state')
    def _compute_staging_stats(self):
        for batch in self:
            lines = batch.staging_ids
            batch.staging_count = len(lines)
            batch.pending_count = len(lines.filtered(lambda l: l.state == 'pending'))
            batch.preview_ready_count = len(lines.filtered(lambda l: l.state == 'preview_ready'))
            batch.imported_count = len(lines.filtered(lambda l: l.state == 'imported'))
            batch.skipped_count = len(lines.filtered(lambda l: l.state == 'skipped'))
            batch.error_count = len(lines.filtered(lambda l: l.state == 'error'))
            batch.queued_count = len(lines.filtered(lambda l: l.state in ('queued_preview', 'queued_import')))
            batch.processing_count = len(lines.filtered(lambda l: l.state in ('previewing', 'importing')))

    def _get_service(self):
        """Devuelve el conector Python correspondiente a la fuente de este lote."""
        self.ensure_one()
        return self.env[self.source_id.connector_model]

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
