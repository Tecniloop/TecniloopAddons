<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_product_template_form_fiebdc" model="ir.ui.view">
        <field name="name">product.template.form.fiebdc</field>
        <field name="model">product.template</field>
        <field name="inherit_id" ref="product.product_template_form_view"/>
        <field name="arch" type="xml">
            <xpath expr="//form/header" position="inside">
                <button name="action_open_fiebdc_import_wizard" type="object" string="Importar BC3" class="btn-primary"/>
            </xpath>
            <xpath expr="//sheet/notebook" position="inside">
                <page string="FIEBDC / BC3">
                    <group>
                        <group>
                            <field name="bc3_code"/>
                            <field name="bc3_alias_codes"/>
                            <field name="bc3_type"/>
                            <field name="bc3_unit_code"/>
                            <field name="bc3_price_date"/>
                            <field name="bc3_source_file"/>
                        </group>
                    </group>
                    <group string="BC3 Description">
                        <field name="bc3_long_description" nolabel="1"/>
                    </group>
                    <group string="Raw BC3 Values">
                        <field name="bc3_raw_prices_json" nolabel="1"/>
                        <field name="bc3_technical_json" nolabel="1"/>
                    </group>
                </page>
            </xpath>
        </field>
    </record>
</odoo>
