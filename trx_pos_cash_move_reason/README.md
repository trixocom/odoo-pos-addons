# trx_pos_cash_move_reason

Motivos de entrada/salida de efectivo para el Punto de Venta de Odoo 19 CE, con
imputación directa a cuentas contables.

## Problema que resuelve

En Odoo 19 la entrada/salida de efectivo del POS (`pos.session.try_cash_in_out`)
crea una línea de extracto en el diario de efectivo **sin contrapartida**: el
asiento queda contra la *cuenta transitoria* (suspense) del diario. En Enterprise
esas líneas se concilian después desde la conciliación bancaria (widget +
modelos de conciliación); en Community no hay herramienta para hacerlo y el saldo
queda colgado en la transitoria.

Este módulo hace que el cajero elija un **motivo** y que el asiento se genere
directamente contra la cuenta del motivo. La línea de extracto nace conciliada.

## Funcionalidad

- **Motivos** (`pos.cash.move.reason`) en *Punto de Venta › Configuración ›
  Motivos de entrada/salida*: nombre, uso en entradas y/o salidas, cuenta de
  entrada, cuenta de salida, compañía y puntos de venta (vacío = todos).
- **Popup del POS**: selector de motivo filtrado por tipo (entrada/salida). Con
  motivo elegido, el texto libre pasa a ser una nota opcional. La etiqueta
  `Motivo - nota` va a la línea de extracto, a la lista de movimientos y al ticket.
- **Exigir motivo** (Ajustes del POS › Pago): si hay motivos para ese tipo de
  movimiento, no se puede confirmar sin elegir uno. Se valida también en el
  servidor. Sin motivos configurados el comportamiento es el estándar.
- **Backend**: botones *Entrada de efectivo* / *Salida de efectivo* en la sesión
  abierta (gestores POS o usuarios con facturación), mismo circuito y permisos que
  el POS.
- **Reporte** *Punto de Venta › Informes › Movimientos de caja*: entradas y
  salidas agrupables por motivo, sesión y fecha.

## Detalle técnico

- Hook: `pos.session._prepare_account_bank_statement_line_vals` agrega
  `counterpart_account_id` (cuenta del motivo) y `pos_cash_move_reason_id`.
- El id del motivo viaja en `extras` (`trx_cash_reason_id`), igual que `pos_hr`
  agrega `employee_id`; no se cambia la firma de `try_cash_in_out`.
- Las líneas de extracto creadas por entrada/salida quedan marcadas con
  `trx_pos_cash_move` (las de ventas en efectivo y diferencias de cierre no).
- Los motivos no se pueden borrar si tienen movimientos (`ondelete=restrict`):
  se archivan.

## Diferencias con OCA `pos_cash_move_reason` (17.0)

Desarrollo propio de Trixocom (LGPL-3), no es un port del código OCA. Respecto a
aquel: funciona desde la interfaz del POS (OCA sólo desde el backend), no pide
diario (usa el diario de efectivo de la sesión), permite restringir por punto de
venta y exigir motivo, y agrega el reporte.

## Tests

`tests/test_pos_cash_move_reason.py` (asientos, validaciones, cierre de sesión,
wizard, permisos) y `tests/test_frontend.py` (tour del popup en el POS).
