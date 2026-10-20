# Part of trx_supplier_pricelist_revision. Author: Trixocom. License: LGPL-3.
import re
import unicodedata

from odoo import _, api, fields, models
from odoo.exceptions import UserError

PVP_RULES = [
    ("list_factor", "Factor sobre precio de lista del proveedor"),
    ("cost_factor", "Factor sobre costo neto (con descuento)"),
    ("suggested", "PVP sugerido por el proveedor"),
    ("margin", "Margen del artículo (precio planificado de Odoo)"),
    ("keep", "Mantener el PVP actual"),
]

PVP_ROUNDINGS = [
    ("0", "Sin redondeo"),
    ("1", "A la unidad"),
    ("10", "A la decena"),
    ("50", "A 50"),
    ("100", "A la centena"),
]


class ResPartner(models.Model):
    _inherit = "res.partner"

    trx_pricelist_discount = fields.Float(
        string="Descuento de lista %", digits="Discount",
        help="Bonificación que el proveedor aplica sobre su precio de lista. Costo neto = lista × (1 − %).",
    )
    trx_pvp_rule = fields.Selection(PVP_RULES, string="Regla de PVP", default="list_factor",
                                    help="Cómo se propone el PVP al cargar una lista de este proveedor.")
    trx_pvp_factor = fields.Float(string="Factor de PVP", default=2.0, digits=(16, 4),
                                  help="Para las reglas por factor: PVP = base × factor (p. ej. 2,1).")
    trx_pvp_rounding = fields.Selection(PVP_ROUNDINGS, string="Redondeo del PVP", default="1")
    trx_alfa_prefix = fields.Char(string="Prefijo de código alfa", size=8,
                                  help="Prefijo de los códigos alfa de los artículos nuevos de este proveedor "
                                       "(p. ej. DER). Si está vacío se usan las 3 primeras letras del nombre.")
    trx_alfa_next = fields.Integer(string="Próximo número de alfa", default=1,
                                   help="Correlativo que se usará para el próximo artículo nuevo.")
    trx_alfa_padding = fields.Integer(string="Dígitos del correlativo", default=0,
                                      help="0 = sin ceros adelante (DER556). 4 = DER0556.")
    trx_revision_ids = fields.One2many("trx.supplier.pricelist.revision", "partner_id", string="Listas de proveedor")
    trx_revision_count = fields.Integer(compute="_compute_trx_revision_count")

    def _compute_trx_revision_count(self):
        groups = self.env["trx.supplier.pricelist.revision"]._read_group(
            [("partner_id", "in", self.ids)], groupby=["partner_id"], aggregates=["__count"]
        )
        counts = {partner.id: count for partner, count in groups}
        for rec in self:
            rec.trx_revision_count = counts.get(rec.id, 0)

    def _trx_default_alfa_prefix(self):
        self.ensure_one()
        name = unicodedata.normalize("NFKD", self.name or "")
        name = "".join(ch for ch in name if not unicodedata.combining(ch))
        letters = re.sub(r"[^A-Za-z]", "", name).upper()
        return letters[:3]

    def _trx_next_alfa(self):
        """Devuelve el próximo código alfa libre (prefijo + correlativo, sin guion) y avanza el contador."""
        self.ensure_one()
        prefix = (self.trx_alfa_prefix or "").strip().upper() or self._trx_default_alfa_prefix()
        if not prefix:
            raise UserError(_("El proveedor %s no tiene prefijo de código alfa.", self.display_name))
        Tmpl = self.env["product.template"].with_context(active_test=False)
        n = max(self.trx_alfa_next or 1, 1)
        for _i in range(100000):
            code = "%s%s" % (prefix, str(n).zfill(self.trx_alfa_padding or 0))
            if not Tmpl.search_count([("default_code", "=", code)]):
                break
            n += 1
        self.sudo().write({"trx_alfa_prefix": prefix, "trx_alfa_next": n + 1})
        return code

    def action_view_trx_revisions(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "trx_supplier_pricelist_revision.action_trx_supplier_pricelist_revision"
        )
        action["domain"] = [("partner_id", "=", self.id)]
        action["context"] = {"default_partner_id": self.id, "search_default_partner_id": self.id}
        return action

    def action_new_trx_revision(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Subir lista de proveedor"),
            "res_model": "trx.supplier.pricelist.revision",
            "view_mode": "form",
            "target": "current",
            "context": {"default_partner_id": self.id},
        }
