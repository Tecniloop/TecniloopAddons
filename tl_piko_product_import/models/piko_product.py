# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import base64
import hashlib
import json
import logging
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Presupuesto por pasada de cron: si se agota, la cola se auto-redispara en
# lugar de arriesgar un corte por `limit_time_real_cron`.
CRON_TIME_BUDGET = 240.0
QUEUE_CRON_XMLID = "tl_piko_product_import.ir_cron_tl_piko_queue"
QUEUE_BATCH_SIZE = 20


class TlPikoProduct(models.Model):
    """Staging + cola de trabajo.

    El trabajo pesado (HTTP) nunca se ejecuta en el worker HTTP: los botones
    solo encolan y despiertan el cron con `_trigger()`, que es el mecanismo de
    tareas asíncronas del propio core, sin necesidad de queue_job.
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
    # Cola
    # ==================================================================
    def action_enqueue(self):
        """Marca las líneas para procesar y despierta al cron."""
        self.write(
            {
                "state": "queued",
                "next_attempt_date": fields.Datetime.now(),
                "error_message": False,
            }
        )
        self._trigger_queue()
        return True

    def action_retry(self):
        """Reintenta desde cero (reinicia el contador de intentos)."""
        self.write({"attempt_count": 0})
        return self.action_enqueue()

    @api.model
    def _trigger_queue(self, at=None):
        cron = self.env.ref(QUEUE_CRON_XMLID, raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger(at=at)

    @api.model
    def _queue_domain(self):
        return [
            ("state", "=", "queued"),
            "|",
            ("next_attempt_date", "=", False),
            ("next_attempt_date", "<=", fields.Datetime.now()),
        ]

    @api.model
    def _lock_batch(self, limit=None):
        """Reserva un lote con FOR UPDATE SKIP LOCKED.

        El bloqueo es de fila y vive dentro de la transacción, así que se
        libera solo en el commit del lote y NO puede quedar huérfano si el
        worker muere. Varios crons pueden trabajar en paralelo sin pisarse:
        cada uno se salta las filas que otro tenga tomadas.
        """
        self.env.cr.execute(
            """
            SELECT id FROM tl_piko_product
             WHERE state = 'queued'
               AND (next_attempt_date IS NULL
                    OR next_attempt_date <= (now() AT TIME ZONE 'UTC'))
             ORDER BY next_attempt_date NULLS FIRST, id
             LIMIT %s
             FOR UPDATE SKIP LOCKED
            """,
            (limit or QUEUE_BATCH_SIZE,),
        )
        return self.browse([row[0] for row in self.env.cr.fetchall()])

    @api.model
    def _commit_batch(self, processed, remaining):
        """Commit por lote, usando el runner de crons si está disponible."""
        cron = self.env["ir.cron"]
        if hasattr(cron, "_commit_progress"):
            try:
                cron._commit_progress(processed=processed, remaining=remaining)
                return
            except Exception:  # noqa: BLE001  (la firma varía entre versiones)
                _logger.debug("_commit_progress no utilizable; commit directo.")
        self.env.cr.commit()

    @api.model
    def _cron_process_queue(self):
        """Procesa la cola por lotes y se redispara si queda trabajo."""
        started = time.monotonic()
        processed = 0
        while time.monotonic() - started < CRON_TIME_BUDGET:
            lines = self._lock_batch()
            if not lines:
                break
            _logger.info("Cola PIKO: lote de %s líneas.", len(lines))
            batch_sources = lines.source_id
            batch_done = 0
            for line in lines:
                if time.monotonic() - started >= CRON_TIME_BUDGET:
                    break
                line._process_one()
                processed += 1
                batch_done += 1
            remaining = self.search_count(self._queue_domain())
            for source in batch_sources:
                source.log(
                    _("Lote terminado: %(done)s procesadas, %(left)s en cola.",
                      done=batch_done, left=remaining)
                )
                source.flush_log(_("Rastreo"))
            # el commit cierra el lote y libera las filas bloqueadas
            self._commit_batch(processed, remaining)

        if not processed:
            waiting_total = self.search_count([("state", "=", "queued")])
            _logger.info(
                "Cola PIKO: nada que procesar (en cola: %s, listas ahora: %s). "
                "Si hay líneas en cola pero ninguna lista, están esperando su "
                "reintento.", waiting_total,
                self.search_count(self._queue_domain()),
            )
        self.env["tl.piko.source"].flush_all_logs(_("Rastreo"))
        pending_now = self.search(self._queue_domain(), limit=1)
        if pending_now:
            self._trigger_queue()  # queda trabajo listo: nueva pasada inmediata
        else:
            waiting = self.search(
                [("state", "=", "queued"), ("next_attempt_date", "!=", False)],
                order="next_attempt_date asc",
                limit=1,
            )
            if waiting:
                self._trigger_queue(at=waiting.next_attempt_date)  # backoff
        _logger.info("Cola PIKO: %s líneas procesadas en esta pasada.", processed)
        return True

    # ------------------------------------------------------------------
    def _process_one(self):
        """Rastrea (y opcionalmente importa) una línea de forma aislada.

        El savepoint evita que un fallo aborte la transacción del lote entero:
        así se registra el error y se sigue con la siguiente línea.
        """
        self.ensure_one()
        source = self.source_id
        try:
            with self.env.cr.savepoint():
                self._do_scrape()
                if source.auto_import and self.state == "parsed":
                    self._do_import()
            source.log(self._log_summary(), level="detail")
        except Exception as exc:  # noqa: BLE001
            self.invalidate_recordset()
            self._register_failure(str(exc))
            _logger.warning("Línea %s fallida: %s", self.url, exc)
            source.log(
                _("ERROR %(ref)s (intento %(n)s): %(err)s",
                  ref=self.default_code or self.url, n=self.attempt_count, err=exc)
            )
        return True

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
        return "%s %s: %s — %s" % (
            "OK", self.default_code or self.url.rsplit("/", 1)[-1],
            estado, " · ".join(detalles) or _("sin datos adicionales"),
        )

    def _register_failure(self, message):
        """Backoff exponencial hasta agotar los intentos de la fuente."""
        self.ensure_one()
        source = self.source_id
        attempts = self.attempt_count + 1
        vals = {
            "attempt_count": attempts,
            "last_attempt_date": fields.Datetime.now(),
            "error_message": message,
        }
        if attempts < (source.max_attempts or 3):
            delay = (source.retry_backoff_minutes or 10) * (2 ** (attempts - 1))
            vals.update(
                {
                    "state": "queued",
                    "next_attempt_date": fields.Datetime.add(
                        fields.Datetime.now(), minutes=delay
                    ),
                }
            )
        else:
            vals.update({"state": "error", "next_attempt_date": False})
        self.write(vals)

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
