from . import models
from . import wizards


def _active_langs(env):
    """Códigos de idioma ACTIVOS en la base."""
    return set(
        env["res.lang"]
        .with_context(active_test=False)
        .search([("active", "=", True)])
        .mapped("code")
    )


def _write_name(record, env, translations, active_langs):
    """Escribe el `name` solo en los idiomas que estén activos.

    Escribir con `with_context(lang=...)` sobre un idioma NO activo revienta con
    `UserError: Invalid language code: xx_XX` y aborta la instalación del módulo.
    Ese era el caso en bases que usan es_419 (Español LATAM) y no tienen es_AR.
    """
    if not record:
        return
    for lang, value in translations.items():
        if lang in active_langs:
            record.with_context(lang=lang).write({"name": value})


def _post_init_hook(env):
    """
    Cleanup automático en cada install/update:

    1. Borra el menú duplicado de "Cuotas" que card_installment crea bajo
       "Pagos en línea".
    2. Asegura que el menú propio (Punto de Venta -> Configuración ->
       Planes de cuotas) y la acción referenciada se llamen "Planes de
       cuotas" en los idiomas activos.

    Es idempotente y tolerante al set de idiomas instalado.
    """
    # 1. Borrar duplicado de cuotas si todavía existe.
    dup = env.ref(
        "pos_financial_surcharge.menu_account_financial_plans",
        raise_if_not_found=False,
    )
    if dup:
        dup.unlink()

    # 2. Forzar nombre del menú propio y de la acción upstream, solo en los
    #    idiomas activos de la base.
    active_langs = _active_langs(env)
    translations = {
        "en_US": "Card plans",
        "es_AR": "Planes de cuotas",
        "es_419": "Planes de cuotas",
        "es_ES": "Planes de cuotas",
    }

    menu = env.ref(
        "pos_financial_surcharge.menu_account_card", raise_if_not_found=False
    )
    _write_name(menu, env, translations, active_langs)

    action = env.ref("card_installment.action_account_card", raise_if_not_found=False)
    _write_name(action, env, translations, active_langs)
