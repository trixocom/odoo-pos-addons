# trx_pos_purchase_receipt — Recepción de mercadería desde el POS

Odoo 19 Community. Autor: Trixocom. Licencia LGPL-3.

## Flujo
1. La orden de compra se carga y confirma en el backend (Compras), con el tipo de operación
   de recepción del depósito del local. Odoo deja la entrada `WH/IN` pendiente.
2. En el POS, botón **Recepciones** (al lado de Órdenes) con el contador de pendientes del
   depósito del punto de venta.
3. Se elige la recepción y se escanea: cada lectura suma 1 unidad. El código se busca en los
   artículos de esa recepción por código de barras, código interno (alfa) o código del
   proveedor de la OC (`product.supplierinfo.product_code`). Un código de otro proveedor se
   acepta solo si identifica un único artículo de la recepción.
4. **Validar recepción**: si falta mercadería se elige "Queda pendiente" (backorder) o
   "No llega más" (se cancela el saldo). Si sobra, se pide confirmación.

## Configuración
- Punto de Venta → Configuración → Ajustes → Inventario: **Recepción de mercadería** y,
  opcional, **Recepción a ciegas**.
- Permisos (Ajustes → Usuarios): "Recibir mercadería en el POS" o "Recibir mercadería y ver
  cantidades pedidas". Los responsables de PdV tienen el segundo.

## Notas técnicas
- API en `stock.picking` (`trx_pos_receipt_*`), ejecutada con `sudo()` tras validar permiso,
  compañía y depósito del punto de venta. Solo entradas con `purchase_id`.
- El avance se guarda en `stock.move.trx_pos_scanned_qty` (unidad del producto).
- En modo ciego el servidor no envía las cantidades pedidas; lo faltante queda pendiente y las
  diferencias se registran en la entrada y en la OC.
- Artículos con lote/serie: se reciben desde el backend.
