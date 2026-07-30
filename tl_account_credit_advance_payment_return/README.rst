==============================================
Anticipos de crédito - Devoluciones de pago
==============================================

Puente entre ``tl_account_credit_advance`` y ``account_payment_return``
(OCA/account-payment). Se instala solo cuando ambos están presentes.

El problema
===========

Los dos módulos saben registrar un impago, pero ninguno sabe del otro.

La devolución de pago estándar hace lo correcto para un cobro normal: reabre la
factura cargando la cuenta del cliente y abona el banco por el importe devuelto y
sus gastos. Lo que no sabe es que ese efecto no era un cobro cualquiera: estaba
en la cuenta de créditos cedidos y lo había financiado el banco. Si se deja así,
la 4311 se queda con saldo vivo de un efecto que ya no existe y la deuda de la
5208 no se cancela nunca.

Qué hace este módulo
====================

Reconoce el efecto en la devolución
-----------------------------------

Al emparejar los apuntes de una línea de devolución, el módulo detecta si detrás
hay un efecto de una remesa anticipada y lo muestra en la línea. La devolución
completa hereda la póliza a la que pertenece.

Para no mezclar conceptos en un mismo documento, una devolución no puede
combinar efectos de dos pólizas distintas, ni efectos anticipados con cobros
ordinarios. Los bancos mandan las devoluciones de una remesa financiada por
separado, así que en la práctica no estorba.

Cierra el ciclo del anticipo al confirmar
-----------------------------------------

Además del asiento estándar de la devolución, se genera un segundo asiento en el
diario de vencimientos de la póliza::

    (5208) Deudas por efectos descontados
                a (4311) Clientes, efectos comerciales descontados

Los dos apuntes se concilian: el de la 4311 contra el crédito cedido de la
remesa, y el de la 5208 contra la financiación que hizo el banco. El efecto pasa
a estado *impagado* y deja de consumir límite de la póliza.

Son dos asientos y no uno a propósito: cada uno está cuadrado y se lee por sí
solo, y la devolución estándar sigue comportándose exactamente igual que para
cualquier otro cobro. El resultado combinado es el mismo::

    (430)  Clientes                 nominal      ← devolución estándar
    (626)  Gastos de devolución     gastos       ← devolución estándar
                a (572) Bancos              nominal + gastos
    (5208) Deudas por efectos descontados        ← este módulo
                a (4311) Clientes, efectos descontados

Cancelar la devolución deshace también el segundo asiento y devuelve el efecto a
*anticipado*.

Conciliación bancaria
---------------------

El banco te retira el nominal y sus gastos en un único movimiento, así que las
dos patas tienen que quedar en la misma cuenta transitoria para que la línea de
extracto se case de una vez.

La devolución estándar ya evita la cuenta de liquidez para el nominal, pero coge
la transitoria del método de pago o la de la compañía, y **los gastos sí los
abona directamente contra la cuenta de liquidez del diario**. Este módulo corrige
las dos cosas: nominal y gastos van contra la cuenta transitoria de la póliza, que
en multibanco es la de ese banco y no la genérica.

Además, la devolución tiene que registrarse en el diario del banco que anticipó
los efectos; si no coincide, no deja confirmar. Contabilizarla en otro banco
dejaría la transitoria descuadrada en los dos.

Elegir cómo se tratan los impagos
---------------------------------

La línea de anticipo gana el campo **Tratamiento de impagos**:

* **Devolución de pago** (por defecto) — la vía de este módulo. Reabre la factura
  original, la marca como devuelta, permite registrar el motivo de devolución y
  aprovecha la importación de ficheros de devoluciones del banco.
* **Asistente de impago** — el asistente propio del módulo base, que lleva la
  deuda a la cuenta de impagados (4315) en vez de reabrir la factura.

En la ficha del efecto sólo aparece el botón de la vía configurada, así que no
hay dos caminos compitiendo. El botón crea la devolución ya emparejada con los
apuntes correctos, sin tener que buscarlos a mano.

Créditos
========

Autor: Tecniloop

Licencia: AGPL-3
