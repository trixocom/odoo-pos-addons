# trx_supplier_pricelist_revision

Listas de proveedor / Revisión de precios programada — Odoo 19 CE (Trixocom).

Menú: **Compras → Productos → Listas de proveedor**. También desde la ficha del proveedor
(pestaña "Listas de precios y códigos" → "Subir lista de precios").

## Flujo

1. **Nueva lista**: proveedor + archivo original (xlsx / xls / csv) + fecha de recepción.
   Las reglas (descuento, regla de PVP, factor, redondeo) se precargan desde el proveedor.
2. **Cargar líneas del archivo**: el lector busca la hoja y la fila de encabezados con
   columnas reconocibles (código, detalle, precio de lista, bonificación, código de barras,
   PVP sugerido; ver `file_parser.SYNONYMS`) y arma las líneas. Después:
   * reconoce el artículo: **código de barras → código del proveedor → código alfa →
     nombre (sólo "sugerido")**; dos líneas al mismo artículo → la segunda queda "sin resolver";
   * toma **costo actual** (precio neto vigente con ese proveedor) y **PVP actual**;
   * propone el **PVP** según la regla y marca la decisión: subió → *Aplicar costo y PVP*;
     bajó → *Aplicar costo, mantener PVP* (si la política lo dice); nuevo → *No incorporar*.
3. **Revisión**: grilla editable (costo actual / nuevo / %, PVP actual / propuesto / % /
   anterior), botones de estadística que abren las líneas filtradas (Subieron, Bajaron,
   Iguales, Nuevos, A confirmar, Sin PVP) con edición masiva y acciones: Aplicar / Mantener
   PVP / No incorporar / Bajar el PVP / Recalcular PVP / Incorporar / Confirmar sugerido.
4. **Programar** (fecha y hora; vacío = mañana 00:00) o **Aplicar ahora**.
5. **Aplicación** (cron `ir_cron_apply_scheduled`, disparado a la hora exacta con
   `_trigger(at=...)` y de respaldo cada 15 min):
   * línea de proveedor del artículo: `price` = precio de lista, `discount` = 0,
     `replenishment_cost_rule_id` = regla ADHOC "Descuento de lista X %" (→ `net_price`
     = costo neto = costo de reposición), `product_code`, `product_name`, `date_start`;
   * si el artículo tenía costo de reposición "manual" en 0 → pasa a "precio del proveedor";
   * PVP (`list_price`) si la decisión es *Aplicar* y el propuesto es > 0;
   * todo queda en el historial (`trx_product_price_history`) con origen "Revisión de lista"
     y la referencia del documento.

## Incorporar (artículos nuevos)

Las líneas no reconocidas quedan como **catálogo del proveedor** dentro del documento.
"Incorporar" crea el artículo: código alfa = **prefijo del proveedor + correlativo, sin
guion** (`DER556`; prefijo por defecto = 3 primeras letras del nombre; correlativo y ceros
configurables en el proveedor), código de barras si es válido y no está usado, PVP
propuesto, línea de proveedor con precio y regla de descuento.

## Decisiones de diseño (v0, 19-10-2026)

* La línea de proveedor se **actualiza en el lugar** (no se versiona con `date_end`):
  `_compute_supplier_data` de ADHOC toma la primera línea por `sequence`/precio sin mirar
  vigencias, así que una línea vieja vigente podría quedar como costo. La historia la da
  `trx_product_price_history`.
* Descuento del proveedor por **regla de costo de reposición**, no por `discount` del core:
  el precio de la OC usa `net_price` (override ADHOC) y con ambos se descontaría dos veces.
* Sin IA todavía: el lector cubre Excel/CSV con encabezados; PDF/foto llega con el agente.

Autor: Trixocom. Licencia: LGPL-3.
