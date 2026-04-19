from odoo import api, models


class ProjectTask(models.Model):
    _name = "project.task"
    _inherit = ["project.task", "tier.validation"]
    _tier_validation_manual_config = False
    _tier_validation_buttons_xpath = "/form/header/field[@name='stage_id']"
    _tier_validation_state_field_is_computed = True
    _state_from = [
        "01_in_progress",
        "02_changes_requested",
        "03_approved",
        "04_waiting_normal",
    ]
    _state_to = ["1_done", "1_canceled"]

    def _get_requested_notification_subtype(self):
        return "project_task_tier_validation.project_task_tier_validation_requested"

    def _get_accepted_notification_subtype(self):
        return "project_task_tier_validation.project_task_tier_validation_accepted"

    def _get_rejected_notification_subtype(self):
        return "project_task_tier_validation.project_task_tier_validation_rejected"

    @api.model
    def _get_under_validation_exceptions(self):
        res = super()._get_under_validation_exceptions()
        res.append("date_last_stage_update")
        return list(set(res))

    @api.model
    def _get_after_validation_exceptions(self):
        res = super()._get_after_validation_exceptions()
        res.append("date_last_stage_update")
        return list(set(res))
