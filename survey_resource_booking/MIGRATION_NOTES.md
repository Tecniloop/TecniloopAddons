# Migration notes: survey_resource_booking 17.0 -> 18.0

- Bumped module version to `18.0.1.0.0` and marked the addon as installable.
- Updated README, generated HTML description links, Runboat branch and Weblate references from 17.0 to 18.0.
- Updated XML data roots to `<odoo>`.
- Kept the existing inheritance points against OCA `resource_booking` 18.0:
  - `resource_booking.resource_booking_type_view_form`, field `requester_advice`.
  - `resource_booking.resource_booking_view_form`, group `booking`.
- Kept the Odoo 18 survey invitation flow based on `survey.user_input.action_resend()` and `survey.invite.action_invite()`.
- Removed the production dependency on `odoo.tests.common.Form` by creating the transient `survey.invite` wizard from the action context/defaults.
- Fixed the `UserError` message interpolation when the booking type has no survey.

Static validation performed here:

- Python files parsed successfully with `ast.parse`.
- XML files parsed successfully with `xml.etree.ElementTree`.

A full install/update test still needs to be run in an Odoo 18 database with dependencies installed: `survey` and OCA `resource_booking` 18.0.
