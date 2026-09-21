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
    trx_ibx_payment_journal_id = fields.Many2one(
        "account.journal",
        string="Diario de reembolsos inter-sucursal",
        help="Diario tipo banco donde se registra, en la compañía que vendió, el "
        "reembolso de la NC contra la cuenta corriente inter-sucursal (account.payment). "
        "Separado del diario del medio de pago POS para que los asientos de cierre de "
        "sesión y los pagos no compartan numeración.",
    )
    trx_ibx_payment_method_id = fields.Many2one(
        "pos.payment.method",
        string="Medio de pago 'Cambio inter-sucursal'",
    )
    trx_ibx_nf_journal_id = fields.Many2one(
        "account.journal",
        string="Diario para NC de ventas no fiscales (NF)",
        domain="[('type', '=', 'sale'), ('company_id', 'parent_of', id)]",
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

    # Sucursales (parent_id): la configuración del cambio inter-sucursal es por
    # razón social. Se delega a la raíz con el mecanismo nativo de Odoo (copia
    # al crear la sucursal, propagación al escribir la raíz, readonly en la
    # sucursal). El medio de pago NO se delega: Odoo exige que el medio de pago
    # de un POS sea de la misma compañía que el POS, así que hay uno por local.
    TRX_IBX_ROOT_DELEGATED_FIELDS = [
        "trx_ibx_account_id",
        "trx_ibx_transit_account_id",
        "trx_ibx_journal_id",
        "trx_ibx_bank_journal_id",
        "trx_ibx_payment_journal_id",
        "trx_ibx_nf_journal_id",
        "trx_ibx_days_limit",
        "trx_ibx_allow_cash_difference",
    ]

    def _get_company_root_delegated_field_names(self):
        return super()._get_company_root_delegated_field_names() + self.TRX_IBX_ROOT_DELEGATED_FIELDS

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

    def _trx_ibx_setup_payment_method(self, root):
        """Medio de pago 'Cambio inter-sucursal' de ESTA compañía (raíz o
        sucursal), con la cta cte de la raíz como cuenta pendiente, agregado a
        todos los POS de la compañía. Idempotente."""
        self.ensure_one()
        PM = self.env["pos.payment.method"]
        pm = self.trx_ibx_payment_method_id
        if not pm:
            pm = PM.search(
                [
                    ("company_id", "=", self.id),
                    ("use_payment_terminal", "=", "interbranch_exchange"),
                ],
                limit=1,
            )
        if not pm:
            pm = PM.create(
                {
                    "name": "Cambio inter-sucursal",
                    "company_id": self.id,
                    "journal_id": root.trx_ibx_bank_journal_id.id,
                    "use_payment_terminal": "interbranch_exchange",
                    "outstanding_account_id": root.trx_ibx_account_id.id,
                    # split_transactions = "Identificar cliente": exigiría partner en la venta
                    "split_transactions": False,
                }
            )
        if self.trx_ibx_payment_method_id != pm:
            self.trx_ibx_payment_method_id = pm
        pm_vals = {}
        if pm.outstanding_account_id != root.trx_ibx_account_id:
            pm_vals["outstanding_account_id"] = root.trx_ibx_account_id.id
        if pm.journal_id != root.trx_ibx_bank_journal_id:
            pm_vals["journal_id"] = root.trx_ibx_bank_journal_id.id
        if pm.split_transactions:
            pm_vals["split_transactions"] = False
        if pm_vals:
            pm.write(pm_vals)
        configs = self.env["pos.config"].search([("company_id", "=", self.id)])
        for config in configs:
            if pm not in config.payment_method_ids:
                config.payment_method_ids = [(4, pm.id)]
        return pm

    def action_trx_ibx_setup(self):
        """Crea (si faltan) cuentas, diarios y medio de pago del cambio
        inter-sucursal para esta razón social (compañía raíz) y agrega el medio
        de pago a todos los POS de la raíz y de sus sucursales. Idempotente.
        Llamado sobre una sucursal, opera sobre su raíz."""
        roots = self.mapped("root_id")
        for company in roots:
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
            if not company.trx_ibx_payment_journal_id:
                company.trx_ibx_payment_journal_id = company._trx_ibx_get_or_create_journal(
                    "IBXP",
                    "Cambios inter-sucursal (reembolsos NC)",
                    "bank",
                    default_account_id=company.trx_ibx_transit_account_id.id,
                )
            # Las líneas de método de pago de los diarios IBXB (medio de pago POS) e
            # IBXP (reembolso de la NC en A, account.payment saliente) apuntan a la
            # cuenta corriente: todo cae directo en la cta cte, sin "pendientes".
            bank_journal = company.trx_ibx_bank_journal_id
            pay_journal = company.trx_ibx_payment_journal_id
            for jrn in bank_journal | pay_journal:
                for line in jrn.inbound_payment_method_line_ids | jrn.outbound_payment_method_line_ids:
                    if line.payment_account_id != company.trx_ibx_account_id:
                        line.payment_account_id = company.trx_ibx_account_id
            # Odoo 19: un diario de la raíz solo es visible para los usuarios de
            # una sucursal si está "compartido con sucursales". El medio de pago
            # de cada local apunta al diario IBXB de la raíz → compartirlo.
            for jrn in company.trx_ibx_journal_id | bank_journal | pay_journal:
                if "shared_to_branches" in jrn._fields and not jrn.shared_to_branches:
                    jrn.shared_to_branches = True
            # Sincronizar la configuración a las sucursales existentes (las
            # creadas antes de esta configuración no la tienen copiada): un
            # write de los campos delegados en la raíz los propaga.
            company.write({
                fname: company._fields[fname].convert_to_write(company[fname], company)
                for fname in self.TRX_IBX_ROOT_DELEGATED_FIELDS
            })
            # Un medio de pago por local (raíz + sucursales), todos sobre la
            # misma cta cte / diario de la raíz.
            tree = self.sudo().search([("id", "child_of", company.id)])
            for local in tree:
                local._trx_ibx_setup_payment_method(company)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Cambio inter-sucursal"),
                "message": _("Cuentas, diarios y medio de pago configurados para %s (y sus sucursales).")
                % ", ".join(roots.mapped("name")),
                "type": "success",
                "sticky": False,
            },
        }
