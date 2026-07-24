Instalación
===========

Instale este módulo como cualquier otro addon de Odoo.

El módulo base no depende de ``queue_job`` y procesa las importaciones de
forma síncrona.

Para habilitar el procesamiento en segundo plano instale además el addon
opcional ``tl_suenlace_import_queue_job`` y su dependencia OCA ``queue_job``.


Actualizaciones con la base en uso
----------------------------------
La versión 19.0.1.13.1 no añade columnas almacenadas nuevas a ``account.move``
para el seguimiento de cobros. El estado de revisión se deriva de actividades y
la idempotencia de pagos usa una referencia técnica, permitiendo desplegar el
código antes de ejecutar la actualización del módulo sin bloquear el registro.
