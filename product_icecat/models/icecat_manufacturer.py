# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models
from odoo.exceptions import UserError

from .icecat_api import IcecatError, get_client_from_env


class IcecatManufacturer(models.Model):
    _name = "icecat.manufacturer"
    _description = "Icecat Manufacturer"
    _order = "name"

    name = fields.Char(
        required=True,
        help="Exact manufacturer/vendor name as known by Icecat. This is "
        "sent as the 'vendor' parameter when querying the Icecat API, so "
        "it must match Icecat's own spelling (e.g. as seen in their "
        "supplier mapping export).",
    )
    icecat_supplier_id = fields.Char(
        string="Icecat Supplier ID",
        help="Icecat's internal numeric Supplier ID, used to find this "
        "manufacturer's products in Icecat's catalog index during bulk "
        "imports. Filled in automatically from Icecat's suppliers list "
        "(by 'Sync Manufacturers from Icecat', or on demand the first "
        "time it is needed) — only fill it by hand if the automatic "
        "lookup cannot match this manufacturer's name.",
    )
    active = fields.Boolean(default=True)

    product_brand_ids = fields.One2many(
        comodel_name="product.brand",
        inverse_name="icecat_manufacturer_id",
        string="Linked Brands",
    )
    brand_count = fields.Integer(compute="_compute_brand_count")

    # -- import configuration ------------------------------------------------
    import_main_image = fields.Boolean(
        default=True,
        help="When importing a product from this manufacturer, set Icecat's "
        "main picture as the product image.",
    )
    import_gallery_images = fields.Boolean(
        string="Import Additional Images",
        default=True,
        help="When importing a product from this manufacturer, import "
        "Icecat's additional pictures as extra website media (product "
        "gallery images shown on the eCommerce product page).",
    )
    create_product_category = fields.Boolean(
        default=False,
        help="When importing a product from this manufacturer, get or "
        "create a Product Category matching its Icecat category, and set "
        "it on the product.",
    )
    create_ecommerce_category = fields.Boolean(
        string="Create eCommerce Category",
        default=False,
        help="When importing a product from this manufacturer, get or "
        "create a Website/eCommerce Category matching its Icecat category, "
        "and add it to the product.",
    )

    _sql_constraints = [
        ("name_uniq", "unique(name)", "This Icecat manufacturer name already exists."),
    ]

    @api.depends("product_brand_ids")
    def _compute_brand_count(self):
        for manufacturer in self:
            manufacturer.brand_count = len(manufacturer.product_brand_ids)

    # ------------------------------------------------------------------
    # sync from Icecat's SuppliersList.xml.gz
    # ------------------------------------------------------------------
    def action_sync_from_icecat(self):
        """Download Icecat's full suppliers list and create/update local
        manufacturer records from it.

        - Existing records are matched by Supplier ID first, then by name
          (case-insensitively). Matched-by-name records get their missing
          Supplier ID filled in; matched-by-ID records get their name
          refreshed to Icecat's canonical spelling (the one product
          lookups expect as the ``vendor`` parameter).
        - Every supplier not known locally yet is created.

        Callable both as a server action (``model.action_sync_from_icecat()``)
        and from a recordset.
        """
        try:
            client = get_client_from_env(self.env)
            rows = list(client.iter_suppliers())
        except IcecatError as exc:
            raise UserError(str(exc)) from exc

        manufacturer_sudo = self.sudo()
        existing = manufacturer_sudo.with_context(active_test=False).search([])
        by_supplier_id = {m.icecat_supplier_id: m for m in existing if m.icecat_supplier_id}
        by_name = {m.name.casefold(): m for m in existing}

        created = updated = 0
        create_vals = []
        seen_names = set(by_name)
        for row in rows:
            name_key = row["name"].casefold()
            record = by_supplier_id.get(row["icecat_id"]) or by_name.get(name_key)
            if record:
                vals = {}
                if not record.icecat_supplier_id:
                    vals["icecat_supplier_id"] = row["icecat_id"]
                elif (
                    record.icecat_supplier_id == row["icecat_id"]
                    and record.name != row["name"]
                    and row["name"].casefold() not in seen_names
                ):
                    # refresh to Icecat's canonical spelling, unless that
                    # exact name is already taken by another record
                    vals["name"] = row["name"]
                    seen_names.discard(record.name.casefold())
                    seen_names.add(name_key)
                if vals:
                    record.write(vals)
                    updated += 1
            elif name_key not in seen_names:
                seen_names.add(name_key)
                create_vals.append({"name": row["name"], "icecat_supplier_id": row["icecat_id"]})
                created += 1
        if create_vals:
            manufacturer_sudo.create(create_vals)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Icecat manufacturers synced"),
                "message": self.env._(
                    "%(total)d suppliers processed: %(created)d created, %(updated)d updated.",
                    total=len(rows),
                    created=created,
                    updated=updated,
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def _icecat_resolve_supplier_ids(self):
        """Fill in the missing Supplier ID of the manufacturers in ``self``
        by looking their name up (case-insensitively) in Icecat's suppliers
        list. Returns the subset that could not be matched.

        Raises :class:`IcecatError` on download/credential problems, like
        the rest of the client — callers inside actions should catch it and
        re-raise as UserError.
        """
        to_resolve = self.filtered(lambda m: not m.icecat_supplier_id)
        unmatched = self.browse()
        if not to_resolve:
            return unmatched
        client = get_client_from_env(self.env)
        wanted = {m.name.casefold(): m for m in to_resolve}
        for row in client.iter_suppliers():
            manufacturer = wanted.pop(row["name"].casefold(), None)
            if manufacturer is not None:
                manufacturer.icecat_supplier_id = row["icecat_id"]
                if not wanted:
                    break
        for manufacturer in wanted.values():
            unmatched |= manufacturer
        return unmatched

    def action_fetch_supplier_id(self):
        """Form-view button: resolve this manufacturer's Supplier ID from
        Icecat's suppliers list."""
        try:
            unmatched = self._icecat_resolve_supplier_ids()
        except IcecatError as exc:
            raise UserError(str(exc)) from exc
        if unmatched:
            raise UserError(
                self.env._(
                    "No Icecat supplier is named %(names)s. Check the "
                    "spelling against Icecat's suppliers list (or run "
                    "'Sync Manufacturers from Icecat' to import it), or "
                    "fill in the Supplier ID by hand.",
                    names=", ".join(unmatched.mapped("name")),
                )
            )
        return True

    def action_view_brands(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Brands"),
            "res_model": "product.brand",
            "view_mode": "list,form",
            "domain": [("icecat_manufacturer_id", "=", self.id)],
            "context": {"default_icecat_manufacturer_id": self.id},
        }
