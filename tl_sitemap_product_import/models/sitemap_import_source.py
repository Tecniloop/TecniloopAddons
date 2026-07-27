from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

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
    ('sitemap.connector.miguelbellido_es', 'Miguel Bellido España'),
    ('sitemap.connector.levis_es', "Levi's España"),
    ('sitemap.connector.fruitoftheloom_eu', 'Fruit of the Loom Europa'),
    ('sitemap.connector.blendcompany_eu', 'Blend Europa'),
    ('sitemap.connector.selected_es', 'SELECTED España'),
    ('sitemap.connector.geox_es', 'Geox España'),
    ('sitemap.connector.callaghan_es', 'Callaghan España'),
    ('sitemap.connector.fluchos_es', 'Fluchos España'),
    ('sitemap.connector.pitillos_es', 'Pitillos España'),
    ('sitemap.connector.gioseppo_es', 'Gioseppo España'),
    ('sitemap.connector.bhbikes_es', 'BH Bikes España'),
    ('sitemap.connector.lapierre_es', 'Lapierre Bikes España'),
    ('sitemap.connector.wethepeoplebmx', 'WeThePeople BMX'),
    ('sitemap.connector.mondraker_es', 'Mondraker España'),
    ('sitemap.connector.cervelo_es', 'Cervélo España'),
    ('sitemap.connector.colnago_es', 'Colnago España'),
    ('sitemap.connector.bicicletasquer_es', 'Bicicletas Quer B2B España'),
    ('sitemap.connector.ridley_es', 'Ridley Bikes España'),
    ('sitemap.connector.gtbicycles', 'GT Bicycles'),
    ('sitemap.connector.conor_es', 'Conor Bikes España'),
    ('sitemap.connector.merida_es', 'MERIDA BIKES España'),
    ('sitemap.connector.orbea_es', 'Orbea España'),
    ('sitemap.connector.scalextric_es', 'Scalextric España'),
    ('sitemap.connector.ninco_es', 'NINCO España'),
    ('sitemap.connector.electrotren_es', 'Electrotren España'),
    ('sitemap.connector.jouef_uk', 'Jouef Europa (precio EUR)'),
    ('sitemap.connector.arnold_de', 'Arnold Europa (precio EUR)'),
    ('sitemap.connector.rivarossi_it', 'Rivarossi Europa (precio EUR)'),
    ('sitemap.connector.lima_it', 'Lima Europa (precio EUR)'),
    ('sitemap.connector.pocher_uk', 'Pocher Europa (precio EUR)'),
    ('sitemap.connector.hornby_uk', 'Hornby Europa (precio EUR)'),
    ('sitemap.connector.airfix_uk', 'Airfix Europa (precio EUR)'),
    ('sitemap.connector.corgi_uk', 'Corgi y Corgi Premiums Europa (precio EUR)'),
    ('sitemap.connector.humbrol_uk', 'Humbrol Europa (precio EUR)'),
    ('sitemap.connector.bassett_lowke_uk', 'Bassett-Lowke Europa (precio EUR)'),
    ('sitemap.connector.maerklin_en', 'Märklin Europa'),
    ('sitemap.connector.trix_en', 'Trix Europa'),
    ('sitemap.connector.minitrix_en', 'Minitrix Europa'),
    ('sitemap.connector.lgb_en', 'LGB Europa'),
    ('sitemap.connector.preiser_de', 'Preiser Figuren Europa'),
    ('sitemap.connector.roco_es', 'ROCO España'),
    ('sitemap.connector.fleischmann_es', 'Fleischmann España'),
    ('sitemap.connector.piko_en', 'PIKO Europa'),
    ('sitemap.connector.brawa_en', 'BRAWA Europa'),
    ('sitemap.connector.hape_es', 'Hape España'),
    ('sitemap.connector.viessmann_viessmann', 'Viessmann Europa'),
    ('sitemap.connector.viessmann_kibri', 'Kibri Europa'),
    ('sitemap.connector.viessmann_vollmer', 'Vollmer Europa'),
    ('sitemap.connector.ree_modeles_fr', 'REE Modèles Francia'),
    ('sitemap.connector.bemo_de', 'BEMO Modelleisenbahnen Europa'),
    ('sitemap.connector.bachmann_bachmann_branchline', 'Bachmann Branchline — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_graham_farish', 'Graham Farish — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_liliput', 'Liliput — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_efe_rail', 'EFE Rail — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_scenecraft', 'Scenecraft — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_bachmann_narrow_gauge', 'Bachmann Narrow Gauge — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_thomas_friends', 'Thomas & Friends — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_woodland_scenics', 'Woodland Scenics — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_proses', 'Proses — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_bachmann_trains_usa', 'Bachmann Trains USA — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_bachmann_china', 'Bachmann China — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_efe_road', 'EFE Road — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_exclusive_first_editions', 'Exclusive First Editions — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_greenlight', 'GreenLight — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_mini_gt', 'Mini GT — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_academy', 'Academy — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_trumpeter', 'Trumpeter — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_airfix_bachmann', 'Airfix — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_accurate_figures', 'Accurate Figures — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_afv_club', 'AFV Club — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_amt', 'AMT — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_emhar', 'Emhar — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_hk_models', 'HK Models — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_i_love_kit', 'I Love Kit — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_mpc', 'MPC — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_polar_lights', 'Polar Lights — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_roden', 'Roden — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_takom', 'Takom — catálogo Bachmann UK'),
    ('sitemap.connector.bachmann_toyway', 'Toyway — catálogo Bachmann UK'),
    ('sitemap.connector.faller_faller', 'FALLER Europa'),
    ('sitemap.connector.faller_pola_g', 'POLA G Europa'),
    ('sitemap.connector.aneste_datank_es', 'Aneste Datank España'),
    ('sitemap.connector.noch_noch', 'NOCH — catálogo NOCH Alemania'),
    ('sitemap.connector.noch_rokuhan', 'Rokuhan — catálogo NOCH Alemania'),
    ('sitemap.connector.noch_athearn', 'Athearn — catálogo NOCH Alemania'),
    ('sitemap.connector.noch_ammo', 'AMMO — catálogo NOCH Alemania'),
    ('sitemap.connector.noch_proxxon', 'PROXXON — catálogo NOCH Alemania'),
    ('sitemap.connector.munichsports_es', 'MUNICH Sports España'),
    ('sitemap.connector.autentishoes_es', 'Autenti Shoes España'),
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
    http_retry_count = fields.Integer(
        string='Reintentos HTTP', default=3,
        help='Número de reintentos ante HTTP 429/5xx, timeout o fallo temporal de red.')
    http_retry_backoff = fields.Float(
        string='Espera exponencial inicial (segundos)', default=1.5,
        help='Espera inicial entre reintentos. Se duplica en cada intento y respeta Retry-After.')
    respect_robots_txt = fields.Boolean(
        string='Respetar robots.txt', default=True,
        help='Si está activo, la importación se detiene si robots.txt no permite el acceso '
             'automatizado (el comprobador interpreta correctamente los comodines "*" de robots.txt).')

    # --- Shopify: disponibilidad del endpoint ligero /products/<handle>.js ---
    shopify_js_mode = fields.Selection(
        [
            ('auto', 'Automático'),
            ('enabled', 'Forzar uso'),
            ('disabled', 'No usar'),
        ],
        string='Endpoint Shopify .js', default='auto', required=True,
        help='Automático prueba el endpoint .js hasta conocer si la fuente lo admite. '
             'Forzar uso lo intenta siempre. No usar evita esa petición y pasa directamente '
             'a .json, products.json y HTML.')
    shopify_js_status = fields.Selection(
        [
            ('unknown', 'Sin comprobar'),
            ('supported', 'Disponible'),
            ('unsupported', 'No disponible'),
        ],
        string='Estado Shopify .js', default='unknown', readonly=True, copy=False)
    shopify_js_checked_at = fields.Datetime(
        string='Última comprobación Shopify .js', readonly=True, copy=False)

    def action_reset_shopify_js_detection(self):
        self.write({
            'shopify_js_status': 'unknown',
            'shopify_js_checked_at': False,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Detección reiniciada'),
                'message': _('El endpoint Shopify .js volverá a comprobarse en la próxima ficha.'),
                'type': 'success',
                'sticky': False,
            },
        }

    # --- Volumen de procesamiento ---
    products_per_run = fields.Integer(
        string='Vistas previas por ejecución de cron', default=40,
        help='Número máximo de fichas de producto que se procesan en cada ejecución del cron de vistas previas.')

    # --- Descubrimiento numérico (Märklin, Trix, Minitrix y LGB) ---
    numeric_scan_start = fields.Char(
        string='Artículo inicial', default='700',
        help='Primera referencia numérica para Märklin, Trix, Minitrix o LGB. Puede tener cualquier cantidad de dígitos; por ejemplo 700, 00700 o 123456.')
    numeric_scan_end = fields.Char(
        string='Artículo final', default='40000',
        help='Última referencia numérica incluida en el escaneo de Märklin, Trix, Minitrix o LGB. Puede tener cualquier cantidad de dígitos.')
    numeric_scan_block_size = fields.Integer(
        string='Tamaño de bloque', default=250,
        help='Cantidad de referencias procesadas por cada trabajo de queue_job. Un valor pequeño facilita reintentos selectivos; uno grande crea menos trabajos.')
    numeric_scan_last_article = fields.Integer(
        string='Último artículo completado', readonly=True, copy=False,
        help='Mayor referencia cuyo bloque ha terminado correctamente. Es un dato informativo del último escaneo.')
    numeric_scan_resume = fields.Boolean(
        string='Reanudar desde el último artículo', default=False,
        help='Al iniciar un nuevo lote, comienza después del último artículo completado. Desactívalo para volver a recorrer todo el rango configurado.')

    @api.constrains('numeric_scan_start', 'numeric_scan_end', 'numeric_scan_block_size')
    def _check_numeric_scan_configuration(self):
        for source in self:
            start = (source.numeric_scan_start or '').strip()
            end = (source.numeric_scan_end or '').strip()
            if not start or not start.isdigit():
                raise ValidationError(_('El artículo inicial debe contener únicamente dígitos.'))
            if not end or not end.isdigit():
                raise ValidationError(_('El artículo final debe contener únicamente dígitos.'))
            if int(start) > int(end):
                raise ValidationError(_('El artículo inicial no puede ser mayor que el artículo final.'))
            if not (1 <= source.numeric_scan_block_size <= 10000):
                raise ValidationError(_('El tamaño de bloque debe estar entre 1 y 10.000 referencias.'))

    def action_reset_numeric_scan_progress(self):
        self.write({
            'numeric_scan_last_article': 0,
            'numeric_scan_resume': False,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Progreso reiniciado'),
                'message': _('El próximo escaneo comenzará en el artículo inicial configurado.'),
                'type': 'success',
                'sticky': False,
            },
        }

    # --- Imágenes ---
    import_images = fields.Boolean(string='Importar imágenes', default=True)
    max_images_per_product = fields.Integer(string='Máximo de imágenes por producto', default=6)
    import_attachments = fields.Boolean(
        string='Importar documentos', default=True,
        help='Descarga manuales, fichas técnicas y otros documentos publicados en la ficha y los muestra en el eCommerce.')
    max_attachments_per_product = fields.Integer(
        string='Máximo de documentos por producto', default=20)

    # --- EAN / GTIN ---
    import_eans = fields.Boolean(
        string='Recuperar EAN/GTIN', default=True,
        help='Busca códigos GTIN válidos en variantes, JSON-LD, JSON incrustado y endpoints públicos.')
    max_ean_requests_per_product = fields.Integer(
        string='Máximo de peticiones de variantes por producto', default=30,
        help='Límite de seguridad para fuentes que requieren una petición por talla o variante.')

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
    brand_id = fields.Many2one(
        'res.brand', string='Marca OCA del producto', ondelete='restrict',
        help='Marca OCA que se asignará a todos los productos creados o actualizados desde esta fuente.')
    sale_ok = fields.Boolean(string='Marcar productos como vendibles', default=True)
    purchase_ok = fields.Boolean(string='Marcar productos como comprables', default=False)
    auto_archive_discontinued = fields.Boolean(
        string='Archivar productos descatalogados', default=False,
        help='Si está activo, al terminar de obtener vistas previas de un lote completo, los '
             'productos de esta fuente que ya no aparezcan en él se archivan automáticamente.')

    auto_sync_enabled = fields.Boolean(
        string='Activar sincronización periódica automática', default=False,
        help='Activa el cron que crea automáticamente nuevos lotes de sincronización para esta fuente.')

    _name_uniq = models.Constraint(
        'unique(name)',
        message='Ya existe una fuente de importación con este nombre.',
    )
