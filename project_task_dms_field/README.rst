======================
Project Task DMS Field
======================

This module adds a Documents tab to project tasks using ``dms.field.mixin``.

**Main features**

* Adds ``dms_directory_ids`` support to ``project.task``.
* Shows a Documents tab in the task form.
* Allows configuring an Embedded DMS template for project tasks.
* Demo data includes a sample template for project tasks.

Configuration
=============

1. Go to Documents > Configuration > Embedded DMS templates.
2. Create a template for model ``project.task``.
3. Choose storage and access groups.
4. Do not use `user_ids` as the DMS `user field` unless you also customize `dms_field` for multi-user support.
5. Define the folder hierarchy to be created per task.

Usage
=====

Open a task and use the Documents tab. The linked directory structure will be
created and managed by ``dms_field``.
