# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import logging
import time
from collections import defaultdict
from urllib.parse import urljoin

from markupsafe import Markup

from odoo.addons.queue_job.exception import RetryableJobError
from odoo.addons.queue_job.job import identity_exact

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

LOG_LEVELS = {"off": 0, "summary": 1, "detail": 2, "debug": 3}
# Buffer en memoria por (bd, fuente). Se vuelca al chatter en un único mensaje
# por lote: un message_post por línea inundaría el chatter y multiplicaría los
# INSERT. Al vivir en memoria, sobrevive al rollback de un savepoint fallido.
_LOG_BUFFER = defaultdict(list)
LOG_FLUSH_AT = 200
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
    timeout = fields.Integer(
        default=60,
        help="El listado de piko-shop.de tarda ~30 s por página; 30 se queda corto.",
    )
    max_retries = fields.Integer(
        "Reintentos HTTP", default=3, help="Reintentos inmediatos dentro de una petición."
    )
    respect_robots = fields.Boolean("Respetar robots.txt", default=True)
    max_products = fields.Integer(
        "Límite por descubrimiento", default=200, help="0 = sin límite."
    )

    # --- Registro -------------------------------------------------------
    log_level = fields.Selection(
        [
            ("off", "Silencioso"),
            ("summary", "Resumen"),
            ("detail", "Detallado (una línea por ficha)"),
            ("debug", "Depuración (cada petición HTTP)"),
        ],
        "Detalle del registro",
        default="summary",
        required=True,
        help="Todo se escribe siempre en el log del servidor; esto controla "
             "qué se publica además en el chatter.",
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
        """Advisory lock transaccional por fuente.

        Sin uso en el flujo de cron desde que el descubrimiento commitea por
        página (un lock de transacción se soltaría en el primer commit). La
        serialización la da `ir.cron`, que no ejecuta dos veces el mismo cron a
        la vez. Se conserva por si hace falta en llamadas puntuales.
        """
        self.ensure_one()
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (self._lock_key(),))
        return self.env.cr.fetchone()[0]

    # ==================================================================
    # Registro
    # ==================================================================
    def log(self, message, level="summary"):
        """Apunta una línea de actividad (siempre al log, según nivel al chatter)."""
        self.ensure_one()
        _logger.info("[%s] %s", self.display_name, message)
        if LOG_LEVELS.get(self.log_level, 1) < LOG_LEVELS.get(level, 1):
            return
        key = (self.env.cr.dbname, self.id)
        _LOG_BUFFER[key].append((fields.Datetime.now(), message))
        if len(_LOG_BUFFER[key]) >= LOG_FLUSH_AT:
            self.flush_log(_("Registro parcial"))

    def flush_log(self, title=None):
        """Vuelca el buffer al chatter como un único mensaje."""
        self.ensure_one()
        entries = _LOG_BUFFER.pop((self.env.cr.dbname, self.id), [])
        if not entries:
            return False
        rows = Markup("").join(
            Markup("<li><code>%s</code> %s</li>") % (
                moment.strftime("%H:%M:%S"), message
            )
            for moment, message in entries
        )
        body = Markup("<p><b>%s</b></p><ul>%s</ul>") % (
            title or _("Actividad"), rows
        )
        self.message_post(body=body)
        return True

    @api.model
    def flush_all_logs(self, title=None):
        """Vuelca lo que quede en el buffer de cualquier fuente de esta BD."""
        dbname = self.env.cr.dbname
        ids = [sid for db, sid in list(_LOG_BUFFER) if db == dbname]
        for source in self.browse(ids).exists():
            source.flush_log(title)
        for key in [k for k in list(_LOG_BUFFER) if k[0] == dbname]:
            _LOG_BUFFER.pop(key, None)

    # ==================================================================
    # Encolado (lo que hacen los botones: nada de HTTP aquí)
    # ==================================================================
    def action_enqueue(self):
        """Encola un job de descubrimiento por categoría."""
        archived = self.filtered(lambda s: not s.active)
        if archived:
            raise UserError(
                _("La fuente %s está archivada. Actívala antes de encolarla.",
                  ", ".join(archived.mapped("name")))
            )
        self.write({"queue_state": "queued", "last_error": False})
        self.category_ids.write({
            "next_page": 0, "discovery_state": "pending", "last_page_hash": False,
        })
        total = 0
        for source in self:
            creados = source._enqueue_discovery()
            total += creados
            source.message_post(
                body=_("Descubrimiento encolado: %s jobs creados.", creados)
            )
        if not total:
            # Nunca dejar la fuente "en cola" sin trabajo real detrás: es el
            # fallo silencioso que más cuesta diagnosticar.
            self.write({"queue_state": "failed",
                        "last_error": _("No se creó ningún job.")})
            raise UserError(
                _("No se ha creado ningún job. Revisa que la fuente tenga "
                  "categorías activas sin recorrer, o usa 'Reiniciar "
                  "descubrimiento'.")
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("PIKO Import"),
                "message": _("%s jobs encolados. Míralos en Trabajos en cola.",
                             total),
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
    # Jobs
    # ==================================================================
    def _enqueue_discovery(self):
        """Un job por categoría pendiente (o uno solo si no hay categorías).

        Devuelve el nº de jobs creados; cero significa que no había nada que
        hacer y quien llama debe avisar en vez de dejarlo "en cola".
        """
        self.ensure_one()
        if not hasattr(self, "with_delay"):
            raise UserError(
                _("queue_job no está activo. Añade 'queue_job' a "
                  "server_wide_modules en odoo.conf y reinicia.")
            )
        if self.discovery_mode == "category":
            categories = self.category_ids.filtered(
                lambda c: c.active and c.discovery_state != "done"
            )
            for category in categories:
                self.with_delay(
                    description=_("Descubrir %s") % category.name,
                    identity_key=identity_exact,
                    priority=5,
                )._job_discover_page(category.id, category.next_page)
            return len(categories)
        self.with_delay(
            description=_("Descubrir %s") % self.name,
            identity_key=identity_exact,
            priority=5,
        )._job_discover_page(False, 0)
        return 1

    def _job_discover_page(self, category_id, page_index):
        """JOB: rastrea UNA página de listado y encadena la siguiente.

        Una página por job (~30 s) en lugar de un catálogo por ejecución: cada
        unidad cabe de sobra en `limit_time_real` y el avance queda guardado.
        """
        self.ensure_one()
        Line = self.env["tl.piko.product"]
        scraper = self.env["tl.piko.scraper"]
        category = self.env["tl.piko.category"].browse(category_id).exists()
        self.queue_state = "running"

        try:
            if category:
                page_urls = category._page_urls()
                if page_index >= len(page_urls):
                    return self._finish_category(category, _("sin más páginas"))
                urls = scraper.urls_from_listing(self, page_urls[page_index])
            else:
                urls = scraper.discover(self)
        except Exception as exc:  # noqa: BLE001
            if Line._is_transient(exc):
                raise RetryableJobError(
                    _("Listado no disponible: %s") % exc,
                    seconds=300,
                    ignore_retry=False,
                ) from exc
            raise

        previous = category.last_page_hash if category else False
        current = str(hash(frozenset(urls)))
        if not urls or current == previous:
            return self._finish_category(category, _("fin de la paginación"))

        existing = set(
            Line.search([("source_id", "=", self.id),
                         ("url", "in", list(urls))]).mapped("url")
        )
        nuevas = [url for url in urls if url not in existing]
        lines = Line.create([
            {
                "source_id": self.id,
                "url": url,
                "external_id": scraper._external_id(url),
            }
            for url in nuevas
        ]) if nuevas else Line
        lines.action_enqueue()

        if category:
            category.write({
                "next_page": page_index + 1,
                "last_page_hash": current,
            })
        self.log(
            _("%(cat)s pág. %(page)s: %(found)s fichas, %(new)s nuevas encoladas.",
              cat=category.name if category else self.name, page=page_index + 1,
              found=len(urls), new=len(nuevas))
        )
        self.flush_log(_("Descubrimiento"))

        if category:
            self.with_delay(
                description=_("Descubrir %(cat)s pág. %(page)s",
                              cat=category.name, page=page_index + 2),
                identity_key=identity_exact,
                priority=5,
            )._job_discover_page(category.id, page_index + 1)
        else:
            self.queue_state = "done"
        return _("%s fichas encoladas") % len(nuevas)

    def _finish_category(self, category, motivo):
        self.ensure_one()
        if category:
            category.discovery_state = "done"
            self.log(_("%(cat)s: %(motivo)s.", cat=category.name, motivo=motivo))
        pendientes = self.category_ids.filtered(
            lambda c: c.active and c.discovery_state != "done"
        )
        if not pendientes:
            self.write({"queue_state": "done", "last_run": fields.Datetime.now()})
            self.log(_("Descubrimiento completado."))
        self.flush_log(_("Descubrimiento"))
        return motivo

    @api.model
    def _cron_scheduled_sync(self, source_ids=None):
        """Cron planificado: encola el descubrimiento de las fuentes activas."""
        domain = [("active", "=", True)]
        if source_ids:
            domain.append(("id", "in", source_ids))
        for source in self.search(domain):
            source.category_ids.write({"discovery_state": "pending", "next_page": 0})
            source.queue_state = "queued"
            source._enqueue_discovery()
        return True

    @api.model
    def _cron_requeue_stuck(self, minutes=120):
        """Red de seguridad: reencola líneas en cola sin job vivo.

        Si el jobrunner se cae mientras hay jobs en vuelo, esas líneas se
        quedarían en 'queued' para siempre.
        """
        limit = fields.Datetime.subtract(fields.Datetime.now(), minutes=minutes)
        lines = self.env["tl.piko.product"].search(
            [("state", "=", "queued"), ("write_date", "<", limit)]
        )
        vivos = set(
            self.env["queue.job"].search(
                [("uuid", "in", lines.mapped("job_uuid")),
                 ("state", "in", ("pending", "enqueued", "started"))]
            ).mapped("uuid")
        )
        huerfanas = lines.filtered(lambda l: l.job_uuid not in vivos)
        if huerfanas:
            _logger.warning("Reencolando %s líneas sin job vivo.", len(huerfanas))
            huerfanas.action_enqueue()
        return len(huerfanas)

    def action_reset_discovery(self):
        """Vuelve a empezar el descubrimiento desde la primera página."""
        self.category_ids.write({
            "next_page": 0, "discovery_state": "pending", "last_page_hash": False,
        })
        for source in self:
            source.log(_("Progreso del descubrimiento reiniciado."))
            source.flush_log(_("Descubrimiento"))
        return True

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
    def action_debug_process_one(self):
        """Diagnóstico: procesa UNA línea en primer plano y muestra el error.

        Sirve para distinguir "el cron no corre" de "el rastreo falla": si esto
        funciona pero la cola no avanza, el problema es el planificador.
        """
        self.ensure_one()
        Line = self.env["tl.piko.product"]
        line = Line.search(
            [("source_id", "=", self.id), ("state", "in", ("queued", "draft", "error"))],
            limit=1,
        )
        if not line:
            # Sin líneas no hay nada que diagnosticar en la cola: el problema
            # está antes, en el descubrimiento. Lo probamos aquí mismo.
            self.log(_("Sin líneas pendientes: probando el descubrimiento."))
            urls = self.env["tl.piko.scraper"].discover(self, limit=5)
            self.log(_("El descubrimiento devuelve %s URLs (se prueban 5).",
                       len(urls)))
            if not urls:
                self.flush_log(_("Diagnóstico"))
                raise UserError(
                    _("El descubrimiento no encuentra ninguna URL de producto. "
                      "Revisa las categorías, el regex de ficha y robots.txt; "
                      "el chatter tiene el detalle de las peticiones.")
                )
            scraper = self.env["tl.piko.scraper"]
            line = Line.create(
                {
                    "source_id": self.id,
                    "url": urls[0],
                    "external_id": scraper._external_id(urls[0]),
                }
            )
        line._job_process_line()
        self.flush_log(_("Diagnóstico"))
        message = _("Línea %(url)s -> estado %(state)s. %(error)s",
                    url=line.url, state=line.state, error=line.error_message or "")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("PIKO Import"), "message": message,
                       "type": "warning" if line.error_message else "success",
                       "sticky": True},
        }

    def action_apply_rules(self):
        """Reaplica las reglas a las líneas ya parseadas (sin HTTP)."""
        for source in self:
            source.line_ids.filtered(
                lambda l: l.state in ("parsed", "imported")
            ).action_apply_rules()
        return True

    def action_view_jobs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Trabajos en cola"),
            "res_model": "queue.job",
            "view_mode": "list,form",
            "domain": [("model_name", "in",
                        ("tl.piko.source", "tl.piko.product"))],
        }

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
    next_page = fields.Integer(
        "Próxima página", default=0, readonly=True, copy=False,
        help="Índice por el que continuará el descubrimiento.",
    )
    discovery_state = fields.Selection(
        [("pending", "Pendiente"), ("done", "Recorrida")],
        default="pending", readonly=True, copy=False,
    )
    last_page_hash = fields.Char(
        "Huella de la última página", readonly=True, copy=False,
        help="Detecta que la tienda repite la última página al pasarse de rango.",
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
