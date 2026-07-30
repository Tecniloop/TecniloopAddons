=====================================
Anticipos de crédito - Gestión contable
=====================================

Contabiliza correctamente las remesas financiadas (anticipo de créditos
comerciales / descuento comercial) sobre la base de ``account_payment_order``
(OCA/bank-payment) y ``l10n_es_account_banking_sepa_fsdd`` (OCA/l10n-spain).

El problema
===========

``l10n_es_account_banking_sepa_fsdd`` marca el fichero SEPA con el prefijo
``FSDD`` para que el banco sepa que la remesa está financiada, pero no cambia
nada en la contabilidad: al subir la remesa, el flujo estándar da la factura por
cobrada y lleva el importe a la cuenta transitoria de la tesorería.

Eso no es lo que ocurre en un anticipo. El banco adelanta el dinero, pero el
riesgo sigue siendo nuestro hasta el vencimiento: hay que reclasificar el crédito
y reconocer una deuda financiera. Este módulo implementa ese ciclo completo.

Los cuatro momentos del ciclo
=============================

1. Cesión (al subir la remesa)
------------------------------

El contravalor de los cobros deja de ser la cuenta transitoria de tesorería y
pasa a ser la cuenta de créditos cedidos. Se genera automáticamente al confirmar
y subir la remesa, con la conciliación de las facturas incluida::

    (4311) Clientes, efectos comerciales descontados
                a (430) Clientes

2. Financiación (asistente "Registrar anticipo")
------------------------------------------------

Se introduce la liquidación del banco. Los intereses y comisiones se proponen a
partir de las condiciones de la línea (tipo anual, días de valoración, base
360/365, comisión mínima por efecto) y se pueden ajustar::

    (572) Bancos                            líquido
    (665) Intereses por descuento           intereses
    (626) Servicios bancarios               comisiones
                a (5208) Deudas por efectos descontados    nominal

La pata de banco no va contra la cuenta de liquidez del diario, sino contra la
cuenta transitoria de cobros: en Odoo la línea de extracto ya carga la cuenta de
liquidez, así que hacerlo aquí duplicaría el saldo y el asiento no aparecería en
el widget de conciliación. Contra la transitoria, el apunte sale como candidato y
al conciliar el extracto se cancela solo. La cuenta se puede fijar en la póliza;
si se deja vacía se usa la del diario del banco y, en su defecto, la de la
compañía.

Cuando el banco no descuenta los gastos
---------------------------------------

Lo normal es que el banco te abone el nominal menos sus intereses y comisiones, y
el extracto traiga una sola línea por el líquido. Pero algunos abonan el nominal
íntegro y liquidan los gastos aparte, normalmente a fin de mes.

El campo **Liquidación de intereses y comisiones** de la póliza recoge esa
diferencia:

* *Descontados del anticipo* (por defecto) — el asistente propone los importes
  calculados y la transitoria queda con el líquido.
* *Cobrados aparte* — el asistente propone cero, la transitoria queda con el
  nominal completo y casa con la línea de abono. Los gastos se contabilizan al
  conciliar su propia línea de extracto, repartiéndolos contra la 665 y la 626.

Los apuntes de intereses y comisiones arrastran la **distribución analítica** que
se configure en la póliza, que es la forma de saber cuánto cuesta cada banco sin
tener que subcuentar el plan contable.

3. Vencimiento cobrado
----------------------

El cliente paga al banco, se cancela la deuda contra el crédito cedido y ambas
partidas quedan conciliadas::

    (5208) Deudas por efectos descontados
                a (4311) Clientes, efectos comerciales descontados

4. Impago (asistente "Registrar impago")
-----------------------------------------

El banco recupera el dinero y sus gastos, y la deuda vuelve al cliente::

    (5208) Deudas por efectos descontados   nominal
    (626)  Gastos de devolución             gastos
                a (572) Bancos                          nominal + gastos

    (4315) Clientes, efectos comerciales impagados
                a (4311) Clientes, efectos comerciales descontados

Opcionalmente la reclamación se lleva a la cuenta ordinaria del cliente en lugar
de a la 4315.

Plazo de recurso y asiento programado
=====================================

El riesgo no termina el día del vencimiento, sino cuando expira el plazo en que
el banco todavía puede devolverte el efecto. La póliza tiene un campo de **días
de recurso** para eso.

Con **Programar el asiento de vencimiento** activado, al registrar el anticipo se
escribe ya el asiento de vencimiento, en borrador, con fecha del final del plazo
de recurso y marcado para publicarse solo en esa fecha. Lo publica la acción
planificada estándar de Odoo, no una propia. Ventajas:

* La cancelación de cada efecto se ve por adelantado, agrupada por fecha.
* No hay que liquidar remesa por remesa a mano.

Cada efecto aporta sus dos apuntes al asiento, y esos dos apuntes se compensan
entre sí. Por eso, si el banco devuelve un efecto antes de la fecha, basta con
quitar sus dos líneas: el asiento sigue cuadrado y el resto de efectos mantienen
su cita. Eso lo hacen automáticamente tanto el asistente de impago como las
devoluciones de pago.

Y como último recurso, un asiento de vencimiento se niega a publicarse si alguno
de sus efectos ya no está en estado *anticipado*: se queda en borrador y alguien
tiene que mirarlo, en vez de cancelar una deuda que todavía se debe.

Sin la programación activada, el ciclo funciona igual pero liquidando a mano con
el asistente, o con el botón *Liquidar vencidos ahora* de la póliza.

Configuración
=============

#. Contabilidad > Clientes > Anticipos de crédito > Líneas de anticipo: cree una
   línea por cada póliza, indicando el diario del banco, el diario para los
   asientos de vencimiento, las cuentas contables y las condiciones económicas.
#. En el modo de pago de la remesa, marque *Anticipo de crédito* y seleccione la
   línea. Al marcarlo se activa también *Financed Charge* (prefijo FSDD del
   fichero SEPA).
#. El límite de la póliza se controla al confirmar la remesa: si el nominal
   pendiente supera el disponible, la confirmación se bloquea.

Notas
=====

* Cada ``account.payment`` de la remesa es un *efecto*, con su propio vencimiento
  y su propio estado (cedido, anticipado, liquidado, impagado). Vencimientos e
  impagos se pueden tratar efecto a efecto o en bloque.
* La cuenta 4311 debe ser de tipo *A cobrar* y conciliable, y no debe ser la
  cuenta de cliente por defecto de ningún contacto. La 5208 debe ser conciliable
  para poder casar la deuda con la liquidación del banco.
* Los apuntes de la 4311 son conciliables y llevan cliente, así que el widget de
  conciliación bancaria los propondrá si llega una transferencia de ese mismo
  cliente. Casar ahí rompe el ciclo del efecto: el cobro de un efecto anticipado
  lo recibe el banco, no tú, y se registra con el asistente de vencimientos.
* Al pasar a borrador un asiento de anticipo, vencimiento o impago se revierte el
  estado de los efectos afectados.

Créditos
========

Autor: Tecniloop

Licencia: AGPL-3
