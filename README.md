<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Top-level menu. The action is also attached to the root entry so it is visible/searchable in the Odoo app menu. -->
    <menuitem id="menu_fiebdc_root"
              name="BC3 / FIEBDC"
              sequence="70"
              action="action_fiebdc_import_wizard"/>

    <menuitem id="menu_fiebdc_import"
              name="Importar productos BC3"
              parent="menu_fiebdc_root"
              action="action_fiebdc_import_wizard"
              sequence="10"/>

    <menuitem id="menu_fiebdc_import_history"
              name="Historial de importaciones"
              parent="menu_fiebdc_root"
              action="action_fiebdc_import_batch"
              sequence="20"/>

    <!-- Additional entry under Inventory, so users can launch the wizard from the Inventory app too. -->
    <menuitem id="menu_stock_fiebdc_root"
              name="BC3 / FIEBDC"
              parent="stock.menu_stock_root"
              sequence="95"/>

    <menuitem id="menu_stock_fiebdc_import"
              name="Importar productos BC3"
              parent="menu_stock_fiebdc_root"
              action="action_fiebdc_import_wizard"
              sequence="10"/>

    <menuitem id="menu_stock_fiebdc_import_history"
              name="Historial de importaciones BC3"
              parent="menu_stock_fiebdc_root"
              action="action_fiebdc_import_batch"
              sequence="20"/>
</odoo>
