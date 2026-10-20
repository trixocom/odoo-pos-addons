{
    "name": "Bandeja de comprobantes - entrada por WhatsApp",
    "version": "19.0.1.0.0",
    "category": "Inventory/Purchase",
    "summary": "Los PDF, fotos y Word que llegan a los números de WhatsApp habilitados entran a la bandeja de "
    "comprobantes de proveedor y se leen con IA, igual que si se subieran a mano.",
    "description": """
Entrada por WhatsApp para la bandeja de comprobantes
=====================================================

En cada número / cuenta de WhatsApp: tilde "Leer comprobantes de proveedor". Cada documento (PDF, foto o
Word) que llegue a ese número crea un registro en Compras → Órdenes → Bandeja de comprobantes con origen
WhatsApp y el número y nombre de quien lo mandó. El mensaje sigue llegando al chat como siempre.

Autor: Trixocom.
""",
    "author": "Trixocom",
    "website": "https://www.trixocom.com",
    "license": "LGPL-3",
    "depends": ["trx_purchase_ai_inbox", "trixo_whatsapp"],
    "data": ["views/whatsapp_account_views.xml", "views/inbox_views.xml"],
    "auto_install": True,
    "installable": True,
    "application": False,
}
