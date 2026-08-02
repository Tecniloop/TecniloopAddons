# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import base64
import hashlib
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.queue_job.exception import RetryableJobError
from odoo.addons.queue_job.job import identity_exact

_logger = logging.getLogger(__name__)


class TlPikoProduct(models.Model):
    """Staging de fichas rastreadas.

    Cada ficha es un job de queue_job: la unidad de trabajo es pequeña
    (~30 s), reintentable y visible en la vista de Trabajos en cola.
    """

    _name = "tl.piko.product"
    _description = "Producto rastreado (staging)"
    _order = "source_id, default_code, id"
    _rec_name = "name"

    source_id = fields.Many2one(
        "tl.piko.source", required=True, ondelete="cascade", index=True
    )
    url = fields.Char(required=True, index=True)
    external_id = fields.Char(index=True)
    name = fields.Char()
    default_code = fields.Char("Referencia", index=True)
    barcode = fields.Char("EAN")
    brand = fields.Char("Marca")
    price = fields.Float(digits="Product Price")
    currency_name = fields.Char()
    availability = fields.Char()
    description = fields.Text()
    image_url = fields.Char()
    categ_path = fields.Char("Ruta de categoría")
    categ_external_ids = fields.Char(
        "Ids de categoría de origen", help="Ids del sitio, p.ej. 20/373/376/306."
    )
    attribute_value_ids = fields.Many2many(
        "product.attribute.value",
        string="Características detectadas",
        help="Resultado de las reglas de extracción. Editable antes de importar.",
    )
    raw_json = fields.Text("JSON-LD original", readonly=True)
    spec_json = fields.Text("Tabla de características", readonly=True)
    checksum = fields.Char(readonly=True, help="Hash del contenido, para detectar cambios.")

    state = fields.Selection(
        [
            ("draft", "Pendiente"),
            ("queued", "En cola"),
            ("parsed", "Parseado"),
            ("imported", "Importado"),
            ("skipped", "Omitido"),
            ("error", "Error"),
        ],
        default="draft",
        index=True,
        required=True,
    )
    error_message = fields.Text(readonly=True)
    job_uuid = fields.Char("Job", readonly=True, copy=False, index=True)
    attempt_count = fields.Integer("Intentos", default=0, readonly=True)
    next_attempt_date = fields.Datetime("Próximo intento", index=True, readonly=True)
    last_attempt_date = fields.Datetime(readonly=True)
    product_tmpl_id = fields.Many2one("product.template", "Producto", ondelete="set null")
    scraped_on = fields.Datetime(readonly=True)
    imported_on = fields.Datetime(readonly=True)

    # Odoo 19: models.Constraint sustituye a _sql_constraints
    _url_source_uniq = models.Constraint(
        "unique(source_id, url)", "Esa URL ya existe en la fuente."
    )

    # ==================================================================
    # Alta idempotente
    # ==================================================================
    @api.model
    def create_from_urls(self, source, urls):
        """Crea las líneas que falten, tolerando carreras entre jobs.

        Comprobar antes con un `search` no sirve: dos jobs de la misma página
        pueden pasar la comprobación a la vez y chocar contra el índice único.
        Aquí se intenta el alta en bloque y, si choca, se reintenta línea a
        línea dentro de un savepoint, quedándose con las que sí son nuevas.
        """
        scraper = self.env["tl.piko.scraper"]
        conocidas = set(
            self.search([("source_id", "=", source.id),
                         ("url", "in", list(urls))]).mapped("url")
        )
        pendientes = [url for url in urls if url not in conocidas]
        if not pendientes:
            return self.browse()

        def vals(url):
            return {
                "source_id": source.id,
                "url": url,
                "external_id": scraper._external_id(url),
            }

        try:
            with self.env.cr.savepoint():
                return self.create([vals(url) for url in pendientes])
        except Exception:  # noqa: BLE001  (IntegrityError por carrera)
            _logger.info(
                "Alta en bloque con colisión en %s: reintento línea a línea.",
                source.display_name,
            )
        creadas = self.browse()
        for url in pendientes:
            try:
                with self.env.cr.savepoint():
                    creadas |= self.create(vals(url))
            except Exception:  # noqa: BLE001
                continue  # otra ejecución se nos adelantó: no es un error
        return creadas

    # ==================================================================
    # Encolado en queue_job
    # ==================================================================
    def action_enqueue(self):
        """Crea un job por ficha.

        `identity_exact` impide duplicar el job de una línea que ya esté
        pendiente: pulsar dos veces no rastrea dos veces.
        """
        for line in self:
            line.write(
                {
                    "state": "queued",
                    "error_message": False,
                    "next_attempt_date": fields.Datetime.now(),
                }
            )
            job = line.with_delay(
                description=_("Rastrear %s") % (line.default_code or line.url),
                identity_key=identity_exact,
                max_retries=line.source_id.max_attempts or 3,
                # misma prioridad que el descubrimiento: van por canales
                # distintos, así que no compiten entre sí
                priority=5,
            )._job_process_line()
            line.job_uuid = job.uuid
        return True

    def action_retry(self):
        self.write({"attempt_count": 0})
        return self.action_enqueue()

    def _job_process_line(self):
        """JOB: rastrea e importa una ficha.

        Los fallos de red se relanzan como RetryableJobError para que
        queue_job los reintente con su propio patrón; los fallos de datos
        marcan la línea en error y no se reintentan.
        """
        self.ensure_one()
        self = self.with_context(tl_piko_single_attempt=True)
        source = self.source_id
        try:
            self._do_scrape()
            if source.auto_import and self.state == "parsed":
                self._do_import()
        except RetryableJobError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._is_transient(exc):
                delay = (source.retry_backoff_minutes or 10) * 60
                self.write({"attempt_count": self.attempt_count + 1,
                            "error_message": str(exc)})
                raise RetryableJobError(
                    _("Error temporal en %(url)s: %(err)s", url=self.url, err=exc),
                    seconds=delay,
                    ignore_retry=False,
                ) from exc
            self._register_failure(str(exc))
            source.log(_("ERROR %(ref)s: %(err)s",
                         ref=self.default_code or self.url, err=exc))
            source.flush_log(_("Rastreo"))
            return _("Error: %s") % exc
        source.log(self._log_summary(), level="detail")
        source.flush_log(_("Rastreo"))
        return self._log_summary()

    def _log_summary(self):
        """Una línea legible con lo que se ha hecho con esta ficha."""
        self.ensure_one()
        estado = {
            "parsed": _("rastreado"),
            "imported": _("importado"),
            "skipped": _("omitido"),
        }.get(self.state, self.state)
        detalles = []
        if self.price:
            detalles.append(_("%s €") % self.price)
        if self.barcode:
            detalles.append(_("EAN %s") % self.barcode)
        if self.attribute_value_ids:
            detalles.append(_("%s caract.") % len(self.attribute_value_ids))
        if self.categ_path:
            detalles.append(self.categ_path)
        if self.product_tmpl_id:
            detalles.append(_("producto #%s") % self.product_tmpl_id.id)
        return "OK %s: %s — %s" % (
            self.default_code or self.url.rsplit("/", 1)[-1], estado,
            " · ".join(detalles) or _("sin datos adicionales"),
        )

    @api.model
    def _is_transient(self, exc):
        """Distingue "el servidor no responde" de "esta ficha no sirve"."""
        text = str(exc).lower()
        marcas = ("timeout", "timed out", "connection", "temporarily",
                  "503", "502", "504", "429", "reset by peer", "ssl")
        return any(marca in text for marca in marcas)

    def _register_failure(self, message):
        """Fallo definitivo: sin reintento (de eso se encarga queue_job)."""
        self.ensure_one()
        self.write(
            {
                "attempt_count": self.attempt_count + 1,
                "last_attempt_date": fields.Datetime.now(),
                "error_message": message,
                "state": "error",
                "next_attempt_date": False,
            }
        )

    # ==================================================================
    # Trabajo real
    # ==================================================================
    def _do_scrape(self):
        """Descarga y parsea. Sin commits: commitea el cron."""
        self.ensure_one()
        scraper = self.env["tl.piko.scraper"]
        vals = scraper.parse_product(self.source_id, self.url)
        if not vals or not (vals.get("name") or vals.get("default_code")):
            raise UserError(_("No se han encontrado datos de producto en %s") % self.url)
        payload = "|".join(
            str(vals.get(k) or "")
            for k in ("name", "default_code", "barcode", "price", "description")
        )
        vals.update(
            {
                "state": "parsed",
                "error_message": False,
                "scraped_on": fields.Datetime.now(),
                "last_attempt_date": fields.Datetime.now(),
                "next_attempt_date": False,
                "checksum": hashlib.sha1(payload.encode()).hexdigest(),
            }
        )
        self.write({k: v for k, v in vals.items() if k in self._fields})
        if self.source_id.apply_attribute_rules:
            self.action_apply_rules()
        return True

    def action_scrape(self):
        """Ejecución manual e inmediata, solo para depurar pocas líneas."""
        if len(self) > 10:
            raise UserError(
                _("Para más de 10 líneas usa 'Encolar': el rastreo síncrono "
                  "bloquea la sesión y puede agotar el tiempo de la petición.")
            )
        for line in self:
            try:
                with self.env.cr.savepoint():
                    line._do_scrape()
            except Exception as exc:  # noqa: BLE001
                line.invalidate_recordset()
                line._register_failure(str(exc))
                line.source_id.flush_log(_("Diagnóstico"))
        return True

    # ------------------------------------------------------------------
    def action_apply_rules(self):
        """Relanza las reglas de características sobre estas líneas."""
        Rule = self.env["tl.piko.attribute.rule"]
        for line in self:
            values = Rule.apply_to_line(line)
            line.attribute_value_ids = [(6, 0, values.ids)]
        return True

    def _spec_dict(self):
        """Tabla de características con las claves en minúsculas."""
        self.ensure_one()
        if not self.spec_json:
            return {}
        try:
            data = json.loads(self.spec_json)
        except ValueError:
            return {}
        return {str(k).strip().rstrip(":").lower(): v for k, v in data.items()}

    def _spec_value(self, label):
        self.ensure_one()
        if not label:
            return ""
        return self._spec_dict().get(label.strip().rstrip(":").lower(), "")

    # ------------------------------------------------------------------
    # Categorías
    # ------------------------------------------------------------------
    def _crumbs(self):
        """[(nombre, id externo), ...] a partir de la ruta rastreada."""
        self.ensure_one()
        names = [n.strip() for n in (self.categ_path or "").split("/") if n.strip()]
        ids = [i.strip() for i in (self.categ_external_ids or "").split("/") if i.strip()]
        if ids and len(ids) == len(names):
            return list(zip(names, ids))
        return [(name, False) for name in names]

    def _get_or_create_chain(self, model, crumbs, root=None, only_leaf=False):
        """Crea/recupera la cadena de categorías y devuelve el recordset.

        Empareja primero por id externo del sitio y, si no, por nombre dentro
        del mismo padre: así renombrar en PIKO no duplica el árbol.
        """
        self.ensure_one()
        Category = self.env[model]
        parent = root or Category.browse()
        chain = Category.browse()
        for name, external_id in crumbs:
            domain = [("parent_id", "=", parent.id or False)]
            category = Category.browse()
            if external_id:
                category = Category.search(
                    [("piko_external_id", "=", external_id)], limit=1
                )
            if not category:
                category = Category.search(domain + [("name", "=", name)], limit=1)
            if not category:
                category = Category.create(
                    {
                        "name": name,
                        "parent_id": parent.id or False,
                        "piko_external_id": external_id or False,
                    }
                )
            elif external_id and not category.piko_external_id:
                category.piko_external_id = external_id
            chain |= category
            parent = category
        if only_leaf:
            return chain[-1:] if chain else chain
        return chain

    def _get_product_categ(self):
        """Categoría contable según el modo de la fuente."""
        self.ensure_one()
        source = self.source_id
        root = source.product_categ_id
        crumbs = self._crumbs()
        if source.categ_mode == "fixed" or not crumbs:
            return root
        if source.categ_mode == "first":
            crumbs = crumbs[:1]
        chain = self._get_or_create_chain("product.category", crumbs, root=root)
        return chain[-1:] or root

    def _get_public_categs(self):
        """Categorías de eCommerce (vacío si website_sale no está instalado)."""
        self.ensure_one()
        source = self.source_id
        if source.public_categ_mode == "none":
            return None
        if "product.public.category" not in self.env:
            return None
        crumbs = self._crumbs()
        if not crumbs:
            return None
        return self._get_or_create_chain(
            "product.public.category", crumbs,
            only_leaf=source.public_categ_mode == "leaf",
        )

    def _sync_public_categories(self, product):
        """Añade sin quitar: las categorías puestas a mano se respetan."""
        self.ensure_one()
        categories = self._get_public_categs()
        if not categories:
            return
        product.write(
            {"public_categ_ids": [(4, category.id) for category in categories]}
        )

    def _sync_template_attributes(self, product):
        """Vuelca las características como líneas de atributo `no_variant`."""
        self.ensure_one()
        if not (self.source_id.update_attributes and self.attribute_value_ids):
            return
        by_attribute = {}
        for value in self.attribute_value_ids:
            by_attribute.setdefault(
                value.attribute_id, self.env["product.attribute.value"]
            )
            by_attribute[value.attribute_id] |= value
        for attribute, values in by_attribute.items():
            if attribute.create_variant != "no_variant":
                continue  # seguridad: jamás generamos variantes desde el scraping
            attr_line = product.attribute_line_ids.filtered(
                lambda l, a=attribute: l.attribute_id == a
            )
            if attr_line:
                attr_line.value_ids = [(6, 0, values.ids)]
            else:
                product.write(
                    {
                        "attribute_line_ids": [
                            (0, 0, {"attribute_id": attribute.id,
                                    "value_ids": [(6, 0, values.ids)]})
                        ]
                    }
                )

    # ------------------------------------------------------------------
    def _find_product(self):
        """Emparejamiento: vínculo previo -> id externo -> referencia -> EAN."""
        self.ensure_one()
        Template = self.env["product.template"]
        if self.product_tmpl_id:
            return self.product_tmpl_id
        product = Template.search(
            [("piko_external_id", "=", self.external_id),
             ("piko_source_id", "=", self.source_id.id)], limit=1
        )
        if not product and self.default_code:
            product = Template.search([("default_code", "=", self.default_code)], limit=1)
        if not product and self.barcode:
            product = Template.search([("barcode", "=", self.barcode)], limit=1)
        return product

    def _prepare_product_vals(self, product=None):
        """Reglas: no pisar datos introducidos a mano, no vaciar campos."""
        self.ensure_one()
        source = self.source_id
        vals = {}
        if not product:
            vals.update(
                {
                    "name": self.name or self.default_code or self.url,
                    "type": source.product_type,
                    "categ_id": (self._get_product_categ().id
                                 or source.product_categ_id.id or False),
                    "default_code": self.default_code or False,
                    "sale_ok": True,
                    "purchase_ok": True,
                }
            )
            if self.price:
                vals["list_price"] = self.price
            if self.barcode:
                vals["barcode"] = self.barcode
        else:
            if product.piko_no_overwrite:
                return {}
            if source.update_name and self.name:
                vals["name"] = self.name
            if source.update_price and self.price and not product.piko_price_locked:
                vals["list_price"] = self.price
            if source.update_barcode and self.barcode and not product.barcode:
                vals["barcode"] = self.barcode
            if not product.default_code and self.default_code:
                vals["default_code"] = self.default_code
            if source.update_categ:
                categ = self._get_product_categ()
                if categ:
                    vals["categ_id"] = categ.id
        if source.update_description and self.description:
            vals["description_sale"] = self.description
        vals.update(
            {
                "piko_source_id": source.id,
                "piko_external_id": self.external_id,
                "piko_url": self.url,
                "piko_last_sync": fields.Datetime.now(),
            }
        )
        return vals

    def _do_import(self):
        self.ensure_one()
        source = self.source_id
        product = self._find_product()
        skip_vals = {"state": "skipped", "next_attempt_date": False}
        if not product and not source.create_products:
            self.write(skip_vals)
            return True
        if product and not source.update_existing:
            self.write(dict(skip_vals, product_tmpl_id=product.id))
            return True
        vals = self._prepare_product_vals(product)
        if product and not vals:
            self.write(dict(skip_vals, product_tmpl_id=product.id))
            return True
        if product:
            product.write(vals)
        else:
            product = self.env["product.template"].create(vals)
        self._sync_template_attributes(product)
        self._sync_public_categories(product)
        self._import_image(product)
        self.write(
            {
                "state": "imported",
                "product_tmpl_id": product.id,
                "imported_on": fields.Datetime.now(),
                "error_message": False,
                "next_attempt_date": False,
            }
        )
        return True

    def action_import(self):
        """Importación manual de líneas ya parseadas (sin HTTP salvo imagen)."""
        for line in self:
            try:
                with self.env.cr.savepoint():
                    line._do_import()
            except Exception as exc:  # noqa: BLE001
                line.invalidate_recordset()
                line._register_failure(str(exc))
        return True

    def _import_image(self, product):
        self.ensure_one()
        if not (self.source_id.import_images and self.image_url) or product.image_1920:
            return
        content = self.env["tl.piko.scraper"].http_get_binary(
            self.source_id, self.image_url
        )
        if content:
            product.image_1920 = base64.b64encode(content)

    # ------------------------------------------------------------------
    def action_reset(self):
        return self.write(
            {
                "state": "draft",
                "error_message": False,
                "attempt_count": 0,
                "next_attempt_date": False,
            }
        )

    def action_open_url(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.url, "target": "new"}

    @api.model
    def _gc_lines(self, days=180):
        """Limpieza de líneas importadas antiguas (cron opcional)."""
        limit_date = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        self.search(
            [("state", "=", "imported"), ("imported_on", "<", limit_date)]
        ).unlink()
        return True
