Importador SUENLACE para Odoo
=============================

Importa ficheros de longitud fija SUENLACE.DAT de a3asesor Eco/Con y crea
cuentas, terceros y documentos contables en Odoo.

El tratamiento depende de la opción **Interpretar impuestos y crear
facturas**:

* desactivada: los registros tipo 0 y los bloques de factura 1/2+9 se crean
  como asientos contables. Se conservan las cuentas a3 del DAT y no se aplican
  ``account.tax`` ni cuentas de reparto de Odoo;
* activada: los registros 1/2+9 se crean como facturas o rectificativas Odoo y
  los registros tipo 0 pueden interpretar únicamente las subcuentas fiscales
  configuradas expresamente en los mapeos.

Incluye normalización de NIF españoles, mapeos de impuestos y posiciones
fiscales, carga idempotente de los casos habituales, detección de recargo de
equivalencia y retenciones generales o de arrendamientos, y actividades de
revisión cuando faltan cuentas o no cuadran los totales.

El procesamiento del módulo base es síncrono. La integración con OCA
``queue_job`` se distribuye en el addon separado y opcional
``tl_suenlace_import_queue_job``.
