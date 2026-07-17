from odoo import fields, models

# Cada conector instalado añade aquí su opción (modelo técnico -> nombre a mostrar). Para dar
# de alta un sitio nuevo con una estructura de sitemap distinta: crea un fichero
# models/connector_<nombre>.py con un AbstractModel _name='sitemap.connector.<nombre>',
# _inherit='sitemap.import.service' que implemente get_product_entries/get_image_map/
# fetch_preview, regístralo en models/__init__.py y añade la opción aquí abajo.
CONNECTOR_SELECTION = [
    ('sitemap.connector.skechers_es', 'Skechers España'),
    ('sitemap.connector.mtng_es', 'Mustang Shoes España'),
    ('sitemap.connector.pikolinos_es', 'Pikolinos España'),
    ('sitemap.connector.panamajack_es', 'Panama Jack España'),
]


class SitemapImportSource(models.Model):
    _name = 'sitemap.import.source'
    _description = 'Fuente de importación de productos (un sitio web con su propio conector)'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True, help='Nombre descriptivo, p. ej. "Skechers España".')
    active = fields.Boolean(default=True)

    connector_model = fields.Selection(
        CONNECTOR_SELECTION, string='Conector', required=True,
        help='Código específico de este sitio (cómo combinar sus sub-sitemaps, qué patrón de '
             'URL usa para el estilo/color y la categoría...). Cada sitio con una estructura '
             'de sitemap distinta necesita su propio conector: no es un ajuste, es código '
             '-ver models/connector_*.py-.')
    sitemap_index_url = fields.Char(
        string='URL del sitemap índice', required=True,
        help='URL del sitemap_index.xml (o equivalente) de este sitio.')

    # --- Comportamiento de red / buenas prácticas de scraping ---
    user_agent = fields.Char(
        string='User-Agent', default='Mozilla/5.0 (compatible; OdooSitemapImporter/1.0)',
        help='Identifícate con un User-Agent propio para que el sitio de origen pueda '
             'reconocer y, si lo desea, limitar tu tráfico.')
    request_delay = fields.Float(
        string='Retraso entre peticiones (segundos)', default=1.0,
        help='Tiempo de espera entre cada petición HTTP para no sobrecargar el servidor de origen.')
    request_timeout = fields.Integer(string='Timeout de petición (segundos)', default=20)
    respect_robots_txt = fields.Boolean(
        string='Respetar robots.txt', default=True,
        help='Si está activo, la importación se detiene si robots.txt no permite el acceso '
             'automatizado (el comprobador interpreta correctamente los comodines "*" de robots.txt).')

    # --- Volumen de procesamiento ---
    products_per_run = fields.Integer(
        string='Vistas previas por ejecución de cron', default=40,
        help='Número máximo de fichas de producto que se procesan en cada ejecución del cron de vistas previas.')

    # --- Imágenes ---
    import_images = fields.Boolean(string='Importar imágenes', default=True)
    max_images_per_product = fields.Integer(string='Máximo de imágenes por producto', default=6)

    # --- Categorías y catálogo ---
    root_category_id = fields.Many2one(
        'product.category', string='Categoría raíz (interna)',
        help='Categoría interna bajo la que se crearán las subcategorías. Si se deja vacío se '
             'creará/usará una categoría con el mismo nombre que esta fuente.')
    import_public_categories = fields.Boolean(
        string='Importar categorías de comercio electrónico', default=True,
        help='Además de la categoría interna, crea/asigna una categoría de comercio electrónico '
             '(product.public.category) para cada producto.')
    public_root_category_id = fields.Many2one(
        'product.public.category', string='Categoría raíz (comercio electrónico)',
        help='Categoría de comercio electrónico bajo la que se crearán las subcategorías. Si se '
             'deja vacío se creará/usará una categoría con el mismo nombre que esta fuente.')
    product_tag_ids = fields.Many2many('product.tag', string='Etiquetas a aplicar a los productos importados')
    sale_ok = fields.Boolean(string='Marcar productos como vendibles', default=True)
    purchase_ok = fields.Boolean(string='Marcar productos como comprables', default=False)
    auto_archive_discontinued = fields.Boolean(
        string='Archivar productos descatalogados', default=False,
        help='Si está activo, al terminar de obtener vistas previas de un lote completo, los '
             'productos de esta fuente que ya no aparezcan en él se archivan automáticamente.')

    auto_sync_enabled = fields.Boolean(
        string='Activar sincronización periódica automática', default=False,
        help='Activa el cron que crea automáticamente nuevos lotes de sincronización para esta fuente.')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Ya existe una fuente de importación con este nombre.'),
    ]
