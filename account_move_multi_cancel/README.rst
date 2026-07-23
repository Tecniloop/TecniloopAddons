============================
Mass Journal Entry Cancel v19
============================

Módulo para cancelar o resetear múltiples asientos contables en Odoo 19.

Cambios en la migración a v19
=============================

1. **Version actualizada**: de 18.0 a 19.0
2. **API Compatibility**: Todos los métodos utilizados (button_cancel, button_draft) son compatibles con Odoo 19
3. **TransientModel**: Sigue siendo el mismo en Odoo 19
4. **Server Actions**: Las acciones de servidor con bindings siguen siendo compatibles

Características
===============

- Cancelar múltiples asientos contables en estado "posted"
- Resetear múltiples asientos contables en estado "cancel" a estado "draft"
- Integración con la lista de asientos contables mediante acciones de servidor

Instalación
===========

1. Copiar el módulo al directorio de módulos personalizados
2. Actualizar la lista de módulos
3. Instalar el módulo "Mass Journal Entry Cancel"
4. Asignar el grupo "Manage Multiple Journal Entry Cancel" a los usuarios que necesiten acceso

Uso
===

1. Ir a Contabilidad > Asientos Contables
2. Seleccionar uno o más asientos
3. En el menú de acciones de lista, seleccionar:
   - "Multiple Journal Entry Cancel" para cancelar asientos
   - "Multiple Journal Entry Reset" para resetear asientos a draft

Requisitos
==========

- Odoo 19.0
- Módulo base: account
