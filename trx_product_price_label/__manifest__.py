{
    "name": "Etiquetas de precio (térmica y hoja A4)",
    "version": "19.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Etiquetas de precio de góndola/producto con código de barras, código interno, "
    "precio final y 'Precio sin impuestos nacionales' (Res. SIC 4/2025).",
    "description": """
Agrega dos formatos al asistente estándar **Imprimir etiquetas** de Odoo (producto, lista de
productos y recepciones, con "Cantidades de la operación"):

* **Etiqueta térmica 50 x 25 mm**: una etiqueta por página, para impresoras de rollo
  (Zebra, Argox, 3nStar, etc.) instaladas en la PC con su driver.
* **Hoja A4 3 x 8 (70 x 37 mm)**: 24 etiquetas autoadhesivas por hoja, para impresora común.

Contenido: nombre del artículo, código interno (alfa), precio final (con IVA, según la lista
de precios elegida o el precio de venta) en grande, "Precio sin impuestos nacionales" en
caracteres menores y código de barras (EAN-13 si es válido, si no Code128).

Los tamaños se ajustan en Ajustes → Técnico → Formatos de papel si el rollo es otro.

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": ["product", "stock"],
    "data": [
        "report/price_label_reports.xml",
        "report/price_label_templates.xml",
    ],
    "installable": True,
    "application": False,
}
