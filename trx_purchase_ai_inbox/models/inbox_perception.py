# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
"""Percepciones / retenciones impresas en la factura del proveedor.

No son artículos: van a la factura de proveedor como impuestos (account.tax de compra, importe fijo),
con el importe que dice la factura. Se busca el impuesto por tipo y jurisdicción en el plan de
impuestos de la compañía (l10n_ar los trae todos, muchos archivados): si está archivado se activa,
si no existe se crea copiando el de la misma clase.
"""
import re
import unicodedata

from odoo import _, api, fields, models

KINDS = [
    ("iva", "Percepción IVA"),
    ("ganancias", "Percepción Ganancias"),
    ("iibb", "Percepción IIBB"),
    ("municipal", "Percepción municipal"),
    ("otro", "Otro tributo"),
]

# jurisdicción IIBB → nombre del grupo de impuestos de l10n_ar ("Perc IIBB <x>")
JURISDICTIONS = [
    # CABA antes que Buenos Aires: "Ciudad Autónoma de Buenos Aires" contiene "buenos aires"
    ("CABA", ("caba", "capital", "ciudad", "agip", "c.a.b.a", "ciudad autonoma")),
    ("P. Buenos Aires", ("buenos aires", "bs as", "bs. as", "pba", "pcia", "provincia", "arba", "bsas")),
    ("Córdoba", ("cordoba",)),
    ("Santa Fe", ("santa fe", "api ")),
    ("Mendoza", ("mendoza",)),
    ("Entre Ríos", ("entre rios",)),
    ("Tucumán", ("tucuman",)),
    ("Salta", ("salta",)),
    ("Jujuy", ("jujuy",)),
    ("Corrientes", ("corrientes",)),
    ("Misiones", ("misiones",)),
    ("Chaco", ("chaco",)),
    ("Formosa", ("formosa",)),
    ("Santiago del Estero", ("santiago",)),
    ("Catamarca", ("catamarca",)),
    ("La Rioja", ("la rioja", "rioja")),
    ("San Juan", ("san juan",)),
    ("San Luis", ("san luis",)),
    ("La Pampa", ("la pampa", "pampa")),
    ("Neuquén", ("neuquen",)),
    ("Río Negro", ("rio negro",)),
    ("Chubut", ("chubut",)),
    ("Santa Cruz", ("santa cruz",)),
    ("Tierra del Fuego", ("tierra del fuego", "fuego")),
]


def _norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", text)


def classify(description, kind_hint=None, jurisdiction_hint=None):
    """Devuelve (kind, jurisdiction) a partir del texto impreso (y lo que sugirió la lectura)."""
    txt = _norm("%s %s" % (description or "", jurisdiction_hint or ""))
    kind = kind_hint if kind_hint in dict(KINDS) else None
    if not kind:
        if "iva" in txt.split() or "i.v.a" in txt or "rg 2408" in txt or "rg 3337" in txt:
            kind = "iva"
        elif "ganan" in txt or "benefic" in txt or "rg 830" in txt:
            kind = "ganancias"
        elif "iibb" in txt or "ingresos brutos" in txt or "ing. brutos" in txt or "ing brutos" in txt or "i.i.b.b" in txt or "arba" in txt or "agip" in txt:
            kind = "iibb"
        elif "municip" in txt or "tasa" in txt:
            kind = "municipal"
        else:
            kind = "otro"
    jurisdiction = False
    if kind == "iibb":
        for name, keys in JURISDICTIONS:
            if any(k in txt for k in keys):
                jurisdiction = name
                break
    return kind, jurisdiction


class TrxPurchaseInboxPerception(models.Model):
    _name = "trx.purchase.inbox.perception"
    _description = "Percepción impresa en la factura del proveedor"
    _order = "inbox_id, sequence, id"

    inbox_id = fields.Many2one("trx.purchase.inbox", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="inbox_id.company_id")
    currency_id = fields.Many2one(related="inbox_id.currency_id")
    inbox_state = fields.Selection(related="inbox_id.state")
    sequence = fields.Integer(default=10)
    description = fields.Char(string="Texto impreso", required=True)
    kind = fields.Selection(KINDS, string="Tipo", required=True, default="otro")
    jurisdiction = fields.Char(string="Jurisdicción", help="Provincia para IIBB (tal como la nombra l10n_ar: 'P. Buenos Aires', 'CABA', 'Córdoba'...).")
    jurisdiction_guessed = fields.Boolean(string="Jurisdicción supuesta", readonly=True,
                                          help="La factura no dice la provincia: se tomó la última usada con el proveedor o la del domicilio de la compañía.")
    rate = fields.Float(string="Alícuota %", digits=(16, 4))
    base = fields.Monetary(string="Base impresa", currency_field="currency_id")
    amount = fields.Monetary(string="Importe", currency_field="currency_id", required=True)
    tax_id = fields.Many2one("account.tax", string="Impuesto", domain="[('company_id', '=', company_id), ('type_tax_use', '=', 'purchase')]",
                             context={"active_test": False})
    tax_state = fields.Selection([
        ("found", "Impuesto existente"),
        ("activated", "Impuesto activado"),
        ("created", "Impuesto creado"),
        ("missing", "Sin impuesto"),
    ], string="Impuesto", default="missing", readonly=True)

    @api.onchange("jurisdiction")
    def _onchange_jurisdiction(self):
        for rec in self:
            rec.jurisdiction_guessed = False
            if rec.kind == "iibb":
                rec.tax_id = False
                rec.tax_state = "missing"

    @api.model
    def _guess_jurisdiction(self, partner, company):
        """IIBB sin provincia impresa: la última percepción IIBB cargada a ese proveedor; si no, la provincia
        del domicilio de la compañía (la percepción se practica por la jurisdicción del comprador); si no, la del proveedor."""
        if partner:
            prev = self.search([("inbox_id.partner_id", "=", partner.id), ("kind", "=", "iibb"), ("jurisdiction", "!=", False), ("tax_id", "!=", False)],
                               order="id desc", limit=1)
            if prev:
                return prev.jurisdiction, _("última usada con %s", partner.name)
        for rec, why in ((company.partner_id, _("domicilio de %s", company.name)), (partner, _("domicilio del proveedor"))):
            if rec and rec.state_id and (rec.state_id.country_id.code or "AR") == "AR":
                _kind, jur = classify("IIBB " + rec.state_id.name)
                if jur:
                    return jur, why
        return False, ""

    @api.onchange("tax_id")
    def _onchange_tax_id(self):
        for rec in self:
            if rec.tax_id and rec.tax_state == "missing":
                rec.tax_state = "found"

    # ------------------------------------------------------------ impuestos
    # código AFIP del tributo en el grupo de impuestos de l10n_ar
    AFIP_TRIBUTE_CODE = {"iva": "06", "ganancias": "09", "iibb": "07", "municipal": "08", "otro": "09"}

    def _names(self, record):
        """Nombre normalizado del registro en todos los idiomas instalados (el plan viene en inglés y traducido)."""
        langs = {code for code, _n in self.env["res.lang"].get_installed()} | {"en_US"}
        return {_norm(record.with_context(lang=lang).name) for lang in langs}

    def _find_group(self):
        """Grupo de impuestos de l10n_ar de esta percepción: por código AFIP del tributo y, dentro de él, por nombre."""
        self.ensure_one()
        Group = self.env["account.tax.group"].with_context(active_test=False)
        groups = Group.search([("company_id", "=", self.company_id.id), ("l10n_ar_tribute_afip_code", "=", self.AFIP_TRIBUTE_CODE[self.kind])])
        if self.kind == "iibb":
            j = _norm(self.jurisdiction)
            groups = groups.filtered(lambda g: j and any(j in n for n in self._names(g)))
        elif self.kind == "ganancias":
            groups = groups.filtered(lambda g: any("benefic" in n or "ganan" in n or "profit" in n for n in self._names(g)))
        elif self.kind == "otro":
            groups = groups.filtered(lambda g: any("otra" in n or "other" in n for n in self._names(g))) or groups
        return groups[:1]

    def _tax_domain(self):
        return [("company_id", "=", self.company_id.id), ("type_tax_use", "=", "purchase")]

    def _find_tax(self):
        """Impuesto de compra (activo o archivado) del grupo que corresponde; preferimos los de importe fijo
        (los de l10n_ar para compras): el importe se carga desde la factura."""
        self.ensure_one()
        Tax = self.env["account.tax"].with_context(active_test=False)
        group = self._find_group()
        taxes = Tax.search(self._tax_domain() + [("tax_group_id", "=", group.id)], order="active desc, id") if group else Tax
        fixed = taxes.filtered(lambda t: t.amount_type == "fixed")
        return (fixed or taxes)[:1], group

    def _template_tax(self):
        """Impuesto de percepción de compra para copiar cuando no existe (p. ej. IIBB de otra provincia)."""
        self.ensure_one()
        Tax = self.env["account.tax"].with_context(active_test=False)
        code = self.AFIP_TRIBUTE_CODE[self.kind]
        for codes in ([code], ["07", "06", "09", "08"]):
            tax = Tax.search(self._tax_domain() + [("amount_type", "=", "fixed"), ("tax_group_id.l10n_ar_tribute_afip_code", "in", codes)], order="active desc, id", limit=1)
            if tax:
                return tax
        return Tax

    def _ensure_tax_config(self, tax):
        """Las percepciones de compra nunca van incluidas en el precio: si el impuesto hereda 'incluido' de la
        compañía (configuración de ventas), se lo fija como excluido para que no descuente base."""
        if tax and tax.price_include_override != "tax_excluded":
            tax.price_include_override = "tax_excluded"

    def action_resolve_tax(self):
        """Impuesto existente → se usa; archivado → se activa; inexistente → se crea copiando uno de la misma clase."""
        for rec in self:
            rec._action_resolve_tax_one()
            rec._ensure_tax_config(rec.tax_id)
        return True

    def _action_resolve_tax_one(self):
        for rec in self:
            if rec.tax_id:
                if not rec.tax_id.active:
                    rec.tax_id.active = True
                    rec.tax_state = "activated"
                elif rec.tax_state == "missing":
                    rec.tax_state = "found"
                continue
            tax, group = rec._find_tax()
            if tax:
                if not tax.active:
                    tax.active = True
                    rec.write({"tax_id": tax.id, "tax_state": "activated"})
                else:
                    rec.write({"tax_id": tax.id, "tax_state": "found"})
                continue
            template = rec._template_tax()
            if not template or (rec.kind == "iibb" and not rec.jurisdiction):
                rec.tax_state = "missing"
                continue
            label = dict(KINDS)[rec.kind] + (" %s" % rec.jurisdiction if rec.jurisdiction else "")
            if not group:
                group = self.env["account.tax.group"].create({
                    "name": label, "company_id": rec.company_id.id, "l10n_ar_tribute_afip_code": rec.AFIP_TRIBUTE_CODE[rec.kind],
                })
            vals = {"name": label, "description": label, "invoice_label": label, "active": True, "amount_type": "fixed", "amount": 1.0,
                    "tax_group_id": group.id, "price_include_override": "tax_excluded"}
            tax = template.copy(vals)
            rec.write({"tax_id": tax.id, "tax_state": "created"})
