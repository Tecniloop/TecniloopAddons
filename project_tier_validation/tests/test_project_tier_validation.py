from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from odoo.addons.base.tests.common import BaseCommon


@tagged("post_install", "-at_install")
class TestProjectTierValidation(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_model = cls.env.ref("project.model_project_project")
        cls.reviewer = new_test_user(
            cls.env,
            name="Project Reviewer",
            login="project_reviewer",
            groups="base.group_user,project.group_project_user",
        )
        cls.env["tier.definition"].create(
            {
                "model_id": cls.project_model.id,
                "review_type": "individual",
                "reviewer_id": cls.reviewer.id,
                "definition_domain": "[('name', 'ilike', 'Validation')]",
            }
        )
        cls.open_stage = cls.env["project.project.stage"].create({"name": "Open Validation", "sequence": 1, "fold": False})
        cls.closed_stage = cls.env["project.project.stage"].create({"name": "Closed Validation", "sequence": 99, "fold": True})
        cls.project = cls.env["project.project"].create({
            "name": "Validation Project",
            "stage_id": cls.open_stage.id,
        })

    def test_project_model_name(self):
        self.assertIn("project.project", self.env["tier.definition"]._get_tier_validation_model_names())

    def test_project_close_requires_validation(self):
        with self.assertRaises(ValidationError):
            self.project.write({"stage_id": self.closed_stage.id})
        self.project.request_validation()
        self.project.with_user(self.reviewer).validate_tier()
        self.project.write({"stage_id": self.closed_stage.id})
        self.assertEqual(self.project.stage_id, self.closed_stage)
