==========================================
Anticipos de crédito - Riesgo financiero
==========================================

Puente entre ``tl_account_credit_advance`` y ``account_financial_risk``
(OCA/credit-control). Se instala solo cuando ambos están presentes.

El problema
===========

``account_financial_risk`` reparte el riesgo según la cuenta del apunte: si la
cuenta es la de cliente del contacto, va a *facturas*; si es cualquier otra
cuenta de tipo *A cobrar*, va al cajón genérico *importe en otras cuentas*.

Al anticipar una remesa, el crédito se reclasifica a la 4311 y la factura queda
conciliada. El riesgo no desaparece —eso está bien— pero se mezcla en ese cajón
genérico junto a cualquier otro saldo, sin límite propio y sin posibilidad de
distinguir un efecto cedido de uno impagado.

Qué hace este módulo
====================

Dos conceptos de riesgo propios
-------------------------------

Añade a la ficha del cliente, con su casilla de inclusión y su límite
específico, igual que el resto:

* **Efectos anticipados** — saldo vivo en la cuenta de créditos cedidos (4311).
* **Efectos impagados** — saldo vivo en la cuenta de impagados (4315).

Ambos importes se restan del cajón genérico, así que no se cuentan dos veces. La
clasificación es por cuenta, no por vencimiento: un efecto cuyo vencimiento ya
pasó pero que todavía no has liquidado ni devuelto sigue siendo un efecto
anticipado, no un impagado.

El botón de detalle de cada concepto abre el pivot con los apuntes que lo
componen, como en los conceptos originales.

Con recurso / sin recurso
-------------------------

La línea de anticipo tiene una casilla **Con recurso**, activa por defecto: el
banco puede devolverte el efecto, así que el riesgo de impago sigue siendo tuyo y
los créditos cedidos cuentan en el riesgo del cliente.

Si la desmarcas (factoring sin recurso real, en el que el riesgo de insolvencia
se transfiere al banco), los créditos cedidos dejan de sumar riesgo: se restan
del cajón genérico y no se añaden a ningún otro.

Límite de concentración por cliente
------------------------------------

El límite global de la póliza y el riesgo por cliente dejan de ser controles
independientes. En la línea de anticipo puedes fijar cuánto puede tener cedido un
solo librado, de tres formas combinables:

* **Límite por cliente** — importe fijo.
* **Límite por cliente (%)** — porcentaje del límite de la póliza, que es como lo
  suelen redactar los bancos.
* **Limitar por el límite de crédito del cliente** — usa el límite de crédito de
  su ficha, el mismo que gobierna el riesgo financiero.

Se aplica el más restrictivo de los que estén configurados, y cuenta lo que ya
tiene cedido de remesas anteriores, no sólo la que estás confirmando.

Control de riesgo al confirmar la remesa
----------------------------------------

En la línea de anticipo, **Comprobación de riesgo al confirmar**, que gobierna
tanto el riesgo excedido como el límite de concentración:

* *Sin comprobación* (por defecto).
* *Avisar* — deja una nota en el chatter de la remesa con los clientes afectados.
* *Bloquear* — impide confirmar la remesa hasta que se saquen esas transacciones
  o se amplíen los límites.

Desglose por línea de anticipo
-------------------------------

Contabilidad > Clientes > Anticipos de crédito > **Riesgo por línea de anticipo**:
tabla dinámica de clientes contra pólizas, con filtros por estado del efecto y
por vencido. Responde a "cuánto tiene cedido cada banco de cada cliente".

Hay accesos directos desde los dos lados:

* En la ficha del cliente, bajo el total de riesgo, un botón que abre el desglose
  agrupado por póliza y estado.
* En la línea de anticipo, un botón que abre el desglose por cliente.

Aviso por efectos devueltos al facturar
----------------------------------------

Un cliente puede estar holgado de límite y tener efectos devueltos: el importe
puede ser pequeño, pero que el banco te haya devuelto un efecto dice bastante más
que el saldo pendiente.

En Ajustes > Contabilidad > Riesgo financiero, **Efectos de anticipo devueltos**
hace que al validar una factura de un cliente con efectos devueltos aparezca el
asistente de riesgo excedido de ``account_financial_risk``, con el importe
devuelto en el mensaje. Se puede fijar un importe mínimo a partir del cual avisar.
El asistente se comporta como siempre: un gestor de riesgo puede continuar, el
resto no.

Cómo se mueve el riesgo
=======================

Con un cliente de 100 € en una remesa anticipada con recurso:

==================================  ===============  ===============  ===============
Momento                             Facturas         Anticipados      Impagados
==================================  ===============  ===============  ===============
Factura emitida                     100              0                0
Remesa subida al banco              0                100              0
Vencimiento cobrado                 0                0                0
Impago (a cuenta 4315)              0                0                100
Impago (a cuenta del cliente)       100              0                0
==================================  ===============  ===============  ===============

El total del riesgo nunca salta: sólo cambia de concepto.

Créditos
========

Autor: Tecniloop

Licencia: AGPL-3
