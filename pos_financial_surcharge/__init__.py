from . import models
from . import wizards


def _post_init_hook(env):
    """
    Cleanup automático en cada install/update:

    1. Borra el menú duplicado de "Cuotas" que card_installment crea bajo
       "Pagos en línea". Antes la teníamos también nosotros bajo el POS y
       generaba ruido; ahora apuntamos al de Tarjetas/Promociones con el
       inline de planes.
    2. Asegura que el menú propio (Punto de Venta -> Configuración ->
       Planes de cuotas) y la acción referenciada se llamen "Planes de
       cuotas" en ambos idiomas, sobrescribiendo el name del JSONB que
       Odoo no actualiza si ya existía.

    Es idempotente: si los registros ya están como queremos, no hace nada.
    """
    # 1. Borrar duplicado de cuotas si todavía existe.
    dup = env.ref(
        "pos_financial_surcharge.menu_account_financial_plans",
        raise_if_not_found=False,
    )
    if dup:
        dup.unlink()

    # 2. Forzar nombre del menú propio y de la acción upstream.
    menu = env.ref(
        "pos_financial_surcharge.menu_account_card", raise_if_not_found=False
    )
    if menu:
        menu.with_context(lang="en_US").write({"name": "Card plans"})
        menu.with_context(lang="es_AR").write({"name": "Planes de cuotas"})

    action = env.ref("card_installment.action_account_card", raise_if_not_found=False)
    if action:
        action.with_context(lang="en_US").write({"name": "Card plans"})
        action.with_context(lang="es_AR").write({"name": "Planes de cuotas"})
