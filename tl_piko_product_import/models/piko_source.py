# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import logging
from urllib.parse import urljoin

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SOURCE_CRON_XMLID = "tl_piko_product_import.ir_cron_tl_piko_sources"
SOURCE_LOCK_NAMESPACE = 8271042


class TlPikoSource(models.Model):
    _name = "tl.piko.source"
    _description = "Fuente de scraping de productos"
    _inherit = ["mail.thread"]
    _order = "sequence, id"

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True
    )
    base_url = fields.Char(
        required=True,
        help="URL raíz de la tienda, p.ej. https://www.piko-shop.de",
        tracking=True,
    )
    lang_code = fields.Char(
        "Idioma del sitio", default="de", help="Prefijo de idioma en las URLs (de, en...)"
    )
    extra_params = fields.Char(
        "Parámetros de consulta",
        help="Se añaden a cada petición, p.ej. 'lang=en'. Las URLs almacenadas "
             "quedan limpias; el parámetro solo se aplica al descargar.",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, required=True
    )

    # --- Descubrimiento -------------------------------------------------
    discovery_mode = fields.Selection(
        [
            ("sitemap", "Sitemap XML"),
            ("category", "Rastreo de categorías"),
            ("manual", "Lista de URLs"),
        ],
        default="category",
        required=True,
        tracking=True,
    )
    sitemap_url = fields.Char()
    url_list = fields.Text("URLs (una por línea)")
    category_ids = fields.One2many("tl.piko.category", "source_id", string="Categorías")
    product_url_regex = fields.Char(
        default=r"/artikel/",
        required=True,
        help="Expresión regular que identifica una URL de ficha de producto.",
    )

    # --- Comportamiento HTTP -------------------------------------------
    user_agent = fields.Char(
        default="Mozilla/5.0 (compatible; TecniloopOdooBot/1.0; +https://www.tecniloop.com)"
    )
    request_delay = fields.Float(
        "Retardo entre peticiones (s)",
        default=1.5,
        help="Cortesía con el servidor de origen. No lo bajes de 1s en producción.",
    )
    timeout = fields.Integer(default=30)
    max_retries = fields.Integer(
        "Reintentos HTTP", default=3, help="Reintentos inmediatos dentro de una petición."
    )
    respect_robots = fields.Boolean("Respetar robots.txt", default=True)
    max_products = fields.Integer(
        "Límite por descubrimiento", default=200, help="0 = sin límite."
    )

    # --- Cola -----------------------------------------------------------
    queue_state = fields.Selection(
        [
            ("idle", "Inactiva"),
            ("queued", "En cola"),
            ("running", "Ejecutándose"),
            ("done", "Completada"),
            ("failed", "Fallida"),
        ],
        default="idle",
        readonly=True,
        copy=False,
        tracking=True,
    )
    auto_import = fields.Boolean(
        "Importar automáticamente tras rastrear",
        default=True,
        help="Si se desactiva, las líneas quedan en 'Parseado' para revisión manual.",
    )
    max_attempts = fields.Integer(
        "Intentos por línea", default=3, help="Antes de marcarla como error."
    )
    retry_backoff_minutes = fields.Integer(
        "Espera base entre intentos (min)",
        default=10,
        help="Backoff exponencial: 10, 20, 40...",
    )

    # --- Selectores opcionales -----------------------------------------
    xpath_name = fields.Char("XPath nombre")
    xpath_sku = fields.Char("XPath referencia")
    xpath_price = fields.Char("XPath precio")
    xpath_description = fields.Char("XPath descripción")
    xpath_image = fields.Char("XPath imagen", help="Debe devolver el atributo src/href.")
    xpath_barcode = fields.Char("XPath EAN")

    # --- Reglas de importación -----------------------------------------
    create_products = fields.Boolean("Crear productos nuevos", default=True)
    update_existing = fields.Boolean("Actualizar existentes", default=True)
    update_name = fields.Boolean("Actualizar nombre", default=False)
    update_description = fields.Boolean("Actualizar descripción", default=True)
    update_price = fields.Boolean("Actualizar precio de venta", default=False)
    update_barcode = fields.Boolean("Completar EAN vacío", default=True)
    import_images = fields.Boolean("Descargar imagen principal", default=True)
    apply_attribute_rules = fields.Boolean(
        "Extraer características", default=True,
        help="Aplica las reglas regex al rastrear cada ficha."
    )
    update_attributes = fields.Boolean(
        "Escribir características en el producto", default=True,
        help="Crea líneas de atributo `no_variant`. Nunca genera variantes."
    )
    attribute_rule_ids = fields.One2many(
        "tl.piko.attribute.rule", "source_id", string="Reglas propias"
    )
    product_categ_id = fields.Many2one(
        "product.category", string="Categoría raíz",
        default=lambda self: self.env.ref(
            "product.product_category_all", raise_if_not_found=False
        ),
        help="Categoría fija, o raíz bajo la que se crea el árbol importado.",
    )
    categ_mode = fields.Selection(
        [
            ("fixed", "Siempre la categoría raíz"),
            ("first", "Primer nivel del breadcrumb"),
            ("leaf", "Último nivel del breadcrumb"),
        ],
        "Categoría de producto",
        default="fixed",
        required=True,
        help="`categ_id` es único por producto y arrastra cuentas contables: "
             "lo habitual es dejarlo grueso (fijo o primer nivel).",
    )
    update_categ = fields.Boolean(
        "Recalcular en productos existentes", default=False,
        help="Por defecto la categoría contable solo se fija al crear."
    )
    public_categ_mode = fields.Selection(
        [
            ("none", "No importar"),
            ("path", "Ruta completa (crea la jerarquía)"),
            ("leaf", "Solo la última"),
        ],
        "Categorías de eCommerce",
        default="path",
        required=True,
        help="Requiere website_sale. Nunca elimina categorías puestas a mano.",
    )
    product_type = fields.Selection(
        [("consu", "Bienes"), ("service", "Servicio")], default="consu", required=True
    )

    # --- Estado ---------------------------------------------------------
    line_ids = fields.One2many("tl.piko.product", "source_id", string="Líneas")
    line_count = fields.Integer(compute="_compute_counts")
    queued_count = fields.Integer(compute="_compute_counts")
    imported_count = fields.Integer(compute="_compute_counts")
    error_count = fields.Integer(compute="_compute_counts")
    last_run = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    _name_company_uniq = models.Constraint(
        "unique(name, company_id)", "El nombre de la fuente debe ser único."
    )

    # ------------------------------------------------------------------
    def _compute_counts(self):
        data = self.env["tl.piko.product"]._read_group(
            [("source_id", "in", self.ids)], ["source_id", "state"], ["__count"]
        )
        mapping = {}
        for source, state, count in data:
            mapping.setdefault(source.id, {})[state] = count
        for record in self:
            states = mapping.get(record.id, {})
            record.line_count = sum(states.values())
            record.queued_count = states.get("queued", 0)
            record.imported_count = states.get("imported", 0)
            record.error_count = states.get("error", 0)

    def _get_session(self):
        self.ensure_one()
        return self.env["tl.piko.scraper"]._session(self)

    def _lock_key(self):
        self.ensure_one()
        return SOURCE_LOCK_NAMESPACE + self.id

    def _try_lock(self):
        """Advisory lock transaccional por fuente."""
        self.ensure_one()
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (self._lock_key(),))
        return self.env.cr.fetchone()[0]

    # ==================================================================
    # Encolado (lo que hacen los botones: nada de HTTP aquí)
    # ==================================================================
    def action_enqueue(self):
        """Encola el descubrimiento de la fuente y despierta al cron."""
        self.write({"queue_state": "queued", "last_error": False})
        cron = self.env.ref(SOURCE_CRON_XMLID, raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        for source in self:
            source.message_post(body=_("Descubrimiento encolado."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("PIKO Import"),
                "message": _("Trabajo encolado: se ejecutará en segundo plano."),
                "type": "success",
            },
        }

    def action_enqueue_lines(self):
        """Reencola las líneas pendientes o con error de esta fuente."""
        for source in self:
            lines = source.line_ids.filtered(lambda l: l.state in ("draft", "error"))
            lines.action_retry()
        return True

    def action_test_connection(self):
        """Única acción que hace HTTP en el worker web: una sola petición."""
        self.ensure_one()
        content = self.env["tl.piko.scraper"].http_get(self, self.base_url)
        if not content:
            raise UserError(_("La URL base no devuelve contenido."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("PIKO Import"),
                "message": _("Conexión correcta (%s KB recibidos).", len(content) // 1024),
                "type": "success",
            },
        }

    # ==================================================================
    # Trabajo en cron
    # ==================================================================
    @api.model
    def _cron_run_sources(self):
        """Descubre URLs de las fuentes encoladas y encola sus líneas."""
        sources = self.search([("queue_state", "=", "queued"), ("active", "=", True)])
        for source in sources:
            if not source._try_lock():
                _logger.info("Fuente %s bloqueada por otro worker.", source.display_name)
                continue
            try:
                with self.env.cr.savepoint():
                    source.queue_state = "running"
                    created = source._discover_and_queue()
                    source.write(
                        {
                            "queue_state": "done",
                            "last_run": fields.Datetime.now(),
                            "last_error": False,
                        }
                    )
                    source.message_post(
                        body=_("Descubrimiento completado: %s líneas nuevas.", created)
                    )
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Fallo en la fuente %s", source.display_name)
                source.invalidate_recordset()
                source.write({"queue_state": "failed", "last_error": str(exc)})
            self.env.cr.commit()  # cada fuente es una unidad de trabajo
        return True

    def _discover_and_queue(self):
        """Descubre URLs, crea las líneas que falten y las pone en cola."""
        self.ensure_one()
        Line = self.env["tl.piko.product"]
        scraper = self.env["tl.piko.scraper"]
        urls = scraper.discover(self, limit=self.max_products or None)
        existing = set(
            Line.search([("source_id", "=", self.id)]).mapped("url")
        )
        new_vals = [
            {
                "source_id": self.id,
                "url": url,
                "external_id": scraper._external_id(url),
                "state": "queued",
                "next_attempt_date": fields.Datetime.now(),
            }
            for url in urls
            if url not in existing
        ]
        lines = Line.create(new_vals) if new_vals else Line
        if lines:
            Line._trigger_queue()
        return len(lines)

    @api.model
    def _cron_scheduled_sync(self, source_ids=None):
        """Cron planificado: encola todas las fuentes activas."""
        domain = [("active", "=", True)]
        if source_ids:
            domain.append(("id", "in", source_ids))
        sources = self.search(domain)
        if sources:
            sources.write({"queue_state": "queued"})
            cron = self.env.ref(SOURCE_CRON_XMLID, raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()
        return True

    # ------------------------------------------------------------------
    def action_apply_rules(self):
        """Reaplica las reglas a las líneas ya parseadas (sin HTTP)."""
        for source in self:
            source.line_ids.filtered(
                lambda l: l.state in ("parsed", "imported")
            ).action_apply_rules()
        return True

    def action_view_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Productos rastreados"),
            "res_model": "tl.piko.product",
            "view_mode": "list,form",
            "domain": [("source_id", "=", self.id)],
            "context": {"default_source_id": self.id},
        }


class TlPikoCategory(models.Model):
    _name = "tl.piko.category"
    _description = "Categoría a rastrear"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    source_id = fields.Many2one("tl.piko.source", required=True, ondelete="cascade")
    url = fields.Char(required=True, help="URL de la página de categoría.")
    paginated = fields.Boolean(
        "Paginar", default=False,
        help="Genera las URLs de página siguiendo el esquema de la tienda."
    )
    page_size = fields.Selection(
        [("18", "18"), ("50", "50"), ("100", "100")],
        "Artículos por página", default="100",
    )
    order_key = fields.Char("Orden", default="artikelnr_asc")
    page_count = fields.Integer(
        "Páginas máx.", default=1,
        help="Tope de páginas a recorrer. El rastreo se detiene antes si una "
             "página no aporta URLs nuevas."
    )
    page_pattern = fields.Char(
        "Patrón manual",
        help="Sobrescribe el esquema automático. Usa {page} (base 0) o "
             "{page1} (base 1).",
    )

    def _page_urls(self):
        """URLs de las páginas de la categoría.

        Esquema de piko-shop.de (verificado):
          página 1 -> /en/warengruppe/<slug>-<id>/l-100/o-artikelnr_asc.html
          página N -> .../l-100/o-artikelnr_asc/p-{N-1}.html   (p es base 0)
        """
        self.ensure_one()
        base = urljoin(self.source_id.base_url, self.url)
        if self.page_pattern:
            return [
                urljoin(
                    self.source_id.base_url,
                    self.page_pattern.format(page=page, page1=page + 1),
                )
                for page in range(max(1, self.page_count))
            ]
        if not self.paginated or self.page_count <= 1:
            return [base]
        stem = base[:-5] if base.endswith(".html") else base.rstrip("/")
        prefix = "%s/l-%s/o-%s" % (stem, self.page_size or "100",
                                   self.order_key or "artikelnr_asc")
        urls = ["%s.html" % prefix]
        urls += ["%s/p-%s.html" % (prefix, page)
                 for page in range(1, self.page_count)]
        return urls
