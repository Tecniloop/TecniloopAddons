from odoo import api, fields, models
from odoo.exceptions import UserError


class SitemapImportWizard(models.TransientModel):
    _name = 'sitemap.import.wizard'
    _description = 'Asistente de importación de productos desde una fuente'

    source_id = fields.Many2one(
        'sitemap.import.source', string='Fuente', required=True,
        default=lambda self: self.env['sitemap.import.source'].search([], limit=1))
    category_filter = fields.Char(
        string='Filtro de categoría (opcional)',
        help='Solo se incluirán URLs que contengan este texto, por ejemplo '
             '"mujer/calzado/zapatillas" o "ropa/hombre". Déjalo vacío para explorar todo el catálogo.')
    url_limit = fields.Integer(
        string='Límite de productos (0 = todos)', default=0,
        help='Útil para hacer una prueba con pocos productos antes de explorar el catálogo completo.')
    force_update = fields.Boolean(
        string='Forzar nueva vista previa de productos ya importados',
        help='Si no está marcado, los productos ya importados cuya fecha de modificación en el '
             'sitemap no ha cambiado se omiten para ahorrar peticiones.')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'source_id' in fields_list and not res.get('source_id') \
                and not self.env['sitemap.import.source'].search_count([]):
            raise UserError(
                'Todavía no hay ninguna fuente de importación configurada. Crea una primero en '
                'Importación por sitemap > Fuentes.')
        return res

    def action_start_import(self):
        self.ensure_one()
        batch = self.env['sitemap.import.batch'].create({
            'source_id': self.source_id.id,
            'trigger': 'manual',
            'category_filter': self.category_filter or False,
            'url_limit': self.url_limit,
            'force_update': self.force_update,
        })
        batch.action_collect_urls()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Lote {self.source_id.name}',
            'res_model': 'sitemap.import.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }
