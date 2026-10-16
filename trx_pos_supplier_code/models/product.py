from odoo import api, fields, models
from odoo.fields import Domain

POSITIVE_OPS = ("ilike", "=ilike", "like", "=like", "=")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    trx_supplier_codes = fields.Char(
        string="Códigos de proveedor",
        compute="_compute_trx_supplier_codes",
        store=True,
        index="trigram",
        help="Códigos de artículo de todos los proveedores del producto (para buscar en el POS y en los listados).",
    )

    @api.depends("seller_ids.product_code", "seller_ids.product_id")
    def _compute_trx_supplier_codes(self):
        for tmpl in self:
            codes = []
            for code in tmpl.seller_ids.mapped("product_code"):
                code = (code or "").strip()
                if code and code not in codes and code != tmpl.default_code:
                    codes.append(code)
            tmpl.trx_supplier_codes = " ".join(codes) or False

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["trx_supplier_codes"]

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if value and isinstance(value, str) and operator in POSITIVE_OPS:
            domain = Domain.OR([Domain("trx_supplier_codes", "ilike", value), Domain(domain)])
        return domain


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if value and isinstance(value, str) and operator in POSITIVE_OPS:
            domain = Domain.OR([Domain("product_tmpl_id.trx_supplier_codes", "ilike", value), Domain(domain)])
        return domain

    @api.model
    def name_search(self, name="", domain=None, operator="ilike", limit=100):
        """Completa la búsqueda del core (campos Producto de OC, facturas, pedidos, etc.)
        con los códigos de proveedor.

        El core solo mira los códigos de proveedor cuando hay un proveedor en el
        contexto, y recién si el código alfa, el EAN y el nombre no dieron nada.
        Acá:

        * Con proveedor en contexto: la coincidencia EXACTA con un código de ESE
          proveedor va primero (un código numérico corto también puede aparecer
          en el nombre de otros artículos).
        * Siempre, con o sin proveedor: después de los resultados del core se
          agregan los artículos cuyo código de CUALQUIER proveedor coincide, para
          que se pueda buscar por el código sin saber de qué proveedor es.
        """
        res = super().name_search(name, domain, operator, limit)
        if not name or not isinstance(name, str) or operator not in POSITIVE_OPS:
            return res
        base_domain = Domain(domain or Domain.TRUE)
        partner_id = self.env.context.get("partner_id")
        first = self.browse()
        if partner_id:
            exact_domain = Domain(
                "product_tmpl_id.seller_ids",
                "any",
                Domain([("partner_id", "=", partner_id), ("product_code", "=ilike", name.strip())]),
            )
            first = self.search_fetch(base_domain & exact_domain, ["display_name"], limit=limit)
        exclude = set(first.ids) | {r[0] for r in res}
        rest_limit = (limit - len(exclude)) if limit else None
        extra = self.browse()
        if rest_limit is None or rest_limit > 0:
            codes_op = "ilike" if operator in ("=", "=ilike") else operator
            extra_domain = Domain("product_tmpl_id.trx_supplier_codes", codes_op, name.strip())
            if exclude:
                extra_domain &= Domain("id", "not in", list(exclude))
            extra = self.search_fetch(base_domain & extra_domain, ["display_name"], limit=rest_limit)
        if not first and not extra:
            return res
        first_ids = set(first.ids)
        result = [(p.id, p.display_name) for p in first.sudo()]
        result += [r for r in res if r[0] not in first_ids]
        result += [(p.id, p.display_name) for p in extra.sudo()]
        return result[:limit] if limit else result
