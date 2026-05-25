{
    "name": "POS Financial Surcharge",
    "version": "19.0.1.2.0",
    "category": "Sales/Point of Sale",
    "sequence": 6,
    "summary": "Recargo o descuento financiero por forma de pago en POS",
    "description": """
Permite cobrar un recargo (o aplicar un descuento) sobre el importe del POS
en función del plan de cuotas elegido al cobrar con tarjeta.

Basado en `card_installment` (ADHOC). Cuando el cajero selecciona el método
de pago de tipo 'Card financial surcharge' se abre un popup con los planes
disponibles para la tarjeta y, según el coeficiente de cada plan, se inserta
una orderline extra con el delta (positivo = recargo, negativo = descuento)
ajustando el monto del payment line para que la orden cierre.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "card_installment",
    ],
    "data": [
        "views/card_installment_view.xml",
        "views/pos_payment_method.xml",
        "wizards/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_financial_surcharge/static/src/**/*",
        ],
    },
    "installable": True,
}
