# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models
from odoo.exceptions import UserError

from .icecat_api import IcecatError, get_client_from_env


class IcecatCategory(models.Model):
    _name = "icecat.category"
    _description = "Icecat Category"
    _parent_name = "parent_id"
    _parent_store = True
    _order = "complete_name"

    name = fields.Char(required=True)
    icecat_id = fields.Char(string="Icecat Category ID", required=True, index=True)
    parent_id = fields.Many2one(
        comodel_name="icecat.category",
        string="Parent Category",
        ondelete="cascade",
        index=True,
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        comodel_name="icecat.category", inverse_name="parent_id", string="Child Categories"
    )
    complete_name = fields.Char(compute="_compute_complete_name", recursive=True, store=True)

    product_categ_id = fields.Many2one(
        comodel_name="product.category",
        string="Mapped Product Category",
        help="Product Category created/linked from this Icecat category. "
        "Only populated for manufacturers with 'Create Product Category' "
        "enabled.",
    )
    ecommerce_categ_id = fields.Many2one(
        comodel_name="product.public.category",
        string="Mapped eCommerce Category",
        help="Website/eCommerce Category created/linked from this Icecat "
        "category. Only populated for manufacturers with 'Create eCommerce "
        "Category' enabled.",
    )
    product_tmpl_ids = fields.One2many(
        comodel_name="product.template", inverse_name="icecat_category_id", string="Products"
    )
    product_count = fields.Integer(compute="_compute_product_count")

    _sql_constraints = [
        ("icecat_id_uniq", "unique(icecat_id)", "This Icecat category ID already exists."),
    ]

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = f"{category.parent_id.complete_name} / {category.name}"
            else:
                category.complete_name = category.name

    @api.depends("product_tmpl_ids")
    def _compute_product_count(self):
        for category in self:
            category.product_count = len(category.product_tmpl_ids)

    # ------------------------------------------------------------------
    # lazy get-or-create, used while importing a single product
    # ------------------------------------------------------------------
    @api.model
    def get_or_create_category(self, icecat_id, name):
        """Get or create a category stub from product-level XML data.

        Product XML only carries the leaf category (id + name), not its
        ancestors, so a category created this way has no parent until a
        full sync (:meth:`action_sync_from_icecat`) fills in the hierarchy.
        """
        category = self.search([("icecat_id", "=", icecat_id)], limit=1)
        if category:
            if name and category.name != name:
                category.name = name
            return category
        return self.create({"icecat_id": icecat_id, "name": name or self.env._("Unknown")})

    def _get_or_create_product_category(self):
        self.ensure_one()
        if self.product_categ_id:
            return self.product_categ_id
        parent_categ = (
            self.parent_id._get_or_create_product_category() if self.parent_id else False
        )
        category = self.env["product.category"].create(
            {"name": self.name, "parent_id": parent_categ.id if parent_categ else False}
        )
        self.product_categ_id = category.id
        return category

    def _get_or_create_ecommerce_category(self):
        self.ensure_one()
        if self.ecommerce_categ_id:
            return self.ecommerce_categ_id
        parent_categ = (
            self.parent_id._get_or_create_ecommerce_category() if self.parent_id else False
        )
        category = self.env["product.public.category"].create(
            {"name": self.name, "parent_id": parent_categ.id if parent_categ else False}
        )
        self.ecommerce_categ_id = category.id
        return category

    # ------------------------------------------------------------------
    # full taxonomy sync
    # ------------------------------------------------------------------
    def action_sync_from_icecat(self):
        """Download Icecat's full category list and create/update local
        records, including parent/child relations."""
        try:
            client = get_client_from_env(self.env)
            rows = list(client.iter_categories())
        except IcecatError as exc:
            raise UserError(str(exc)) from exc

        icecat_category_sudo = self.sudo()
        existing = {
            c.icecat_id: c
            for c in icecat_category_sudo.with_context(active_test=False).search([])
        }

        create_vals = [
            {"icecat_id": row["icecat_id"], "name": row["name"]}
            for row in rows
            if row["icecat_id"] not in existing
        ]
        if create_vals:
            for record in icecat_category_sudo.create(create_vals):
                existing[record.icecat_id] = record

        for row in rows:
            record = existing.get(row["icecat_id"])
            if not record:
                continue
            vals = {}
            if row["name"] and record.name != row["name"]:
                vals["name"] = row["name"]
            parent_icecat_id = row.get("parent_icecat_id")
            if parent_icecat_id:
                parent = existing.get(parent_icecat_id)
                if parent and record.parent_id.id != parent.id:
                    vals["parent_id"] = parent.id
            if vals:
                record.write(vals)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Icecat categories synced"),
                "message": self.env._("%d categories processed.", len(rows)),
                "type": "success",
                "sticky": False,
            },
        }
