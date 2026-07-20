from odoo import fields, models


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
        ('preview_ready', 'Vista previa lista'),
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
    preview_date = fields.Datetime(string='Fecha de vista previa')
    imported_date = fields.Datetime(string='Fecha de importación')

    _sql_constraints = [
        ('batch_url_uniq', 'unique(batch_id, url)', 'Esta URL ya está en este lote.'),
    ]

    def action_import_selected(self):
        """Acción en lote: aparece en el menú de Acciones (⚙) de la vista lista al
        seleccionar una o varias filas ('todas' o 'solo algunas', según pida el usuario;
        pueden pertenecer a lotes -e incluso fuentes- distintas). Crea o actualiza el
        producto de Odoo de cada fila seleccionada reutilizando los datos ya obtenidos en
        la vista previa -no se vuelve a descargar la ficha del producto-. Las imágenes solo
        se descargan aquí, y solo de lo seleccionado."""
        image_map_cache = {}

        created = updated = failed = 0
        for batch in self.mapped('batch_id'):
            rows = self.filtered(lambda r: r.batch_id == batch)
            source = batch.source_id
            connector = self.env[source.connector_model]
            if source.import_images and source.id not in image_map_cache:
                try:
                    image_map_cache[source.id] = connector.get_image_map(source)
                except Exception:
                    image_map_cache[source.id] = {}
            image_map = image_map_cache.get(source.id, {})
            for row in rows:
                result = connector.import_staging_row(row, source, image_map.get(row.url, []))
                if result == 'created':
                    created += 1
                elif result == 'updated':
                    updated += 1
                else:
                    failed += 1
                self.env.cr.commit()

        message = f'{created} creados, {updated} actualizados'
        if failed:
            message += f', {failed} con error'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Importación de productos',
                'message': message,
                'type': 'warning' if failed else 'success',
                'sticky': False,
            },
        }
