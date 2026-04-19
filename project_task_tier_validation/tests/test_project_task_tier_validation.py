from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from odoo.addons.base.tests.common import BaseCommon


@tagged("post_install", "-at_install")
class TestProjectTaskTierValidation(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.task_model = cls.env.ref("project.model_project_task")
        cls.reviewer = new_test_user(
            cls.env,
            name="Task Reviewer",
            login="task_reviewer",
            groups="base.group_user,project.group_project_user",
        )
        cls.env["tier.definition"].create(
            {
                "model_id": cls.task_model.id,
                "review_type": "individual",
                "reviewer_id": cls.reviewer.id,
                "definition_domain": "[('name', 'ilike', 'Validation')]",
            }
        )
        cls.project = cls.env["project.project"].create({"name": "Tier Validation Project"})
        cls.task = cls.env["project.task"].create({
            "name": "Validation Task",
            "project_id": cls.project.id,
        })

    def test_task_model_name(self):
        self.assertIn("project.task", self.env["tier.definition"]._get_tier_validation_model_names())

    def test_task_done_requires_validation(self):
        with self.assertRaises(ValidationError):
            self.task.write({"state": "1_done"})
        self.task.request_validation()
        self.task.with_user(self.reviewer).validate_tier()
        self.task.write({"state": "1_done"})
        self.assertEqual(self.task.state, "1_done")
