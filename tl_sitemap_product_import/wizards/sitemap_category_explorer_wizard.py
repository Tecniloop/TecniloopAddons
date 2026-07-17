from odoo import fields, models
from odoo.exceptions import UserError


class SitemapCategoryExplorerWizard(models.TransientModel):
    _name = 'sitemap.category.explorer.wizard'
    _description = 'Explorador de categorías de una fuente'

    source_id = fields.Many2one(
        'sitemap.import.source', string='Fuente', required=True,
        default=lambda self: self.env['sitemap.import.source'].search([], limit=1))
    category_summary = fields.Text(string='Rutas de categoría encontradas', readonly=True)
    total_products = fields.Integer(string='Productos analizados', readonly=True)
    total_categories = fields.Integer(string='Rutas de categoría distintas', readonly=True)

    def action_explore(self):
        """Pide al conector de la fuente la lista completa de URLs de producto y deriva la
        categoría de cada una SOLO a partir de la URL (parse_category_path), sin descargar
        ninguna ficha -por eso es rápido incluso con miles de referencias-, para ayudar a
        decidir qué mapeos crear en 'Mapeo de categorías' antes de lanzar una importación
        completa."""
        self.ensure_one()
        source = self.source_id
        service = self.env[source.connector_model]

        if not service.check_robots(source, source.sitemap_index_url):
            raise UserError(
                'El robots.txt del sitio no permite el acceso automatizado a esta URL.')

        entries = service.get_product_entries(source)
        counts = {}
        for entry in entries:
            segments = service.parse_category_path(entry['url'])
            path = '/'.join(segments) if segments else '(sin categoría, URL plana)'
            counts[path] = counts.get(path, 0) + 1

        lines = [f'{count:>5}  {path}' for path, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        self.write({
            'category_summary': '\n'.join(lines) or 'No se encontraron categorías.',
            'total_products': len(entries),
            'total_categories': len(counts),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sitemap.category.explorer.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
