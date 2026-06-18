<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_fiebdc_import_batch_list" model="ir.ui.view">
        <field name="name">fiebdc.import.batch.list</field>
        <field name="model">fiebdc.import.batch</field>
        <field name="arch" type="xml">
            <list string="FIEBDC Imports">
                <field name="create_date"/>
                <field name="name"/>
                <field name="bc3_filename"/>
                <field name="state"/>
                <field name="total_concepts"/>
                <field name="importable_concepts"/>
                <field name="created_products"/>
                <field name="updated_products"/>
                <field name="attachments_created"/>
                <field name="warning_count"/>
                <field name="error_count"/>
            </list>
        </field>
    </record>

    <record id="view_fiebdc_import_batch_form" model="ir.ui.view">
        <field name="name">fiebdc.import.batch.form</field>
        <field name="model">fiebdc.import.batch</field>
        <field name="arch" type="xml">
            <form string="FIEBDC Import">
                <sheet>
                    <group>
                        <group>
                            <field name="name"/>
                            <field name="state"/>
                            <field name="zip_filename"/>
                            <field name="bc3_filename"/>
                        </group>
                        <group>
                            <field name="total_concepts"/>
                            <field name="importable_concepts"/>
                            <field name="created_products"/>
                            <field name="updated_products"/>
                            <field name="skipped_products"/>
                            <field name="attachments_created"/>
                            <field name="warning_count"/>
                            <field name="error_count"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Logs">
                            <field name="log_ids" readonly="1">
                                <list>
                                    <field name="level"/>
                                    <field name="bc3_code"/>
                                    <field name="message"/>
                                </list>
                            </field>
                        </page>
                    </notebook>
                </sheet>
                <chatter open_attachments="True"/>
            </form>
        </field>
    </record>

    <record id="action_fiebdc_import_batch" model="ir.actions.act_window">
        <field name="name">FIEBDC Import History</field>
        <field name="res_model">fiebdc.import.batch</field>
        <field name="view_mode">list,form</field>
    </record>
</odoo>
