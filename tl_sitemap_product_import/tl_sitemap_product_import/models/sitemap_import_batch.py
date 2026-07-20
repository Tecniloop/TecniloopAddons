import logging

from odoo import api, fields, models
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

    def _get_service(self):
        """Devuelve el conector Python correspondiente a la fuente de este lote."""
        self.ensure_one()
        return self.env[self.source_id.connector_model]

    def action_collect_urls(self):
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
        except UserError:
            self.write({'state': 'error'})
            raise
        except Exception as exc:
            _logger.exception('Error recopilando URLs (fuente %s)', self.source_id.name)
            self.write({'state': 'error', 'error_message': str(exc)})
            raise UserError(f'Error al recopilar las URLs del sitemap: {exc}') from exc

    def action_fetch_previews(self, limit=None):
        """Obtiene datos ligeros de vista previa (nombre, precio, categoría; SIN imágenes)
        para un lote acotado de filas pendientes. Las filas ya enlazadas a un producto de
        Odoo de una sincronización anterior se actualizan de inmediato (incluidas imágenes,
        porque ya fueron aprobadas); las filas nuevas solo muestran la vista previa a la
        espera de que el usuario las seleccione en la lista para importarlas."""
        self.ensure_one()
        service = self._get_service()
        source = self.source_id
        run_limit = limit or source.products_per_run

        image_map = {}
        if source.import_images:
            try:
                image_map = service.get_image_map(source)
            except Exception as exc:
                _logger.warning('No se pudo obtener el mapa de imágenes (fuente %s): %s', source.name, exc)

        pending = self.staging_ids.filtered(lambda r: r.state == 'pending')[:run_limit]
        for row in pending:
            service.refresh_staging_row(row, source, image_map, force=self.force_update)
            self.env.cr.commit()

        if not self.staging_ids.filtered(lambda r: r.state == 'pending'):
            self.write({'state': 'ready', 'date_end': fields.Datetime.now()})
            if source.auto_archive_discontinued:
                self._archive_discontinued()

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
                if batch.state == 'collecting':
                    # Un lote atascado en "collecting" probablemente falló a medias; se reintenta.
                    batch.action_collect_urls()
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
