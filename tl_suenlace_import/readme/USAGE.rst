Uso
===

Abra **Contabilidad > SUENLACE > Importar fichero**, seleccione el fichero y
el diario general. Active **Interpretar impuestos y crear facturas** solo
cuando desee convertir los bloques 1/2+9 en facturas Odoo.

Con la opción desactivada, todos los documentos se generan como asientos y las
cuentas del DAT no se sustituyen. Los diarios de ventas y compras solo se usan
cuando la opción está activada.

Los mapeos predeterminados se cargan automáticamente al instalar o actualizar
el módulo. Para reintentarlo después de cambiar el plan contable o crear
impuestos, utilice **Contabilidad > SUENLACE > Cargar mapeos predeterminados**.

El módulo base ejecuta las operaciones de forma síncrona. Si está instalado
``tl_suenlace_import_queue_job`` puede activar el procesamiento asíncrono en
cada lote.

Si el fichero contiene un NIF que Odoo rechaza pero debe conservarse para la
migración, active **Omitir validación del NIF de Odoo**. La excepción se aplica
solo a los terceros creados o actualizados por ese lote.

Terceros y subcuentas de cliente/proveedor
===========================================

Los terceros creados por SUENLACE se registran como compañías. Cuando el
fichero informa una cuenta ``43``/``44``, se crea si es necesario y se asigna
como cuenta a cobrar del partner para la compañía importada. Las cuentas
``40``/``41`` se asignan del mismo modo como cuenta a pagar. Un tercero que
actúe como cliente y proveedor puede conservar ambas propiedades.

En los asientos literales de facturas, las subcuentas de IVA, recargo y
retención se localizan por su código y se crean automáticamente si todavía no
existen. Para compatibilidad con distintos generadores SUENLACE, el importador
revisa tanto los campos de cuenta soportada como repercutida y conserva el
código que realmente venga informado en el DAT.

Procesamiento incremental
========================

Por defecto, las acciones de parseo y procesado no ejecutan el fichero dentro
de la petición HTTP. El lote queda en cola y el cron nativo ``SUENLACE:
procesar lotes pendientes`` procesa:

* hasta 2.000 registros por lote de parseo;
* hasta 25 cuentas/terceros por lote;
* hasta 25 asientos o facturas por lote contable.

Los límites se pueden cambiar en Ajustes de Contabilidad o en el propio
asistente. Cada documento se ejecuta dentro de un savepoint independiente. Un
documento incorrecto queda marcado con error sin deshacer los documentos
correctos del mismo fichero.

Si se instala ``tl_suenlace_import_queue_job``, el mismo motor incremental se
ejecuta mediante OCA Queue Job. El cron nativo excluye automáticamente los
lotes asignados a Queue Job para evitar procesamientos concurrentes.


Cobros y pagos en cuentas 570/572
=================================

Al encontrar una cuenta de tesorería ``572...`` o ``570...``, el importador
crea, si todavía no existe, su diario de banco o efectivo. Cada cuenta conserva
un diario propio. Los movimientos de cobro/pago se registran en ese diario y
se concilian con el vencimiento correspondiente.
