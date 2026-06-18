<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Fallback entry point: available from Products list/form under the Action menu. -->
    <record id="action_server_open_fiebdc_import_wizard" model="ir.actions.server">
        <field name="name">Importar productos BC3 / FIEBDC</field>
        <field name="model_id" ref="product.model_product_template"/>
        <field name="binding_model_id" ref="product.model_product_template"/>
        <field name="binding_view_types">list,form</field>
        <field name="state">code</field>
        <field name="code"><![CDATA[
action = {
    'type': 'ir.actions.act_window',
    'name': 'Importar productos BC3 / FIEBDC',
    'res_model': 'fiebdc.import.wizard',
    'view_mode': 'form',
    'view_id': env.ref('tl_fiebdc_product_import.view_fiebdc_import_wizard_form').id,
    'target': 'new',
    'context': {},
}
        ]]></field>
    </record>

    <!-- Direct window action binding, also shown in the Products Action menu. -->
    <record id="action_fiebdc_import_wizard_product_binding" model="ir.actions.act_window">
        <field name="name">Importar productos BC3 / FIEBDC</field>
        <field name="res_model">fiebdc.import.wizard</field>
        <field name="view_mode">form</field>
        <field name="view_id" ref="view_fiebdc_import_wizard_form"/>
        <field name="target">new</field>
        <field name="binding_model_id" ref="product.model_product_template"/>
        <field name="binding_type">action</field>
        <field name="binding_view_types">list,form</field>
    </record>
</odoo>
