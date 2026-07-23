# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import base64
import logging

from odoo import api, fields, models, _
from odoo.tools.float_utils import float_compare

from ..exceptions import SuenlaceImportError, missing_journal
from . import suenlace_parser as parser
from . import suenlace_partner_utils as partner_utils

_logger = logging.getLogger(__name__)


class SuenlaceImport(models.Model):
    """Lote de importación de un fichero SUENLACE.DAT.

    Flujo:
      draft -> (Parsear) -> parsed -> (Procesar) -> done / error

    El módulo base procesa el fichero de forma síncrona. La integración
    asíncrona es opcional y se incorpora instalando el complemento
    ``tl_suenlace_import_queue_job``.
    """

    _name = "tl.suenlace.import"
    _description = "Importación de fichero SUENLACE (a3asesor)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("Nuevo"),
    )
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    file_data = fields.Binary(
        string="Fichero SUENLACE", required=True, attachment=True)
    file_name = fields.Char(string="Nombre del fichero")
    encoding = fields.Char(
        string="Codificación",
        help="Vacío = autodetección (a3 suele usar CP1252).",
    )
    state = fields.Selection(
        [("draft", "Borrador"),
         ("queued", "En cola"),
         ("parsed", "Parseado"),
         ("processing", "Procesando"),
         ("done", "Procesado"),
         ("error", "Con errores")],
        default="draft",
        tracking=True,
        string="Estado",
    )
    post_moves = fields.Boolean(
        string="Contabilizar asientos",
        default=False,
        help="Si se marca, los asientos y facturas creados se publican; "
             "de lo contrario quedan en borrador para revisión.",
    )
    associate_partners = fields.Boolean(
        string="Asociar terceros en asientos",
        default=lambda self: self.env.company.suenlace_associate_partners,
        help=(
            "Asigna partner_id a los asientos tipo 0 y a las facturas que se "
            "importen como asiento literal. Cuando se crean facturas Odoo, "
            "el cliente o proveedor es obligatorio y siempre se identifica."
        ),
    )
    skip_vat_validation = fields.Boolean(
        string="Omitir validación del NIF de Odoo",
        default=lambda self: self.env.company.suenlace_skip_vat_validation,
        help=(
            "Permite crear o actualizar terceros de este lote aunque el NIF "
            "no supere la validación estándar de Odoo. El NIF se conserva "
            "normalizado y, para España, con el prefijo ES. No afecta a "
            "altas o modificaciones realizadas fuera de SUENLACE."
        ),
    )
    associate_taxes = fields.Boolean(
        string="Interpretar impuestos y crear facturas",
        default=lambda self: self.env.company.suenlace_associate_taxes,
        help=(
            "Desactivado: todos los documentos, incluidas las facturas de "
            "registros 1/2+9, se importan como asientos y se conservan las "
            "cuentas originales del DAT sin sustitución fiscal. Activado: "
            "las facturas se crean como facturas Odoo con impuestos y los "
            "asientos tipo 0 pueden interpretar subcuentas fiscales mapeadas."
        ),
    )
    journal_misc_id = fields.Many2one(
        "account.journal",
        string="Diario de asientos varios",
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
    )
    journal_sale_id = fields.Many2one(
        "account.journal",
        string="Diario de ventas",
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id)]",
    )
    journal_purchase_id = fields.Many2one(
        "account.journal",
        string="Diario de compras",
        domain="[('type', '=', 'purchase'), ('company_id', '=', company_id)]",
    )
    line_ids = fields.One2many(
        "tl.suenlace.import.line", "import_id", string="Registros")
    line_count = fields.Integer(
        string="Nº registros", readonly=True, copy=False)
    partner_ids = fields.Many2many(
        "res.partner", string="Terceros creados", copy=False)
    account_ids = fields.Many2many(
        "account.account", string="Cuentas creadas", copy=False)
    move_ids = fields.Many2many(
        "account.move", string="Asientos creados", copy=False)
    move_count = fields.Integer(
        string="Nº documentos", readonly=True, copy=False)
    log = fields.Text(string="Registro de proceso", readonly=True)

    # ------------------------------------------------------------------ #
    #  Compute                                                           #
    # ------------------------------------------------------------------ #
    @api.onchange("company_id")
    def _onchange_company_suenlace_options(self):
        for rec in self:
            if rec.company_id:
                rec.associate_partners = (
                    rec.company_id.suenlace_associate_partners
                )
                rec.skip_vat_validation = (
                    rec.company_id.suenlace_skip_vat_validation
                )
                rec.associate_taxes = rec.company_id.suenlace_associate_taxes

    # ------------------------------------------------------------------ #
    #  CRUD                                                              #
    # ------------------------------------------------------------------ #
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                seq = self.env["ir.sequence"].next_by_code(
                    "tl.suenlace.import")
                vals["name"] = seq or _("Import/%s") % fields.Date.today()
        return super().create(vals_list)

    # ------------------------------------------------------------------ #
    #  Utilidades                                                        #
    # ------------------------------------------------------------------ #
    def _append_log(self, message):
        self.ensure_one()
        self.log = (self.log or "") + message + "\n"
        _logger.info("[SUENLACE %(name)s] %(msg)s",
                     {"name": self.name, "msg": message})

    def _read_records(self):
        self.ensure_one()
        raw = base64.b64decode(self.file_data)
        return list(parser.iter_records(raw, encoding=self.encoding or None))

    # ------------------------------------------------------------------ #
    #  Acciones de usuario                                               #
    # ------------------------------------------------------------------ #
    def action_parse(self):
        """Parsea el fichero en el proceso actual."""
        for rec in self:
            if not rec.file_data:
                raise SuenlaceImportError(
                    _("Debe adjuntar un fichero SUENLACE."))
            rec.job_parse()
        return True

    def action_process(self):
        """Procesa el fichero en el proceso actual."""
        for rec in self:
            if rec.state == "draft":
                rec.job_parse()
            rec.job_process()
        return True

    def action_reset_draft(self):
        self.write({"state": "draft", "log": ""})
        self.line_ids.unlink()

    # ------------------------------------------------------------------ #
    #  Operaciones de parseo y procesado                                #
    # ------------------------------------------------------------------ #
    def job_parse(self):
        """Job: parsea el fichero y almacena las líneas."""
        self.ensure_one()
        self.line_ids.unlink()
        line_model = self.env["tl.suenlace.import.line"]
        vals_list = []
        counts = {}
        for num, data in self._read_records():
            rtype = data.get("_type")
            counts[rtype] = counts.get(rtype, 0) + 1
            vals_list.append({
                "import_id": self.id,
                "sequence": num,
                "record_type": rtype,
                "payload": repr(data),
                "unsupported": bool(data.get("_unsupported")),
            })
        line_model.create(vals_list)
        self.line_count = len(vals_list)
        summary = ", ".join(
            "%s=%d" % (k, v) for k, v in sorted(counts.items()))
        self._append_log(
            _("Parseados %(n)d registros: %(s)s")
            % {"n": len(vals_list), "s": summary})
        self.state = "parsed"
        return True

    def job_process(self):
        """Job: procesa los registros y crea los documentos en Odoo."""
        self.ensure_one()
        self.state = "processing"
        self.log = ""
        if self.skip_vat_validation:
            self._append_log(
                _("Validación de NIF de Odoo omitida para los terceros "
                  "creados o actualizados por este lote."))
        records = [data for _num, data in self._read_records()]
        try:
            self._process_records(records)
            self.state = "done"
        except Exception as exc:  # noqa: BLE001
            self.state = "error"
            self._append_log(_("ERROR: %s") % exc)
            raise
        return True

    # ------------------------------------------------------------------ #
    #  Motor de procesado (fases)                                        #
    # ------------------------------------------------------------------ #
    def _process_records(self, records):
        c_records = [r for r in records
                     if r["_type"] in ("C", "CB", "CR", "CF")]
        self._process_accounts_partners(c_records)
        self._process_documents(records)
        n_count = len([r for r in records if r["_type"] == "N"])
        if n_count:
            self._append_log(
                _("%d registros de modelo 190 (tipo N) parseados. La "
                  "generación del 190 requiere l10n_es_aeat_mod190; los datos "
                  "quedan disponibles en las líneas del lote.") % n_count)

    # ---- Fase 1: cuentas y terceros ------------------------------------ #
    def _process_accounts_partners(self, c_records):
        created_accounts = self.env["account.account"]
        created_partners = self.env["res.partner"]
        for rec in c_records:
            if rec["_type"] != "C":
                self._apply_partner_extension(rec)
                continue
            cuenta = rec.get("cuenta")
            if not cuenta:
                continue
            is_third = cuenta[:3] in (
                "430", "400", "410", "431", "440"
            )
            if is_third or rec.get("nif"):
                partner = self._upsert_partner(rec)
                if partner:
                    created_partners |= partner
            account = self._upsert_account(
                rec.get("cuenta"), rec.get("cuenta_desc")
            )
            if account:
                created_accounts |= account
        self.partner_ids = [(4, p.id) for p in created_partners]
        self.account_ids = [(4, a.id) for a in created_accounts]
        self._append_log(
            _("Cuentas creadas/actualizadas: %(a)d; terceros: %(p)d")
            % {"a": len(created_accounts), "p": len(created_partners)}
        )

    def _upsert_account(self, code, name):
        if not code:
            return self.env["account.account"]
        account_model = self.env["account.account"]
        account = account_model.search([
            ("code", "=", code),
            ("company_ids", "in", self.company_id.id),
        ], limit=1)
        if account:
            return account
        account_type = self._guess_account_type(code)
        values = {
            "code": code,
            "name": name or code,
            "account_type": account_type,
            "company_ids": [(4, self.company_id.id)],
        }
        if account_type in ("asset_receivable", "liability_payable"):
            values["reconcile"] = True
        try:
            # El savepoint evita dejar toda la transacción abortada si una
            # cuenta concreta no puede crearse durante un lote voluminoso.
            with self.env.cr.savepoint():
                account = account_model.create(values)
        except Exception as exc:  # noqa: BLE001
            self._append_log(
                _("No se pudo crear la cuenta %(c)s: %(e)s")
                % {"c": code, "e": exc})
            return account_model.browse()
        return account

    @staticmethod
    def _guess_account_type(code):
        """Heurística de tipo de cuenta según el PGC español."""
        if not code:
            return "asset_current"
        by_prefix = {
            "472": "asset_current",
            "473": "asset_current",
            "475": "liability_current",
            "476": "liability_current",
            "477": "liability_current",
        }
        for prefix, account_type in by_prefix.items():
            if code.startswith(prefix):
                return account_type
        by_prefix2 = {
            "43": "asset_receivable",
            "44": "asset_receivable",
            "40": "liability_payable",
            "41": "liability_payable",
            "47": "asset_current",
            "57": "asset_cash",
        }
        if code[:2] in by_prefix2:
            return by_prefix2[code[:2]]
        by_first = {
            "1": "equity",
            "2": "asset_fixed",
            "3": "asset_current",
            "5": "asset_current",
            "6": "expense",
            "7": "income",
        }
        return by_first.get(code[0], "asset_current")

    def _suenlace_partner_context(self):
        """Contexto limitado al alta/actualización de terceros del lote.

        ``base_vat`` soporta oficialmente ``no_vat_validation`` para cargas
        procedentes de plataformas externas. No se altera la validación global
        ni se modifica el comportamiento manual de ``res.partner``.
        """
        self.ensure_one()
        return {
            "no_vat_validation": bool(self.skip_vat_validation),
        }

    def _suenlace_partner_model(self):
        self.ensure_one()
        return self.env["res.partner"].with_context(
            active_test=False,
            **self._suenlace_partner_context(),
        )

    def _suenlace_partner_record(self, partner):
        self.ensure_one()
        return partner.with_context(**self._suenlace_partner_context())

    def _upsert_partner(self, rec):
        """Localiza o crea un tercero sin duplicarlo por variaciones del NIF.

        Prioridad de identificación: NIF normalizado, cuenta SUENLACE (``ref``)
        y, de forma conservadora, nombre exacto corroborado por otros datos.
        Los datos recibidos completan huecos del tercero existente; no pisan
        información ya mantenida manualmente salvo la normalización del NIF.
        """
        return self._find_or_create_partner(rec)

    def _find_or_create_partner(self, rec, force_name=False):
        partner_model = self._suenlace_partner_model()
        country_code = rec.get("pais")
        nif = partner_utils.normalize_vat(rec.get("nif"), country_code)
        account_code = (rec.get("cuenta") or "").strip()
        name = (rec.get("nombre") or rec.get("cuenta_desc") or nif or "").strip()

        partner = self._find_partner_by_vat(nif, country_code)
        match_method = "vat" if partner else False

        if not partner and account_code:
            candidate = self._find_partner_by_ref(account_code)
            if candidate and self._partner_vat_conflicts(candidate, nif):
                self._append_log(
                    _("La cuenta SUENLACE %(account)s pertenece a %(partner)s "
                      "con NIF %(vat)s, distinto de %(incoming)s. Se crea un "
                      "tercero separado para evitar una asociación incorrecta.")
                    % {
                        "account": account_code,
                        "partner": candidate.display_name,
                        "vat": candidate.vat or _("sin NIF"),
                        "incoming": nif,
                    })
            else:
                partner = candidate
                match_method = "ref" if partner else False

        if not partner and name:
            candidate = self._find_partner_by_name(rec, name)
            if candidate and not self._partner_vat_conflicts(candidate, nif):
                partner = candidate
                match_method = "name"

        vals = self._prepare_partner_vals(rec, nif=nif, name=name)
        if partner:
            partner = partner.commercial_partner_id
            self._update_existing_partner(
                partner, vals, incoming_vat=nif,
                account_code=account_code, force_name=force_name,
            )
            if match_method == "name":
                self._append_log(
                    _("Tercero %(partner)s asociado por nombre exacto al no "
                      "existir coincidencia por NIF o cuenta.")
                    % {"partner": partner.display_name})
        else:
            partner = partner_model.create(vals)

        self._apply_partner_roles(
            partner, account_code, invoice_type=rec.get("tipo_factura"))
        self._apply_partner_account_properties(
            partner,
            account_code,
            rec.get("cuenta_desc") or rec.get("nombre"),
        )
        return partner

    def _company_partner_domain(self):
        return [("company_id", "in", [False, self.company_id.id])]

    def _find_partner_by_vat(self, nif, country_code=None):
        if not nif:
            return self.env["res.partner"]
        partner_model = self.env["res.partner"].with_context(active_test=False)
        canonical = partner_utils.normalize_vat(nif, country_code)
        local = partner_utils.vat_local_part(canonical, country_code)
        variants = list({canonical, local})
        candidates = partner_model.search(
            self._company_partner_domain() + [("vat", "in", variants)])
        partner = self._select_matching_vat_partner(candidates, canonical)
        if partner:
            return partner

        # Compatibilidad con NIF antiguos guardados con espacios, puntos o
        # guiones. Se buscan fragmentos y la igualdad real se valida después
        # de eliminar todos los separadores en Python.
        digits = "".join(ch for ch in local if ch.isdigit())
        tokens = [local[-4:], digits[-4:], digits[-3:]]
        for token in dict.fromkeys(t for t in tokens if len(t) >= 3):
            candidates = partner_model.search(
                self._company_partner_domain()
                + [("vat", "ilike", token)],
                limit=500,
            )
            partner = self._select_matching_vat_partner(candidates, canonical)
            if partner:
                return partner
        return self.env["res.partner"]

    def _select_matching_vat_partner(self, candidates, canonical):
        matches = candidates.filtered(
            lambda p: partner_utils.normalize_vat(
                p.vat, p.country_id.code if p.country_id else None
            ) == canonical
        ).mapped("commercial_partner_id")
        if not matches:
            return self.env["res.partner"]
        ordered = matches.sorted(
            key=lambda p: (
                p.company_id != self.company_id,
                p.company_type != "company",
                not p.active,
                p.id,
            )
        )
        return ordered[:1]

    def _find_partner_by_ref(self, account_code):
        if not account_code:
            return self.env["res.partner"]
        partners = self.env["res.partner"].with_context(active_test=False).search(
            self._company_partner_domain() + [("ref", "=", account_code)]
        ).mapped("commercial_partner_id")
        if not partners:
            return self.env["res.partner"]
        ordered = partners.sorted(
            key=lambda p: (
                p.company_id != self.company_id,
                p.company_type != "company",
                not p.active,
                p.id,
            )
        )
        if len(ordered) > 1:
            self._append_log(
                _("Hay varios terceros con la referencia %(ref)s; se usa %(p)s.")
                % {"ref": account_code, "p": ordered[0].display_name})
        return ordered[:1]

    def _find_partner_by_name(self, rec, name):
        partner_model = self.env["res.partner"].with_context(active_test=False)
        candidates = partner_model.search(
            self._company_partner_domain() + [("name", "=ilike", name)],
            limit=20,
        ).mapped("commercial_partner_id")
        if not candidates:
            normalized_name = partner_utils.normalize_name(name)
            if not normalized_name:
                return partner_model.browse()
            search_token = next(
                (part for part in normalized_name.split() if len(part) >= 4),
                normalized_name,
            )
            broad_candidates = partner_model.search(
                self._company_partner_domain()
                + [("name", "ilike", search_token)],
                limit=100,
            ).mapped("commercial_partner_id")
            candidates = broad_candidates.filtered(
                lambda p: partner_utils.normalize_name(p.name)
                == normalized_name
            )
        # Deduplicar posibles contactos hijos que apunten al mismo comercial.
        candidates = partner_model.browse(list(dict.fromkeys(candidates.ids)))
        if len(candidates) != 1:
            return partner_model.browse()
        candidate = candidates[0]

        incoming_email = (rec.get("email") or "").strip().lower()
        incoming_zip = (rec.get("cp") or "").strip()
        incoming_phone = partner_utils.normalize_phone(rec.get("telefono"))
        corroborated = any([
            incoming_email and (candidate.email or "").strip().lower()
            == incoming_email,
            incoming_zip and (candidate.zip or "").strip() == incoming_zip,
            incoming_phone and partner_utils.normalize_phone(candidate.phone)
            == incoming_phone,
        ])
        # Si no hay ningún dato adicional, solo se acepta una coincidencia
        # única y exacta cuando tampoco se ha recibido NIF.
        if corroborated or not rec.get("nif") or not candidate.vat:
            return candidate
        return partner_model.browse()

    def _partner_vat_conflicts(self, partner, incoming_vat):
        if not partner or not incoming_vat or not partner.vat:
            return False
        return not partner_utils.vat_equivalent(
            partner.vat,
            incoming_vat,
            partner.country_id.code if partner.country_id else None,
        )

    def _prepare_partner_vals(self, rec, nif, name):
        country = self._resolve_country(rec.get("pais"))
        if nif.startswith("ES") and not country:
            country = self.env.ref("base.es", raise_if_not_found=False)
        state = self._resolve_state(rec.get("provincia"), country)
        street = self._compose_street(rec)
        street2 = self._compose_street2(rec)
        account_code = (rec.get("cuenta") or "").strip()
        vals = {
            "name": name or nif or _("Tercero SUENLACE"),
            "vat": nif or False,
            "street": street,
            "street2": street2,
            "city": rec.get("municipio") or False,
            "zip": rec.get("cp") or False,
            "phone": rec.get("telefono") or False,
            "email": rec.get("email") or False,
            # Los registros C y las cabeceras 1/2 representan cuentas de
            # clientes/proveedores. Se crean como compañías aunque el NIF
            # tenga formato de persona física.
            "company_type": "company",
            "ref": account_code or False,
        }
        if country:
            vals["country_id"] = country.id
        if state:
            vals["state_id"] = state.id
        if "fax" in self.env["res.partner"]._fields and rec.get("fax"):
            vals["fax"] = rec["fax"]
        return vals

    def _update_existing_partner(
            self, partner, vals, incoming_vat, account_code, force_name=False):
        write_vals = {}
        for field_name, value in vals.items():
            if not value or field_name not in partner._fields:
                continue
            if field_name == "vat":
                if not partner.vat or partner_utils.vat_equivalent(
                        partner.vat, incoming_vat,
                        partner.country_id.code if partner.country_id else None):
                    if partner.vat != incoming_vat:
                        write_vals["vat"] = incoming_vat
                continue
            if field_name == "ref":
                if not partner.ref:
                    write_vals["ref"] = value
                elif partner.ref != value:
                    self._append_log(
                        _("El tercero %(partner)s ya tiene referencia %(old)s; "
                          "no se sustituye por %(new)s.")
                        % {
                            "partner": partner.display_name,
                            "old": partner.ref,
                            "new": value,
                        })
                continue
            if field_name == "name" and force_name:
                if partner.name != value:
                    write_vals["name"] = value
                continue
            if field_name == "company_type":
                # Todo tercero tratado por SUENLACE representa la cuenta
                # contable de un cliente/proveedor y debe quedar como compañía,
                # también cuando ya existía por una importación anterior.
                if partner.company_type != value:
                    write_vals[field_name] = value
                continue
            current = partner[field_name]
            if not current:
                write_vals[field_name] = value
        if write_vals:
            self._suenlace_partner_record(partner).write(write_vals)

    def _apply_partner_roles(self, partner, account_code, invoice_type=None):
        if not partner:
            return
        vals = {}
        if account_code.startswith(("43", "44")) or invoice_type == "1":
            vals["customer_rank"] = max(partner.customer_rank, 1)
        if account_code.startswith(("40", "41")) or invoice_type in ("2", "3"):
            vals["supplier_rank"] = max(partner.supplier_rank, 1)
        if vals:
            partner.write(vals)

    def _apply_partner_account_properties(
            self, partner, account_code, account_name=None):
        """Asigna al tercero la subcuenta a3 de cliente/proveedor.

        Odoo guarda las cuentas por cobrar y por pagar como propiedades
        dependientes de compañía. Una cuenta 43/44 se asigna como cuenta a
        cobrar y una cuenta 40/41 como cuenta a pagar. Si el mismo tercero
        aparece en ambos ámbitos, se conservan ambas propiedades.
        """
        if not partner:
            return
        account_code = (account_code or "").strip()
        if account_code.startswith(("43", "44")):
            property_field = "property_account_receivable_id"
            expected_type = "asset_receivable"
            role_label = _("cuenta a cobrar")
        elif account_code.startswith(("40", "41")):
            property_field = "property_account_payable_id"
            expected_type = "liability_payable"
            role_label = _("cuenta a pagar")
        else:
            return

        account = self._upsert_account(
            account_code,
            account_name or partner.display_name or account_code,
        )
        if not account:
            self._append_log(
                _("No se pudo crear o localizar la cuenta %(account)s para "
                  "asignarla como %(role)s de %(partner)s.") % {
                    "account": account_code,
                    "role": role_label,
                    "partner": partner.display_name,
                }
            )
            return
        if account.account_type != expected_type:
            self._append_log(
                _("La cuenta %(account)s no se asigna como %(role)s de "
                  "%(partner)s porque su tipo es %(actual)s y se esperaba "
                  "%(expected)s.") % {
                    "account": account.display_name,
                    "role": role_label,
                    "partner": partner.display_name,
                    "actual": account.account_type,
                    "expected": expected_type,
                }
            )
            return

        commercial_partner = partner.commercial_partner_id.with_company(
            self.company_id
        )
        current_account = commercial_partner[property_field]
        if current_account == account:
            return
        self._suenlace_partner_record(commercial_partner).write({
            property_field: account.id,
        })
        self._append_log(
            _("Asignada %(account)s como %(role)s de %(partner)s para la "
              "compañía %(company)s.") % {
                "account": account.display_name,
                "role": role_label,
                "partner": commercial_partner.display_name,
                "company": self.company_id.display_name,
            }
        )

    @staticmethod
    def _compose_street(rec):
        parts = [rec.get("siglas_via"), rec.get("via_publica"),
                 rec.get("numero")]
        return " ".join(p.strip() for p in parts if p and p.strip()) or False

    @staticmethod
    def _compose_street2(rec):
        parts = []
        if rec.get("escalera"):
            parts.append(_("Esc. %s") % rec["escalera"].strip())
        if rec.get("piso"):
            parts.append(_("Piso %s") % rec["piso"].strip())
        if rec.get("puerta"):
            parts.append(_("Puerta %s") % rec["puerta"].strip())
        return ", ".join(parts) or False

    def _resolve_country(self, code):
        country_model = self.env["res.country"]
        if not code:
            return country_model.browse()
        code = partner_utils.compact_vat(code)
        if code in ("011", "ES", "ESP", "724"):
            return self.env.ref("base.es", raise_if_not_found=False) \
                or country_model.browse()
        if len(code) == 2:
            return country_model.search([("code", "=", code)], limit=1)
        return country_model.browse()

    def _resolve_state(self, province, country):
        if not province or not country:
            return self.env["res.country.state"]
        province = province.strip()
        state_model = self.env["res.country.state"]
        if not province:
            return state_model.browse()
        state = state_model.search([
            ("country_id", "=", country.id),
            "|", ("code", "=ilike", province),
            ("name", "=ilike", province),
        ], limit=1)
        if state:
            return state
        normalized = partner_utils.normalize_name(province)
        if not normalized:
            return state_model.browse()
        states = state_model.search([("country_id", "=", country.id)])
        return states.filtered(
            lambda item: (
                partner_utils.normalize_name(item.name) == normalized
                or partner_utils.normalize_name(item.name).startswith(normalized)
                or normalized.startswith(partner_utils.normalize_name(item.name))
            )
        )[:1]

    def _apply_partner_extension(self, rec):
        nif = partner_utils.normalize_vat(rec.get("nif"))
        partner = self._find_partner_by_vat(nif)
        extension_name = rec.get("nombre") or rec.get("nombre_fiscal")
        if not partner and extension_name:
            partner = self._find_or_create_partner({
                "nif": nif,
                "nombre": extension_name,
            })
        if not partner:
            return

        # Toda extensión sirve también para normalizar el VAT histórico.
        self._update_existing_partner(
            partner,
            {"vat": nif},
            incoming_vat=nif,
            account_code=False,
        )
        if rec["_type"] == "CB" and rec.get("ccc"):
            bank_model = self.env["res.partner.bank"].sudo()
            account_number = partner_utils.normalize_bank_account(rec["ccc"])
            banks = bank_model.search([("partner_id", "=", partner.id)])
            existing = banks.filtered(
                lambda bank: partner_utils.normalize_bank_account(
                    bank.acc_number) == account_number
            )[:1]
            if not existing:
                bank_model.create({
                    "partner_id": partner.id,
                    "acc_number": account_number,
                })
        elif rec["_type"] == "CF" and rec.get("nombre_fiscal"):
            self._update_existing_partner(
                partner,
                {"name": rec["nombre_fiscal"], "vat": nif},
                incoming_vat=nif,
                account_code=False,
                force_name=True,
            )

    # ---- Fase 2: documentos -------------------------------------------- #
    def _process_documents(self, records):
        moves = self.env["account.move"]
        current_entry = []
        i = 0
        n = len(records)
        while i < n:
            rec = records[i]
            rtype = rec["_type"]
            if rtype in ("1", "2"):
                block, i = self._collect_invoice_block(records, i)
                if self.associate_taxes:
                    move = self._create_invoice(block)
                else:
                    move = self._create_invoice_as_literal_entry(block)
                if move:
                    moves |= move
                continue
            if rtype == "0":
                current_entry.append(rec)
                if rec.get("linea") == "U":
                    move = self._create_entry(current_entry)
                    if move:
                        moves |= move
                    current_entry = []
                i += 1
                continue
            i += 1
        if current_entry:
            self._append_log(
                _("Asiento incompleto sin línea 'U' descartado (%d líneas).")
                % len(current_entry))
        if self.post_moves and moves:
            to_post = moves.filtered(
                lambda m: (
                    m.state == "draft"
                    and not m.suenlace_needs_review
                    and not m.suenlace_fiscal_needs_review
                    and not m.suenlace_partner_needs_review
                    and not m.suenlace_tax_needs_review
                )
            )
            if to_post:
                to_post.action_post()
            review_count = len(moves.filtered(
                lambda m: (
                    m.suenlace_needs_review
                    or m.suenlace_fiscal_needs_review
                    or m.suenlace_partner_needs_review
                    or m.suenlace_tax_needs_review
                )
            ))
            if review_count:
                self._append_log(
                    _("%(n)d documentos no se contabilizan porque requieren "
                      "revisión de totales, tercero, impuestos o posición fiscal.")
                    % {"n": review_count})
        self.move_ids = [(4, m.id) for m in moves]
        self.move_count = len(self.move_ids)
        self._append_log(
            _("Documentos contables creados: %d") % len(moves))

    def _collect_invoice_block(self, records, start):
        block = [records[start]]
        i = start + 1
        n = len(records)
        while i < n:
            if records[i]["_type"] in ("1", "2", "0"):
                break
            block.append(records[i])
            i += 1
        return block, i

    # ---- Facturas ------------------------------------------------------ #
    @staticmethod
    def _reverse_entry_side(side):
        return "credit" if side == "debit" else "debit"

    @staticmethod
    def _amount_to_debit_credit(amount, side):
        """Convierte un importe SUENLACE en Debe/Haber sin perder su signo."""
        amount = amount or 0.0
        if amount < 0.0:
            side = "credit" if side == "debit" else "debit"
        amount = abs(amount)
        if side == "debit":
            return amount, 0.0
        return 0.0, amount

    @staticmethod
    def _invoice_header_entry_side(header):
        """Lado contable normal de la cuenta de cliente/proveedor."""
        is_sale = header.get("tipo_factura") == "1"
        is_refund = header.get("_type") == "2"
        if is_sale:
            return "credit" if is_refund else "debit"
        return "debit" if is_refund else "credit"

    @staticmethod
    def _invoice_detail_entry_side(header, detail):
        """Aplica literalmente la regla C/A descrita por SUENLACE."""
        is_sale = header.get("tipo_factura") == "1"
        is_refund = header.get("_type") == "2"
        if is_sale:
            side = "debit" if is_refund else "credit"
        else:
            side = "credit" if is_refund else "debit"
        if str(detail.get("tipo_importe") or "").strip().upper() == "A":
            side = "credit" if side == "debit" else "debit"
        return side

    @staticmethod
    def _literal_invoice_tax_account(detail, application, tax_kind):
        """Obtiene la subcuenta fiscal informada por a3 sin sustituirla.

        Algunos generadores rellenan las posiciones 192/204 y otros las
        228/240 con independencia de que la factura sea de compra o venta.
        Se prioriza el campo esperado por el tipo de operación y se usa el
        alternativo cuando el primero viene vacío. Así, si el DAT contiene el
        código, la cuenta se localiza o se crea automáticamente.
        """
        if tax_kind == "retention":
            candidates = ("cuenta_retencion",)
        elif tax_kind == "iva":
            candidates = (
                ("cuenta_iva2_repercutido", "cuenta_iva_soportado")
                if application == "sale"
                else ("cuenta_iva_soportado", "cuenta_iva2_repercutido")
            )
        else:
            candidates = (
                ("cuenta_recargo2_repercutido", "cuenta_recargo_soportado")
                if application == "sale"
                else ("cuenta_recargo_soportado", "cuenta_recargo2_repercutido")
            )
        for field_name in candidates:
            account_code = (detail.get(field_name) or "").strip()
            if account_code:
                return account_code
        return ""

    def _create_invoice_as_literal_entry(self, block):
        """Importa 1/2+9 como asiento, sin account.tax ni sustituciones.

        La cuenta de tercero de la cabecera, las cuentas de base y las cuentas
        fiscales indicadas en cada registro 9 se trasladan literalmente. Los
        lados Debe/Haber se obtienen de las reglas C/A del formato SUENLACE.
        """
        header = block[0]
        details = [record for record in block if record["_type"] == "9"]
        amp = next((record for record in block if record["_type"] == "4"), {})
        obs = next((record for record in block if record["_type"] == "3"), {})
        application = (
            "sale" if header.get("tipo_factura") == "1" else "purchase"
        )
        journal = self.journal_misc_id or self.env["account.journal"].search([
            ("type", "=", "general"),
            ("company_id", "=", self.company_id.id),
        ], limit=1)
        if not journal:
            raise missing_journal("general")

        profile = self._invoice_fiscal_profile(details)
        partner = self.env["res.partner"]
        if self.associate_partners:
            partner = self._find_or_create_partner(header)

        line_data_list = []
        review_notes = []
        debit_total = 0.0
        credit_total = 0.0

        def add_line(account_code, account_name, line_name, amount, side,
                     line_partner=None, fiscal=False):
            nonlocal debit_total, credit_total
            amount = amount or 0.0
            if not amount:
                return
            account_code = (account_code or "").strip()
            if not account_code:
                review_notes.append(
                    _("Falta la cuenta original a3 para %(line)s "
                      "(%(amount).2f). No se ha sustituido por ninguna "
                      "cuenta Odoo.") % {
                        "line": line_name,
                        "amount": amount,
                    }
                )
                return
            account = self._upsert_account(account_code, account_name)
            if not account:
                review_notes.append(
                    _("No se pudo crear o localizar la cuenta original "
                      "a3 %(account)s para %(line)s.") % {
                        "account": account_code,
                        "line": line_name,
                    }
                )
                return
            debit, credit = self._amount_to_debit_credit(amount, side)
            values = {
                "name": line_name or account_name or "/",
                "account_id": account.id,
                "debit": debit,
                "credit": credit,
                "suenlace_source_account_code": account_code,
            }
            if line_partner:
                values["partner_id"] = line_partner.id
            line_data_list.append(values)
            debit_total += debit
            credit_total += credit
            if fiscal:
                self._append_log(
                    _("Factura como asiento literal: cuenta fiscal a3 "
                      "%(account)s conservada sin account.tax.") % {
                        "account": account_code,
                    }
                )

        header_side = self._invoice_header_entry_side(header)
        add_line(
            header.get("cuenta"),
            header.get("cuenta_desc"),
            header.get("apunte_desc") or header.get("cuenta_desc") or _("Tercero"),
            header.get("importe"),
            header_side,
            line_partner=partner if partner else None,
        )

        for detail in details:
            base_side = self._invoice_detail_entry_side(header, detail)
            detail_name = (
                detail.get("apunte_desc")
                or detail.get("cuenta_desc")
                or _("Base SUENLACE")
            )
            add_line(
                detail.get("cuenta"),
                detail.get("cuenta_desc"),
                detail_name,
                detail.get("base"),
                base_side,
            )

            iva_amount = detail.get("cuota_iva") or 0.0
            if iva_amount:
                iva_code = self._literal_invoice_tax_account(
                    detail, application, "iva"
                )
                add_line(
                    iva_code,
                    _("IVA %(rate).2f%%") % {
                        "rate": detail.get("pct_iva") or 0.0,
                    },
                    _("IVA %(rate).2f%% - %(document)s") % {
                        "rate": detail.get("pct_iva") or 0.0,
                        "document": header.get("num_factura") or "",
                    },
                    iva_amount,
                    base_side,
                    fiscal=True,
                )

            recargo_amount = detail.get("cuota_recargo") or 0.0
            if recargo_amount:
                recargo_code = self._literal_invoice_tax_account(
                    detail, application, "recargo"
                )
                add_line(
                    recargo_code,
                    _("Recargo de equivalencia %(rate).2f%%") % {
                        "rate": detail.get("pct_recargo") or 0.0,
                    },
                    _("Recargo %(rate).2f%% - %(document)s") % {
                        "rate": detail.get("pct_recargo") or 0.0,
                        "document": header.get("num_factura") or "",
                    },
                    recargo_amount,
                    base_side,
                    fiscal=True,
                )

            retention_amount = detail.get("cuota_retencion") or 0.0
            if retention_amount:
                retention_code = self._literal_invoice_tax_account(
                    detail, application, "retention"
                )
                add_line(
                    retention_code,
                    _("Retención %(rate).2f%%") % {
                        "rate": detail.get("pct_retencion") or 0.0,
                    },
                    _("Retención %(rate).2f%% - %(document)s") % {
                        "rate": detail.get("pct_retencion") or 0.0,
                        "document": header.get("num_factura") or "",
                    },
                    retention_amount,
                    self._reverse_entry_side(base_side),
                    fiscal=True,
                )

        source_tax_accounts = self._source_tax_accounts_summary(details)
        reference = header.get("num_factura_sii") or header.get("num_factura")
        if amp.get("num_factura_rectificar"):
            reference = _("Rectifica: %s") % amp["num_factura_rectificar"]
        move = self.env["account.move"].with_context(
            check_move_validity=False
        ).create({
            "move_type": "entry",
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "suenlace_import_id": self.id,
            "suenlace_document_mode": "invoice_literal_entry",
            "suenlace_associate_partners": self.associate_partners,
            "suenlace_associate_taxes": False,
            "suenlace_source_tax_accounts": source_tax_accounts or False,
            "suenlace_invoice_subtype": profile["subtype_label"],
            "suenlace_has_recargo": profile["has_recargo"],
            "suenlace_has_retention": profile["has_retention"],
            "suenlace_retention_percent": profile["retention_percent"],
            "suenlace_retention_nature": profile["retention_nature"],
            "date": header.get("fecha"),
            "ref": reference or False,
            "line_ids": [(0, 0, values) for values in line_data_list],
        })
        if obs.get("observaciones"):
            move.narration = obs["observaciones"]
        if review_notes:
            self._schedule_literal_invoice_account_review(move, review_notes)
        if self.associate_partners and not partner:
            self._schedule_literal_invoice_partner_review(move, header)

        expected = abs(header.get("importe") or 0.0)
        source_detail_total = abs(sum(
            (
                (detail.get("base") or 0.0)
                + (detail.get("cuota_iva") or 0.0)
                + (detail.get("cuota_recargo") or 0.0)
                - (detail.get("cuota_retencion") or 0.0)
            ) * (
                -1.0
                if str(detail.get("tipo_importe") or "").strip().upper() == "A"
                else 1.0
            )
            for detail in details
        ))
        rounding = self.company_id.currency_id.rounding
        source_mismatch = float_compare(
            expected, source_detail_total, precision_rounding=rounding
        ) != 0
        balance_mismatch = float_compare(
            debit_total, credit_total, precision_rounding=rounding
        ) != 0
        if source_mismatch or balance_mismatch:
            reasons = []
            if source_mismatch:
                reasons.append(
                    _("La suma literal de bases, IVA, recargos y retenciones "
                      "no coincide con la cabecera SUENLACE.")
                )
            if balance_mismatch:
                reasons.append(
                    _("El asiento literal no cuadra: Debe %(debit).2f y "
                      "Haber %(credit).2f.") % {
                        "debit": debit_total,
                        "credit": credit_total,
                    }
                )
            self._schedule_literal_invoice_total_review(
                move,
                expected=expected,
                source_detail_total=source_detail_total,
                debit_total=debit_total,
                credit_total=credit_total,
                reason=" ".join(reasons),
            )

        self._append_log(
            _("Factura %(number)s importada como asiento literal; no se "
              "aplicaron impuestos ni se sustituyeron cuentas a3.") % {
                "number": header.get("num_factura") or move.display_name,
            }
        )
        return move

    def _schedule_literal_invoice_account_review(self, move, notes):
        move.suenlace_tax_needs_review = True
        move.activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline=fields.Date.context_today(self),
            summary=_("Revisar cuentas de factura SUENLACE"),
            note="<br/>".join(notes),
            user_id=self.env.user.id,
        )
        self._append_log(
            _("El asiento literal %(move)s requiere revisar cuentas: "
              "%(notes)s") % {
                "move": move.display_name,
                "notes": " ".join(notes),
            }
        )

    def _schedule_literal_invoice_partner_review(self, move, header):
        move.suenlace_partner_needs_review = True
        move.activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline=fields.Date.context_today(self),
            summary=_("Asignar tercero al asiento SUENLACE"),
            note=_(
                "No se pudo identificar el tercero solicitado para la "
                "factura %(number)s. Cuenta: %(account)s; NIF: %(vat)s; "
                "nombre: %(name)s."
            ) % {
                "number": header.get("num_factura") or "",
                "account": header.get("cuenta") or "",
                "vat": header.get("nif") or "",
                "name": header.get("nombre") or header.get("cuenta_desc") or "",
            },
            user_id=self.env.user.id,
        )

    def _schedule_literal_invoice_total_review(
            self, move, expected, source_detail_total,
            debit_total, credit_total, reason):
        currency = move.company_currency_id
        move.write({
            "suenlace_needs_review": True,
            "suenlace_expected_total": expected,
            "suenlace_source_detail_total": source_detail_total,
            "suenlace_calculated_total": source_detail_total,
            "suenlace_total_difference": source_detail_total - expected,
        })
        move.activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline=fields.Date.context_today(self),
            summary=_("Revisar totales de importación SUENLACE"),
            note="<br/>".join([
                reason,
                _("Total cabecera SUENLACE: %(amount)s %(currency)s") % {
                    "amount": currency.round(expected),
                    "currency": currency.name,
                },
                _("Suma de detalles SUENLACE: %(amount)s %(currency)s") % {
                    "amount": currency.round(source_detail_total),
                    "currency": currency.name,
                },
                _("Debe del asiento creado: %(amount)s %(currency)s") % {
                    "amount": currency.round(debit_total),
                    "currency": currency.name,
                },
                _("Haber del asiento creado: %(amount)s %(currency)s") % {
                    "amount": currency.round(credit_total),
                    "currency": currency.name,
                },
            ]),
            user_id=self.env.user.id,
        )
        self._append_log(
            _("El asiento literal %(move)s requiere revisión de totales.") % {
                "move": move.display_name,
            }
        )

    def _create_invoice(self, block):
        header = block[0]
        details = [r for r in block if r["_type"] == "9"]
        amp = next((r for r in block if r["_type"] == "4"), {})
        obs = next((r for r in block if r["_type"] == "3"), {})

        is_sale = header.get("tipo_factura") == "1"
        is_refund = header["_type"] == "2"
        if is_sale:
            move_type = "out_refund" if is_refund else "out_invoice"
            application = "sale"
            journal = self.journal_sale_id
        else:
            move_type = "in_refund" if is_refund else "in_invoice"
            application = "purchase"
            journal = self.journal_purchase_id

        partner = self._find_partner_for_invoice(header)
        if not partner:
            self._append_log(
                _("Factura %s sin tercero identificable; omitida.")
                % header.get("num_factura")
            )
            return self.env["account.move"]

        fiscal_position, fiscal_profile, fiscal_issue = \
            self._determine_invoice_fiscal_position(
                partner, application, details
            )
        line_vals = [
            (
                0,
                0,
                self._invoice_line_vals(
                    det,
                    application,
                    fiscal_position=fiscal_position,
                    fiscal_profile=fiscal_profile,
                ),
            )
            for det in details
        ]
        source_tax_accounts = self._source_tax_accounts_summary(details)
        move_vals = {
            "move_type": move_type,
            "company_id": self.company_id.id,
            "suenlace_import_id": self.id,
            "suenlace_document_mode": "odoo_invoice",
            "invoice_date": header.get("fecha_factura") or header.get("fecha"),
            "date": header.get("fecha"),
            "ref": header.get("num_factura_sii") or header.get("num_factura"),
            "invoice_line_ids": line_vals,
            # En modo factura Odoo el tercero y los impuestos son obligatorios.
            "suenlace_associate_partners": True,
            "suenlace_associate_taxes": True,
            "suenlace_source_tax_accounts": source_tax_accounts or False,
            "suenlace_invoice_subtype": fiscal_profile["subtype_label"],
            "suenlace_has_recargo": fiscal_profile["has_recargo"],
            "suenlace_has_retention": fiscal_profile["has_retention"],
            "suenlace_retention_percent": fiscal_profile[
                "retention_percent"
            ],
            "suenlace_retention_nature": fiscal_profile[
                "retention_nature"
            ],
        }
        if partner:
            move_vals["partner_id"] = partner.id
        if fiscal_position:
            move_vals["fiscal_position_id"] = fiscal_position.id
        if journal:
            move_vals["journal_id"] = journal.id
        if not is_sale and header.get("num_factura"):
            move_vals["ref"] = header["num_factura"]
        if amp.get("num_factura_rectificar"):
            move_vals["ref"] = _("Rectifica: %s") \
                % amp["num_factura_rectificar"]

        move = self.env["account.move"].with_context(
            check_move_validity=False
        ).create(move_vals)
        if obs.get("observaciones"):
            move.narration = obs["observaciones"]
        self._record_odoo_tax_accounts(move)
        if fiscal_issue:
            self._schedule_fiscal_position_review(
                move, fiscal_profile, fiscal_issue
            )
        self._check_invoice_totals(move, header, details)
        return move

    @staticmethod
    def _detail_has_recargo(det):
        """Detecta también el caso especial de recargo al 0% (marca S)."""
        return bool(
            abs(det.get("pct_recargo") or 0.0) > 0.0
            or abs(det.get("cuota_recargo") or 0.0) > 0.0
            or str(det.get("iva_0_recargo") or "").strip().upper() == "S"
            or det.get("cuenta_recargo_soportado")
            or det.get("cuenta_recargo2_repercutido")
        )

    @staticmethod
    def _detail_has_retention(det):
        return bool(
            abs(det.get("pct_retencion") or 0.0) > 0.0
            or abs(det.get("cuota_retencion") or 0.0) > 0.0
            or det.get("cuenta_retencion")
        )

    @staticmethod
    def _source_tax_accounts_summary(details):
        field_labels = (
            ("cuenta_iva_soportado", "IVA soportado"),
            ("cuenta_recargo_soportado", "Recargo soportado"),
            ("cuenta_retencion", "Retención"),
            ("cuenta_iva2_repercutido", "IVA repercutido"),
            ("cuenta_recargo2_repercutido", "Recargo repercutido"),
        )
        rows = []
        for field_name, label in field_labels:
            codes = sorted({
                str(det.get(field_name) or "").strip()
                for det in details
                if str(det.get(field_name) or "").strip()
            })
            if codes:
                rows.append("%s: %s" % (label, ", ".join(codes)))
        return "\n".join(rows)

    def _record_odoo_tax_accounts(self, move):
        tax_lines = move.line_ids.filtered(
            lambda line: line.tax_repartition_line_id and line.account_id
        )
        accounts = sorted({
            "%s - %s" % (line.account_id.code, line.account_id.name)
            for line in tax_lines
        })
        move.suenlace_odoo_tax_accounts = "\n".join(accounts) or False
        if move.suenlace_source_tax_accounts:
            self._append_log(
                _("Documento %(move)s: las subcuentas fiscales a3 se "
                  "conservan como trazabilidad; la contabilización usa las "
                  "cuentas de reparto de los impuestos Odoo: %(accounts)s")
                % {
                    "move": move.display_name,
                    "accounts": ", ".join(accounts) if accounts else _("sin líneas fiscales"),
                }
            )

    @classmethod
    def _invoice_fiscal_profile(cls, details):
        """Resume el perfil fiscal real informado en los registros tipo 9."""
        subtypes = sorted({
            str(det.get("subtipo_factura") or "").strip().zfill(2)
            for det in details
            if str(det.get("subtipo_factura") or "").strip()
        })
        has_recargo = any(cls._detail_has_recargo(det) for det in details)
        has_retention = any(cls._detail_has_retention(det) for det in details)
        retention_rates = sorted({
            abs(det.get("pct_retencion") or 0.0)
            for det in details
            if cls._detail_has_retention(det)
            and abs(det.get("pct_retencion") or 0.0) > 0.0
        })
        lease_codes = {"03", "04", "28", "29", "32", "33"}
        retention_natures = sorted({
            "lease"
            if str(det.get("impreso") or "").strip() in lease_codes
            else "generic"
            for det in details
            if cls._detail_has_retention(det)
        })
        return {
            "subtypes": subtypes,
            "subtype": subtypes[0] if len(subtypes) == 1 else False,
            "subtype_label": ",".join(subtypes),
            "mixed_subtypes": len(subtypes) > 1,
            "has_recargo": has_recargo,
            "has_retention": has_retention,
            "retention_rates": retention_rates,
            "retention_percent": (
                retention_rates[0] if len(retention_rates) == 1 else 0.0
            ),
            "mixed_retention_rates": len(retention_rates) > 1,
            "retention_natures": retention_natures,
            "retention_nature": (
                retention_natures[0]
                if len(retention_natures) == 1
                else ("none" if not has_retention else "generic")
            ),
            "mixed_retention_natures": len(retention_natures) > 1,
        }

    def _determine_invoice_fiscal_position(
            self, partner, application, details):
        """Determina la posición fiscal con todos los indicadores SUENLACE.

        El recargo y la retención no son simples impuestos accesorios para esta
        decisión: forman parte de la clave de búsqueda de la posición fiscal.
        """
        profile = self._invoice_fiscal_profile(details)
        mapping_model = self.env["tl.suenlace.fiscal.position.mapping"]
        fiscal_position = mapping_model.find_fiscal_position(
            self.company_id,
            application,
            profile["subtype"],
            profile["has_recargo"],
            profile["has_retention"],
            retention_percent=profile["retention_percent"],
            retention_nature=profile["retention_nature"],
        )
        issues = []
        if profile["mixed_subtypes"]:
            issues.append(
                _("La factura combina varios subtipos SUENLACE: %s.")
                % profile["subtype_label"]
            )
        if profile["mixed_retention_rates"]:
            issues.append(
                _("La factura combina varios porcentajes de retención: %s.")
                % ", ".join(
                    "%.2f%%" % rate
                    for rate in profile["retention_rates"]
                )
            )
        if profile["mixed_retention_natures"]:
            issues.append(
                _("La factura combina retenciones generales y de "
                  "arrendamientos.")
            )

        special_profile = (
            profile["has_recargo"]
            or profile["has_retention"]
            or (
                profile["subtype"]
                and profile["subtype"] != "01"
            )
        )
        if not fiscal_position and not special_profile:
            fiscal_position = self._standard_partner_fiscal_position(partner)
        elif not fiscal_position and special_profile:
            labels = []
            if profile["has_recargo"]:
                labels.append(_("recargo de equivalencia"))
            if profile["has_retention"]:
                labels.append(
                    _("retención %(rate).2f%% (%(nature)s)") % {
                        "rate": profile["retention_percent"],
                        "nature": profile["retention_nature"],
                    }
                )
            if not labels and profile["subtype"]:
                labels.append(
                    _("subtipo especial %s") % profile["subtype"]
                )
            issues.append(
                _("No existe un mapeo de posición fiscal para %(profile)s "
                  "en el subtipo %(subtype)s (%(application)s).") % {
                    "profile": _(" y ").join(labels),
                    "subtype": profile["subtype_label"] or _("sin subtipo"),
                    "application": application,
                }
            )
            # Conserva la posición fiscal normal del partner únicamente como
            # referencia, pero exige revisión porque no acredita el régimen
            # especial informado por el DAT.
            fiscal_position = self._standard_partner_fiscal_position(partner)

        return fiscal_position, profile, " ".join(issues)

    def _standard_partner_fiscal_position(self, partner):
        if not partner:
            return self.env["account.fiscal.position"]
        fiscal_position_model = self.env["account.fiscal.position"].with_company(
            self.company_id
        )
        getter = getattr(fiscal_position_model, "_get_fiscal_position", None)
        if getter:
            try:
                return getter(partner)
            except TypeError:
                # Compatibilidad defensiva con firmas que aceptan también la
                # dirección de entrega.
                try:
                    return getter(partner, partner)
                except TypeError:
                    pass
        return partner.with_company(
            self.company_id
        ).property_account_position_id

    def _schedule_fiscal_position_review(self, move, profile, reason):
        move.suenlace_fiscal_needs_review = True
        fiscal_position_name = (
            move.fiscal_position_id.display_name
            if move.fiscal_position_id else _("Sin posición fiscal")
        )
        details = [
            reason,
            _("Posición fiscal aplicada provisionalmente: %s")
            % fiscal_position_name,
            _("Subtipo(s) SUENLACE: %s")
            % (profile["subtype_label"] or _("sin subtipo")),
            _("Recargo de equivalencia: %s")
            % (_("Sí") if profile["has_recargo"] else _("No")),
            _("Retención: %s")
            % (_("Sí") if profile["has_retention"] else _("No")),
            _("Porcentaje de retención: %.2f%%")
            % profile["retention_percent"],
            _("Naturaleza de retención: %s")
            % profile["retention_nature"],
            _("Configure el mapeo exacto en Contabilidad > SUENLACE > "
              "Mapeo de posiciones fiscales."),
        ]
        move.activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline=fields.Date.context_today(self),
            summary=_("Revisar posición fiscal SUENLACE"),
            note="<br/>".join(details),
            user_id=self.env.user.id,
        )
        self._append_log(
            _("El documento %(move)s requiere revisión de posición fiscal: "
              "%(reason)s") % {
                "move": move.display_name,
                "reason": reason,
            }
        )

    def _find_partner_for_invoice(self, header):
        # Las facturas necesitan siempre un tercero. La opción de asociación
        # del lote se limita a los asientos varios tipo 0.
        return self._find_or_create_partner(header)

    def _check_invoice_totals(self, move, header, details):
        expected = abs(header.get("importe") or 0.0)
        calculated = abs(move.amount_total)
        source_detail_total = abs(sum(
            (
                (det.get("base") or 0.0)
                + (det.get("cuota_iva") or 0.0)
                + (det.get("cuota_recargo") or 0.0)
                - (det.get("cuota_retencion") or 0.0)
            ) * (-1.0 if det.get("tipo_importe") == "A" else 1.0)
            for det in details
        ))
        rounding = move.currency_id.rounding
        odoo_mismatch = float_compare(
            expected, calculated, precision_rounding=rounding) != 0
        source_mismatch = float_compare(
            expected, source_detail_total, precision_rounding=rounding) != 0
        if odoo_mismatch or source_mismatch:
            reasons = []
            if source_mismatch:
                reasons.append(
                    _("La suma de bases, cuotas, recargos y retenciones del "
                      "fichero no coincide con la cabecera SUENLACE."))
            if odoo_mismatch:
                reasons.append(
                    _("El total de la cabecera SUENLACE no coincide con el "
                      "total calculado por Odoo."))
            self._schedule_total_review(
                move,
                expected=expected,
                calculated=calculated,
                source_detail_total=source_detail_total,
                reason=" ".join(reasons),
            )

    def _invoice_line_vals(
        self,
        det,
        application,
        fiscal_position=None,
        fiscal_profile=None,
    ):
        account = self._upsert_account(
            det.get("cuenta"), det.get("cuenta_desc")
        )
        taxes = self.env["account.tax"]
        mapping = self.env["tl.suenlace.tax.mapping"]
        if det.get("pct_iva"):
            tax = mapping.find_tax(
                self.company_id,
                application,
                "iva",
                det["pct_iva"],
            )
            if (
                tax
                and fiscal_position
                and not (fiscal_profile or {}).get("has_recargo")
                and not (fiscal_profile or {}).get("has_retention")
            ):
                try:
                    tax = fiscal_position.map_tax(tax)
                except (AttributeError, TypeError):
                    pass
            if tax:
                taxes |= tax
            else:
                self._append_log(
                    _("Sin impuesto IVA %(p).2f%% para %(a)s; línea sin IVA.")
                    % {"p": det["pct_iva"], "a": application})
        if self._detail_has_recargo(det):
            recargo_percent = det.get("pct_recargo") or 0.0
            tax = mapping.find_tax(
                self.company_id,
                application,
                "recargo",
                recargo_percent,
            )
            if tax:
                taxes |= tax
            else:
                self._append_log(
                    _("Sin impuesto de recargo %(p).2f%% para %(a)s; "
                      "la factura requerirá revisión fiscal.") % {
                        "p": recargo_percent,
                        "a": application,
                    }
                )
        if self._detail_has_retention(det):
            retention_percent = det.get("pct_retencion") or 0.0
            retention_nature = mapping.retention_nature_from_detail(det)
            tax = mapping.find_tax(
                self.company_id,
                application,
                "retencion",
                retention_percent,
                retention_nature=retention_nature,
            )
            if tax:
                taxes |= tax
            else:
                self._append_log(
                    _("Sin impuesto de retención %(p).2f%% para %(a)s; "
                      "la factura requerirá revisión fiscal.") % {
                        "p": retention_percent,
                        "a": application,
                    }
                )
        vals = {
            "name": det.get("apunte_desc") or det.get("cuenta_desc") or "/",
            "quantity": 1.0,
            "price_unit": abs(det.get("base", 0.0)),
            "tax_ids": [(6, 0, taxes.ids)],
        }
        if account:
            vals["account_id"] = account.id
        return vals

    # ---- Asientos varios (tipo 0) -------------------------------------- #
    def _create_entry(self, entry_records):
        if not entry_records:
            return self.env["account.move"]
        head = entry_records[0]
        journal = self.journal_misc_id or self.env["account.journal"].search([
            ("type", "=", "general"),
            ("company_id", "=", self.company_id.id),
        ], limit=1)
        if not journal:
            raise missing_journal("general")

        line_data_list = []
        mapped_tax_lines = []
        tax_review_notes = []
        debit_total = 0.0
        credit_total = 0.0
        tax_mapping_model = self.env["tl.suenlace.tax.mapping"]

        for rec in entry_records:
            source_code = (rec.get("cuenta") or "").strip()
            account = self._upsert_account(
                source_code, rec.get("cuenta_desc")
            )
            amount = abs(rec.get("importe") or 0.0)
            debit = amount if rec.get("tipo_importe") == "D" else 0.0
            credit = amount if rec.get("tipo_importe") == "H" else 0.0
            balance = debit - credit
            debit_total += debit
            credit_total += credit
            line_data = {
                "name": rec.get("apunte_desc") or "/",
                "account_id": account.id if account else False,
                "debit": debit,
                "credit": credit,
                "suenlace_source_account_code": source_code or False,
            }

            # La opción de terceros solo afecta a los asientos tipo 0 y nunca
            # altera la cuenta contable original.
            if self.associate_partners and source_code[:2] in (
                "40", "41", "43", "44"
            ):
                partner = self._find_partner_by_ref(source_code)
                if partner:
                    line_data["partner_id"] = partner.id

            # Con la interpretación desactivada no se consulta ningún mapeo:
            # la cuenta del DAT se conserva literalmente.
            if self.associate_taxes:
                mapping = tax_mapping_model.find_for_entry_account(
                    self.company_id, source_code
                )
                if mapping:
                    repartition_data = mapping._entry_repartition_data(balance)
                    tax_line = repartition_data.get("tax_line")
                    if tax_line:
                        if tax_line.account_id:
                            line_data["account_id"] = tax_line.account_id.id
                        line_data["tax_repartition_line_id"] = tax_line.id
                        if tax_line.tag_ids:
                            line_data["tax_tag_ids"] = [
                                (6, 0, tax_line.tag_ids.ids)
                            ]
                        line_data["tax_base_amount"] = repartition_data.get(
                            "base_amount", 0.0
                        )
                        mapped_tax_lines.append({
                            "line": line_data,
                            "mapping": mapping,
                            "data": repartition_data,
                            "source_code": source_code,
                        })
                        self._append_log(
                            _("Asiento: subcuenta fiscal a3 %(source)s "
                              "interpretada como %(tax)s y contabilizada en "
                              "%(account)s.") % {
                                "source": source_code,
                                "tax": mapping.tax_id.display_name,
                                "account": (
                                    tax_line.account_id.display_name
                                    if tax_line.account_id
                                    else account.display_name
                                ),
                            }
                        )
                    else:
                        tax_review_notes.append(
                            _("La subcuenta %(account)s está mapeada al "
                              "impuesto %(tax)s, pero el impuesto no tiene una "
                              "línea de reparto fiscal utilizable.") % {
                                "account": source_code,
                                "tax": mapping.tax_id.display_name,
                            }
                        )
                elif self._looks_like_entry_tax_account(source_code):
                    tax_review_notes.append(
                        _("La posible subcuenta fiscal %(account)s no tiene un "
                          "mapeo explícito para asientos. Se conserva la "
                          "cuenta original.") % {"account": source_code}
                    )

            line_data_list.append(line_data)

        # Añade las etiquetas de base únicamente cuando existe una línea base
        # inequívoca por importe y signo. No se inventan asociaciones.
        rounding = self.company_id.currency_id.rounding
        for item in mapped_tax_lines:
            base_amount = item["data"].get("base_amount") or 0.0
            base_line = item["data"].get("base_line")
            if not base_line or not base_line.tag_ids or not base_amount:
                continue
            candidates = []
            for candidate in line_data_list:
                if candidate is item["line"]:
                    continue
                if candidate.get("tax_repartition_line_id"):
                    continue
                candidate_balance = (
                    candidate.get("debit", 0.0)
                    - candidate.get("credit", 0.0)
                )
                if float_compare(
                    candidate_balance,
                    base_amount,
                    precision_rounding=rounding,
                ) == 0:
                    candidates.append(candidate)
            if len(candidates) == 1:
                candidate = candidates[0]
                existing_ids = set()
                commands = candidate.get("tax_tag_ids") or []
                for command in commands:
                    if command and command[0] == 6:
                        existing_ids.update(command[2])
                existing_ids.update(base_line.tag_ids.ids)
                candidate["tax_tag_ids"] = [(6, 0, sorted(existing_ids))]
            else:
                tax_review_notes.append(
                    _("No se pudo identificar de forma inequívoca la base "
                      "%(base).2f de la subcuenta fiscal %(account)s. La cuota "
                      "se ha interpretado, pero deben revisarse las etiquetas "
                      "de base del informe fiscal.") % {
                        "base": base_amount,
                        "account": item["source_code"],
                    }
                )

        line_vals = [(0, 0, values) for values in line_data_list]
        move = self.env["account.move"].with_context(
            check_move_validity=False
        ).create({
            "move_type": "entry",
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "suenlace_import_id": self.id,
            "suenlace_document_mode": "entry_type_0",
            "suenlace_associate_partners": self.associate_partners,
            "suenlace_associate_taxes": self.associate_taxes,
            "date": head.get("fecha"),
            "ref": head.get("referencia") or False,
            "line_ids": line_vals,
        })
        if tax_review_notes:
            self._schedule_entry_tax_review(move, tax_review_notes)
        if float_compare(
                debit_total, credit_total,
                precision_rounding=move.company_currency_id.rounding) != 0:
            self._schedule_total_review(
                move,
                expected=debit_total,
                calculated=credit_total,
                reason=_("El total del Debe no coincide con el total del Haber."),
                debit_total=debit_total,
                credit_total=credit_total,
            )
        return move

    @staticmethod
    def _looks_like_entry_tax_account(account_code):
        code = (account_code or "").replace(" ", "")
        return code.startswith(("472", "477", "473", "4751"))

    def _schedule_entry_tax_review(self, move, notes):
        move.suenlace_tax_needs_review = True
        move.activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline=fields.Date.context_today(self),
            summary=_("Revisar impuestos del asiento SUENLACE"),
            note="<br/>".join(notes),
            user_id=self.env.user.id,
        )
        self._append_log(
            _("El asiento %(move)s requiere revisión fiscal: %(notes)s") % {
                "move": move.display_name,
                "notes": " ".join(notes),
            }
        )

    def _schedule_total_review(
            self, move, expected, calculated, reason,
            source_detail_total=None, debit_total=None, credit_total=None):
        difference = calculated - expected
        source_difference = (
            source_detail_total - expected
            if source_detail_total is not None else None
        )
        move.write({
            "suenlace_needs_review": True,
            "suenlace_expected_total": expected,
            "suenlace_calculated_total": calculated,
            "suenlace_total_difference": difference,
            "suenlace_source_detail_total": source_detail_total or 0.0,
        })
        currency = move.currency_id or move.company_currency_id
        details = [
            reason,
            _("Importación: %(import)s") % {"import": self.display_name},
        ]
        if debit_total is not None and credit_total is not None:
            details.extend([
                _("Debe: %(amount)s %(currency)s") % {
                    "amount": currency.round(debit_total),
                    "currency": currency.name,
                },
                _("Haber: %(amount)s %(currency)s") % {
                    "amount": currency.round(credit_total),
                    "currency": currency.name,
                },
            ])
        else:
            details.extend([
                _("Total SUENLACE: %(amount)s %(currency)s") % {
                    "amount": currency.round(expected),
                    "currency": currency.name,
                },
                _("Total Odoo: %(amount)s %(currency)s") % {
                    "amount": currency.round(calculated),
                    "currency": currency.name,
                },
            ])
            if source_detail_total is not None:
                details.extend([
                    _("Suma informada en detalles SUENLACE: "
                      "%(amount)s %(currency)s") % {
                        "amount": currency.round(source_detail_total),
                        "currency": currency.name,
                    },
                    _("Diferencia detalle/cabecera: "
                      "%(amount)s %(currency)s") % {
                        "amount": currency.round(source_difference),
                        "currency": currency.name,
                    },
                ])
        details.append(
            _("Diferencia Odoo/cabecera: %(amount)s %(currency)s") % {
                "amount": currency.round(difference),
                "currency": currency.name,
            })
        move.activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline=fields.Date.context_today(self),
            summary=_("Revisar totales de importación SUENLACE"),
            note="<br/>".join(details),
            user_id=self.env.user.id,
        )
        log_difference = (
            source_difference
            if source_difference is not None
            and float_compare(
                source_difference, 0.0,
                precision_rounding=currency.rounding) != 0
            else difference
        )
        self._append_log(
            _("El documento %(move)s requiere revisión de totales "
              "(diferencia %(difference)s %(currency)s).") % {
                "move": move.display_name,
                "difference": currency.round(log_difference),
                "currency": currency.name,
            })

    # ------------------------------------------------------------------ #
    #  Smart buttons                                                     #
    # ------------------------------------------------------------------ #
    def action_view_moves(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Asientos importados"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", self.move_ids.ids)],
        }

