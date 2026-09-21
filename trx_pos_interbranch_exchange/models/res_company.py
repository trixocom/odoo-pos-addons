# Part of trx_pos_interbranch_exchange. Author: Trixocom. License: LGPL-3.
from odoo import _, api, fields, models
from odoo.exceptions import UserError

CTA_CTE_CODE = "1.1.3.99.001"
TRANSIT_CODE = "1.1.1.99.001"


class ResCompany(models.Model):
    _inherit = "res.company"

    trx_ibx_account_id = fields.Many2one(
        "account.account",
        string="Cuenta corriente cambios inter-sucursal",
        help="Cuenta (activo corriente, conciliable) donde queda el saldo entre "
        "compañías por cambios inter-sucursal. En la compañía que VENDIÓ queda "
        "acreedora (le debe a la que recibió el cambio); en la que RECIBE queda "
        "deudora (tiene a cobrar).",
    )
    trx_ibx_transit_account_id = fields.Many2one(
        "account.account",
        string="Cuenta transitoria del diario de cobros inter-sucursal",
        help="Cuenta por defecto del diario tipo banco que usa el medio de pago "
        "'Cambio inter-sucursal'. Odoo exige que sea de tipo caja/banco; el "
        "importe real se contabiliza en la cuenta corriente vía la cuenta "
        "pendiente (outstanding) del medio de pago.",
    )
    trx_ibx_journal_id = fields.Many2one(
        "account.journal",
        string="Diario de ajustes inter-sucursal",
        help="Diario (varios) donde se asienta, en la compañía que vendió, la "
        "compensación de la NC contra la cuenta corriente inter-sucursal.",
    )
    trx_ibx_bank_journal_id = fields.Many2one(
        "account.journal",
        string="Diario de cobros inter-sucursal",
        help="Diario tipo banco del medio de pago 'Cambio inter-sucursal'.",
    )
    trx_ibx_payment_method_id = fields.Many2one(
        "pos.payment.method",
        string="Medio de pago 'Cambio inter-sucursal'",
    )
    trx_ibx_nf_journal_id = fields.Many2one(
        "account.journal",
        string="Diario para NC de ventas no fiscales (NF)",
        domain="[('type', '=', 'sale'), ('company_id', '=', id)]",
        help="Diario de ventas SIN documentos fiscales donde se emite la NC cuando "
        "la venta original no fue facturada. Si está vacío se usa el diario del "
        "POS que hizo la venta original.",
    )
    trx_ibx_days_limit = fields.Integer(
        string="Plazo máximo para cambios (días)",
        default=30,
        help="Días desde la venta original dentro de los cuales se acepta el cambio. "
        "0 = sin límite. Se evalúa con el plazo de la compañía que RECIBE el cambio.",
    )
    trx_ibx_allow_cash_difference = fields.Boolean(
        string="Permitir devolver diferencia en efectivo",
        default=False,
        help="Si el importe del cambio supera la compra nueva, permitir que el POS "
        "devuelva la diferencia como vuelto. Si no, la compra nueva debe ser de "
        "igual o mayor valor.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + [
            "trx_ibx_allow_cash_difference",
            "trx_ibx_days_limit",
        ]

    def _trx_ibx_get_or_create_account(self, code, name, account_type, reconcile):
        self.ensure_one()
        Account = self.env["account.account"].with_company(self)
        account = Account.search(
            [("company_ids", "in", self.id), ("code", "=", code)], limit=1
        )
        if account:
            return account
        return Account.create(
            {
                "code": code,
                "name": name,
                "account_type": account_type,
                "reconcile": reconcile,
                "company_ids": [(4, self.id)],
            }
        )

    def _trx_ibx_get_or_create_journal(self, code, name, jtype, **extra):
        self.ensure_one()
        Journal = self.env["account.journal"]
        journal = Journal.search(
            [("company_id", "=", self.id), ("code", "=", code)], limit=1
        )
        if journal:
            return journal
        vals = {"name": name, "code": code, "type": jtype, "company_id": self.id}
        vals.update(extra)
        return Journal.create(vals)

    def action_trx_ibx_setup(self):
        """Crea (si faltan) cuentas, diarios y medio de pago del cambio
        inter-sucursal para esta compañía y agrega el medio de pago a todos sus
        POS. Idempotente."""
        for company in self:
            if not company.chart_template:
                raise UserError(
                    _("La compañía %s no tiene plan de cuentas instalado.", company.name)
                )
            if not company.trx_ibx_account_id:
                company.trx_ibx_account_id = company._trx_ibx_get_or_create_account(
                    CTA_CTE_CODE,
                    "Cambios inter-sucursal - cuenta corriente entre compañías",
                    "asset_current",
                    True,
                )
            if not company.trx_ibx_transit_account_id:
                company.trx_ibx_transit_account_id = company._trx_ibx_get_or_create_account(
                    TRANSIT_CODE,
                    "Cambios inter-sucursal - transitoria diario de cobros",
                    "asset_cash",
                    False,
                )
            if not company.trx_ibx_journal_id:
                company.trx_ibx_journal_id = company._trx_ibx_get_or_create_journal(
                    "IBXA", "Cambios inter-sucursal (ajustes)", "general"
                )
            if not company.trx_ibx_bank_journal_id:
                company.trx_ibx_bank_journal_id = company._trx_ibx_get_or_create_journal(
                    "IBXB",
                    "Cambios inter-sucursal (cobros)",
                    "bank",
                    default_account_id=company.trx_ibx_transit_account_id.id,
                )
            if not company.trx_ibx_payment_method_id:
                PM = self.env["pos.payment.method"]
                pm = PM.search(
                    [
                        ("company_id", "=", company.id),
                        ("use_payment_terminal", "=", "interbranch_exchange"),
                    ],
                    limit=1,
                )
                if not pm:
                    pm = PM.create(
                        {
                            "name": "Cambio inter-sucursal",
                            "company_id": company.id,
                            "journal_id": company.trx_ibx_bank_journal_id.id,
                            "use_payment_terminal": "interbranch_exchange",
                            "outstanding_account_id": company.trx_ibx_account_id.id,
                            "split_transactions": True,
                        }
                    )
                company.trx_ibx_payment_method_id = pm
            configs = self.env["pos.config"].search([("company_id", "=", company.id)])
            for config in configs:
                if company.trx_ibx_payment_method_id not in config.payment_method_ids:
                    config.payment_method_ids = [(4, company.trx_ibx_payment_method_id.id)]
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Cambio inter-sucursal"),
                "message": _("Cuentas, diarios y medio de pago configurados para %s.")
                % ", ".join(self.mapped("name")),
                "type": "success",
                "sticky": False,
            },
        }
