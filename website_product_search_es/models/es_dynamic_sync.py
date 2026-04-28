from odoo import api, models


class BaseDynamicEsSync(models.AbstractModel):
    _inherit = "base"

    def _es_sync_excluded_models(self):
        return {
            "es.index.log",
            "es.index.config",
            "es.index.config.line",
            "ir.config_parameter",
        }

    def _es_dynamic_configs(self):
        if self._name in self._es_sync_excluded_models():
            return self.env["es.index.config"]
        return self.env["es.index.config"].sudo().search(
            [
                ("active", "=", True),
                ("auto_sync", "=", True),
                ("model_name", "=", self._name),
            ]
        )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env.context.get("skip_es_dynamic_sync"):
            return records
        configs = records._es_dynamic_configs()
        if configs:
            configs._sync_records(records)
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("skip_es_dynamic_sync"):
            return res
        configs = self._es_dynamic_configs()
        if configs:
            changed_fields = set(vals.keys())
            configs_to_sync = self.env["es.index.config"]
            for cfg in configs:
                mapped_fields = set(cfg.line_ids.mapped("field_id.name"))
                if not mapped_fields or (changed_fields & mapped_fields):
                    configs_to_sync |= cfg
            if configs_to_sync:
                configs_to_sync._sync_records(self)
        return res

    def unlink(self):
        if self.env.context.get("skip_es_dynamic_sync"):
            return super().unlink()
        configs = self._es_dynamic_configs()
        record_ids = self.ids[:]
        res = super().unlink()
        if configs and record_ids:
            configs._delete_record_ids(record_ids)
        return res
