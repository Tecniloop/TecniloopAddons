from odoo import models


class ProjectProject(models.Model):
    _name = "project.project"
    _inherit = ["project.project", "tier.validation"]
    _tier_validation_manual_config = False
    _tier_validation_buttons_xpath = "/form/header/field[@name='stage_id']"
    _state_field = "stage_id"
    _state_from = ["open"]
    _state_to = ["closed"]
    _cancel_state = "cancelled"

    def _get_requested_notification_subtype(self):
        return "project_tier_validation.project_tier_validation_requested"

    def _get_accepted_notification_subtype(self):
        return "project_tier_validation.project_tier_validation_accepted"

    def _get_rejected_notification_subtype(self):
        return "project_tier_validation.project_tier_validation_rejected"

    def _tier_validation_get_current_state_value(self):
        self.ensure_one()
        return "closed" if self.stage_id.fold else "open"

    def _check_state_conditions(self, vals):
        self.ensure_one()
        if not self._check_state_from_condition() or "stage_id" not in vals:
            return False
        new_stage = self.env["project.project.stage"].browse(vals["stage_id"])
        return bool(new_stage and new_stage.fold)

    def _allow_to_remove_reviews(self, values):
        self.ensure_one()
        if "stage_id" not in values:
            return False
        current_state = self._tier_validation_get_current_state_value()
        new_stage = self.env["project.project.stage"].browse(values["stage_id"])
        new_state = "closed" if new_stage.fold else "open"
        return new_state in self._state_from and current_state not in self._state_from
