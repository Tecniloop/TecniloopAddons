from odoo import fields, models


class SitemapCategoryMapping(models.Model):
    _name = 'sitemap.category.mapping'
    _description = 'Mapeo de categorías de una fuente a categorías existentes'
    _order = 'source_id, sequence, id'
    _rec_name = 'category_path'

    source_id = fields.Many2one(
        'sitemap.import.source', string='Fuente', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category_path = fields.Char(
        string='Ruta de categoría de origen', required=True,
        help='Ruta tal como la genera el importador a partir de la URL, con segmentos separados '
             'por "/", p. ej. "Mujer/Calzado/Zapatillas/Zapatillas Casual".\n'
             'También puede ser una ruta PARCIAL (p. ej. "Mujer/Calzado"): en ese caso se usa como '
             'punto de partida y los segmentos restantes ("Zapatillas", "Zapatillas Casual"...) se '
             'siguen creando anidados debajo de la categoría indicada, en vez de bajo la categoría '
             'raíz de la fuente.\n'
             'Usa el asistente "Explorar categorías" para ver las rutas reales presentes en el '
             'catálogo de esta fuente antes de crear mapeos.')
    product_category_id = fields.Many2one(
        'product.category', string='Categoría interna existente',
        help='Si se indica, los productos de esta ruta (o de rutas que empiecen por ella) usarán '
             'esta categoría interna en lugar de crear una nueva bajo la categoría raíz de la fuente.')
    public_category_id = fields.Many2one(
        'product.public.category', string='Categoría e-commerce existente',
        help='Si se indica, los productos de esta ruta (o de rutas que empiecen por ella) usarán '
             'esta categoría de comercio electrónico en lugar de crear una nueva bajo la categoría '
             'raíz de la fuente.')
    note = fields.Char(string='Nota')

    _sql_constraints = [
        ('source_path_uniq', 'unique(source_id, category_path)',
         'Ya existe un mapeo para esta ruta de categoría en esta fuente.'),
    ]
