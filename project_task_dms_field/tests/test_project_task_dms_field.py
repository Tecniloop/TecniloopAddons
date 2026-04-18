# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase


class TestProjectTaskDmsField(TransactionCase):
    def test_task_has_dms_field(self):
        task = self.env["project.task"].create({"name": "Task with docs"})
        self.assertIn("dms_directory_ids", task._fields)
