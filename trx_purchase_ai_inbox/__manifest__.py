{
    "name": "Compras - Facturas de proveedor escaneadas con IA",
    "version": "19.0.1.1.0",
    "category": "Inventory/Purchase",
    "summary": "Sube la factura del proveedor (PDF o foto), la lee con Claude, reconoce los artículos "
    "(EAN → código del proveedor → alfa), calcula el costo neto real y arma la orden de compra.",
    "description": """
Facturas de proveedor escaneadas
================================

Compras → Pedidos → Facturas recibidas (IA).

* **Entrada**: PDF o foto de la factura, para la razón social que compra (se detecta por el
  CUIT receptor si está impreso).
* **Lectura**: Claude (API de Anthropic) devuelve un esquema con cabecera (CUIT emisor y
  receptor, tipo y número, fecha, CAE, totales), líneas (código del proveedor, EAN13 si está
  impreso, descripción, cantidad, precio, descuento de línea, IVA), descuentos globales al pie,
  otros cargos y percepciones. Nada se inventa: lo que no está impreso queda vacío.
* **Costo neto real por unidad**: precio impreso − descuento de línea − descuento global
  prorrateado. Es el que va a la OC, a la línea de proveedor del artículo y a la comparación
  con el último costo (aviso si subió).
* **Control**: el CUIT emisor no puede ser de una razón social de la red; la suma de líneas
  netas + IVA + percepciones tiene que cerrar con el total impreso (si no, queda a revisar).
* **Reconocimiento del artículo**: EAN → código del proveedor → código alfa → descripción
  (sólo sugerido). Los no reconocidos se incorporan con un clic (alfa automático del proveedor).
* **Orden de compra**: líneas al costo neto con el IVA de la factura, referencia = tipo y
  número; se confirma sola cuando todo coincide y los totales cierran (la recepción aparece en
  la caja); si no, queda en borrador con una actividad a Compras.

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": ["purchase", "account", "l10n_ar", "mail", "trx_product_price_history", "trx_supplier_pricelist_revision"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "data/data.xml",
        "views/inbox_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
