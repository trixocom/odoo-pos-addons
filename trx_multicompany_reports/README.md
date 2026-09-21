# trx_multicompany_reports — Reportes por razón social (CUIT)

Red de locales con varias razones sociales: cada CUIT es una compañía Odoo
**raíz** y los demás locales de esa razón social son **sucursales** (compañías
con `parent_id`). La casa matriz tiene todas las compañías habilitadas y
necesita ver la información agrupada por CUIT además de por local. En Odoo la
compañía raíz (`res.company.root_id`) no es un campo almacenado, así que no se
puede agrupar ni filtrar por ella en pivots.

## Qué agrega
- Campo almacenado e indexado **Razón social (CUIT)** (`trx_root_company_id`
  = `company_id.root_id`, mixin `trx.root.company.mixin`) en `pos.order`,
  `pos.order.line`, `pos.payment`, `account.move`, `account.move.line`,
  `account.payment`, `stock.picking`, `stock.move` y `stock.quant`. La
  jerarquía de compañías no puede cambiar (base lo prohíbe), así que
  almacenarlo es seguro.
- Agrupación "Razón social (CUIT)" y "Local (compañía)" en las búsquedas de
  órdenes POS, facturas, stock (quants), *Análisis de ventas POS*
  (`report.pos.order`) y *Análisis de facturas* (`account.invoice.report`);
  filtro "Mi razón social".
- Vista SQL **Ventas por razón social y local** (`trx.mc.sales.report`, menú
  *Punto de Venta → Informes*): ventas POS confirmadas (paid/done/invoiced) +
  facturas y NC de clientes posteadas que **no** provienen del POS (se
  excluyen las `account.move` referenciadas por `pos_order.account_move` para
  no contar dos veces). Columnas: fecha (día, en la zona horaria de la
  compañía), origen, razón social, local, punto de venta, diario, cliente,
  vendedor, producto, categoría, cantidad, neto, total con impuestos, costo
  (`total_cost` de la línea POS; cantidad × costo estándar de la compañía en
  facturas) y margen. Pivot por defecto: razón social → local × mes.

## Notas
- Importes en moneda de la compañía, sin conversión (la red opera en ARS).
- Regla multi-compañía sobre `company_id`: cada usuario ve los locales que
  tiene habilitados; la casa matriz, con todas las compañías seleccionadas,
  ve la red completa.
- Base para el cruce mensual de ventas por franquicia contra los informes de
  los proveedores (comisiones): agrupar por razón social y categoría/producto
  en el mes.

Autor: Trixocom. Licencia LGPL-3.
