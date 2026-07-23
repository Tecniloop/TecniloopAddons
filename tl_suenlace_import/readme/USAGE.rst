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
