<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Root menu without parent: it appears as an application in the Odoo main menu. -->
    <menuitem id="menu_fiebdc_root" name="BC3 / FIEBDC" sequence="25"/>

    <menuitem id="menu_fiebdc_operations" name="Operaciones" parent="menu_fiebdc_root" sequence="10"/>
    <menuitem id="menu_fiebdc_import_history" name="Historial de importaciones" parent="menu_fiebdc_operations" action="action_fiebdc_import_batch" sequence="20"/>

    <!-- Keep the legacy file-import menu XML ID inactive so it also disappears on module update. -->
    <record id="menu_fiebdc_import" model="ir.ui.menu">
        <field name="name">Importar productos BC3</field>
        <field name="parent_id" ref="menu_fiebdc_operations"/>
        <field name="sequence">10</field>
        <field name="active" eval="False"/>
    </record>

    <menuitem id="menu_fiebdc_configuration" name="Configuracion" parent="menu_fiebdc_root" sequence="20"/>
    <menuitem id="menu_fiebdc_manufacturers" name="Fabricantes" parent="menu_fiebdc_configuration" action="action_fiebdc_manufacturer" sequence="10"/>
</odoo>
