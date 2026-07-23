Configuración
=============

Al instalar o actualizar el addon se cargan, para las compañías con país
fiscal España, los mapeos habituales que puedan relacionarse de forma segura
con los impuestos y posiciones fiscales realmente existentes en su plan
contable.

La carga es idempotente: no modifica ni elimina mapeos manuales. Puede
repetirse desde **Contabilidad > SUENLACE > Cargar mapeos predeterminados**.

Revise después los menús **Mapeo de impuestos** y **Mapeo de posiciones
fiscales**, especialmente si utiliza tipos históricos, impuestos propios,
operaciones exentas/no sujetas o una localización personalizada.

Sin el complemento opcional, el parseo y el procesado se ejecutan de forma
inmediata en la petición de Odoo.

Modo de importación contable
============================

En Contabilidad / Ajustes puede definirse por compañía el comportamiento
predeterminado. Las opciones también pueden cambiarse para cada lote.

**Asociar terceros en asientos**
-------------------------------

Asigna ``partner_id`` a:

* los apuntes de cliente o proveedor de los asientos tipo 0;
* la línea de cliente/proveedor de una factura importada como asiento literal.

No modifica la cuenta contable. Si se crean facturas Odoo, el tercero es
obligatorio y se identifica o crea independientemente de esta opción.

**Interpretar impuestos y crear facturas**
------------------------------------------

Desactivada:

* los registros tipo 0 se importan literalmente;
* los bloques 1/2+9 se crean como ``account.move`` de tipo ``entry``;
* se respetan la cuenta de tercero de la cabecera, la cuenta de base y las
  cuentas de IVA, recargo y retención indicadas en el DAT;
* no se asignan ``account.tax``, líneas de reparto ni etiquetas fiscales Odoo;
* si una cuota fiscal no trae cuenta en el DAT, no se inventa ni sustituye una
  cuenta: el asiento queda en borrador con actividad de revisión.

Activada:

* los bloques 1/2+9 se crean como facturas o rectificativas Odoo;
* se identifican tercero, posición fiscal, IVA, recargo y retenciones;
* Odoo genera la contrapartida y las líneas fiscales usando las cuentas de
  reparto de los impuestos;
* los asientos tipo 0 solo convierten una subcuenta fiscal cuando existe un
  mapeo explícito en **Subcuentas a3 en asientos**.

Subcuentas fiscales de a3
=========================

a3 puede informar subcuentas distintas por tipo, por ejemplo ``472...21`` y
``472...10``.

En modo literal esas cuentas se conservan exactamente. En modo factura Odoo,
los porcentajes y la naturaleza fiscal se convierten a ``account.tax`` y Odoo
contabiliza las cuotas en las cuentas definidas en
``account.tax.repartition.line``. Las subcuentas de origen quedan guardadas
como trazabilidad.
