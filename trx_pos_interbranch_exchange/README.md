# trx_pos_interbranch_exchange — Cambio inter-sucursal (multi-compañía)

Odoo 19 Community. Autor: Trixocom.

Permite tomar en cualquier sucursal el cambio de un producto vendido en otra
sucursal, aunque la venta original sea de **otra compañía (CUIT)**.

## Flujo
1. En el POS que recibe (compañía **B**), el cajero elige el medio de pago
   **Cambio inter-sucursal** y escanea/tipea el código del ticket de cambio
   (uuid del `pos.order`, número de recibo `00001-001-0001` o número de orden).
2. El servidor busca la venta original en todas las compañías y evalúa cada
   línea: categoría con el tilde *Acepta cambios inter-sucursal* (u override
   por producto), plazo en días de la compañía que recibe, cantidad ya
   devuelta/cambiada.
3. El cajero elige productos y cantidades. El importe (PVP con IVA de la venta
   original) queda como pago de la venta nueva. Regla por defecto: la compra
   nueva debe ser de igual o mayor valor (configurable: devolver diferencia en
   efectivo).
4. Al confirmar la venta nueva, **en la misma transacción** el servidor:
   - emite la **NC en la compañía A** (fiscal con CAE y comprobante asociado
     vía `account.move.reversal` si la venta fue facturada; NC interna en un
     diario de ventas sin documentos si fue NF);
   - asienta en A la **compensación**: Dr Deudores (cliente) / Cr *Cuenta
     corriente cambios inter-sucursal* (partner = compañía B) y la concilia con
     la NC → el cliente queda en cero en A y **A le debe a B** el importe;
   - ingresa la mercadería al **depósito de B** (devolución de cliente, al
     costo de B);
   - en B, el pago se contabiliza al cierre de sesión en la misma cuenta
     corriente (cuenta *outstanding* del medio de pago) → **B tiene a cobrar de A**.
5. El cajero solo necesita el grupo **POS: cambio inter-sucursal**. Lo de A lo
   ejecuta el servidor (`sudo` + `with_company`). Todo queda en
   *Punto de Venta → Cambios inter-sucursal* (lista, formulario, pivot).

## Contabilidad (resumen)
| Compañía | Documento | Débito | Crédito |
|---|---|---|---|
| A (vendió) | NC (fiscal o NF) | Ventas / IVA | Deudores (cliente) |
| A | Reembolso de la NC: `account.payment` saliente en el diario IBXP, conciliado con la NC | Deudores (cliente) | Cta cte inter-sucursal |
| B (recibe) | Cierre de sesión POS (medio de pago con outstanding = cta cte) | Cta cte inter-sucursal | Deudores POS |
| B | Ingreso de stock (devolución de cliente) | (valoración: stock +costo) | — |

Por qué un pago y no un asiento manual: la NC queda **conciliada y en estado
"en proceso de pago"** (pasa a "pagada" cuando la línea de la cta cte se
concilia con la compensación entre CUIT), el cliente queda en cero en A y el
importe se ve como un reembolso al cliente, que es lo que ocurrió: A devolvió
el dinero por intermedio de B. Con `account_payment_pro` (ADHOC) instalado, el
pago se crea con las líneas de la NC como "deudas a pagar" explícitas, para que
no autocomplete con otras deudas abiertas del partner (Consumidor Final).

Saldo neto: A acreedora / B deudora por el PVP del cambio. La mercadería queda
en B sin contrapartida contable automática; el pivot informa PVP y costo por
par de compañías para la **compensación periódica** que defina el estudio
contable (factura/NC entre CUIT o compensación de saldos). Esa compensación
NO la hace el módulo (v1).

## Configuración
Por cada razón social (compañía raíz): *Punto de Venta → Ajustes → Cambio
inter-sucursal → Crear cuentas, diarios y medio de pago*. Crea (idempotente):
- cuenta `1.1.3.99.001` *Cambios inter-sucursal - cuenta corriente* (activo
  corriente, conciliable) y `1.1.1.99.001` transitoria (caja/banco, exigida por
  el diario tipo banco);
- diarios `IBXA` (varios, ajustes), `IBXB` (banco, medio de pago POS) e `IBXP`
  (banco, reembolsos de NC; separado de IBXB para que cierres de sesión y pagos
  no compartan numeración: con talonarios de recibo ADHOC colisionaban); los
  tres compartidos con las sucursales (`shared_to_branches`);
- un medio de pago *Cambio inter-sucursal* por local (raíz y cada sucursal;
  terminal `interbranch_exchange`, outstanding = cta cte de la raíz, sin
  "identificar cliente") y lo agrega a todos los POS de ese local; las líneas
  de método de pago de IBXB e IBXP apuntan a la cta cte.

**Compañías y sucursales (desde 19.0.1.1.0)**: cada CUIT es una compañía
**raíz** (sin `parent_id`); los demás locales de esa razón social son
compañías con `parent_id` = la raíz (*sucursales* de Odoo 17+: comparten plan
de cuentas, impuestos e identidad fiscal). La configuración del módulo
(cuentas, diarios, plazo, diferencia en efectivo) es por razón social: se
define en la raíz y las sucursales la heredan (campos delegados, readonly en
la sucursal). "Mismo CUIT" se decide por `root_id`: un cambio entre dos
locales del mismo CUIT genera igual la NC en el local que vendió (su diario /
punto de venta) y el ingreso de stock en el que recibe; la compensación y el
cobro POS caen ambos en la cta cte de la misma razón social, así que a nivel
CUIT queda en cero y sólo refleja el traspaso entre locales. Sólo entre CUIT
distintos queda un saldo a compensar.

Además: plazo máximo en días, diario para NC de ventas NF (si el diario del
POS usa documentos), y el tilde en las categorías de producto.

## Ticket de cambio
Reporte PDF 80mm sobre `pos.order` (botón *Ticket de cambio* y menú Imprimir):
sin precios, con código de barras Code128 del uuid.

## Supuestos v1 (a validar con el cliente)
- Solo productos almacenables. Cantidad disponible = vendida − devuelta − ya cambiada.
- El PVP del cambio es el de la venta original (con IVA), no el actual.
- La compra nueva debe ser ≥ al cambio (sin vuelto), salvo configuración.
- Devoluciones en la misma compañía también pasan por acá (mismo circuito;
  la cuenta corriente queda en cero por sí sola).
- Los preparados que no se confirman en 12 h se cancelan (cron).

## Probado (st_giro, 21-09-2026)
Venta NF en DIDACTICA (Belgrano) → cambio de 1 unidad tomado en "DEMO Franquicia
Palermo SRL" (otro CUIT) vía `pos.order.sync_from_ui`: NC `RPDEMO/26-27/0001`
posteada por 21.780 en Didáctica, reembolso `RE-X 0001-00000003` en IBXB (v1.0.x; desde 1.1.0 en IBXP)
conciliado (NC en proceso de pago), cta cte Didáctica −21.780, stock franquicia
3 → 4, cta cte franquicia +21.780 al cerrar la sesión. Scripts:
`Girodidactico/demo_compras/08_demo_compania2.py` y `09_probar_cambio_intersucursal.py`.
El flujo fiscal (NC con CAE) sigue la receta del wizard `account.move.reversal`
usada por `pos_promotions`; no se pudo probar contra AFIP en test (sin
certificado).
