# Part of trx_pos_interbranch_exchange. Author: Trixocom. License: LGPL-3.
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round

_logger = logging.getLogger(__name__)

GROUP_USER = "trx_pos_interbranch_exchange.group_ibx_user"


class TrxIbxExchange(models.Model):
    """Un cambio inter-sucursal: venta original en la compañía A, cambio
    tomado en un POS de la compañía B (puede ser la misma)."""

    _name = "trx.ibx.exchange"
    _description = "Cambio inter-sucursal"
    _order = "id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default="/")
    state = fields.Selection(
        [("draft", "Preparado"), ("done", "Realizado"), ("cancel", "Cancelado")],
        default="draft",
        required=True,
        index=True,
    )
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    user_id = fields.Many2one("res.users", string="Cajero", default=lambda self: self.env.user)
    # Compañía que RECIBE el cambio (donde está el POS)
    company_id = fields.Many2one("res.company", string="Compañía que recibe", required=True, index=True)
    config_id = fields.Many2one("pos.config", string="POS que recibe", required=True)
    session_id = fields.Many2one("pos.session", string="Sesión que recibe")
    pos_order_id = fields.Many2one("pos.order", string="Venta nueva (B)")
    pos_payment_id = fields.Many2one("pos.payment", string="Pago en la venta nueva")
    # Venta original en la compañía A
    origin_company_id = fields.Many2one("res.company", string="Compañía que vendió", required=True, index=True)
    origin_order_id = fields.Many2one("pos.order", string="Venta original (A)", required=True)
    origin_move_id = fields.Many2one("account.move", string="Factura original (A)")
    origin_is_fiscal = fields.Boolean(string="Venta original fiscal")
    same_company = fields.Boolean(compute="_compute_same_company", store=True)
    # Documentos generados
    refund_move_id = fields.Many2one("account.move", string="Nota de crédito (A)")
    settlement_move_id = fields.Many2one("account.move", string="Asiento de compensación (A)")
    picking_id = fields.Many2one("stock.picking", string="Ingreso de stock (B)")
    # Importes
    currency_id = fields.Many2one(related="company_id.currency_id")
    amount = fields.Monetary(string="Importe del cambio (PVP)", currency_field="currency_id")
    amount_refund = fields.Monetary(string="Importe de la NC", currency_field="currency_id")
    amount_cost = fields.Monetary(string="Costo de la mercadería recibida", currency_field="currency_id")
    line_ids = fields.One2many("trx.ibx.exchange.line", "exchange_id", string="Líneas")
    note = fields.Text()

    @api.depends("company_id", "origin_company_id")
    def _compute_same_company(self):
        for rec in self:
            rec.same_company = rec.company_id == rec.origin_company_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code("trx.ibx.exchange") or "/"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _ibx_check_user(self):
        if not self.env.user.has_group(GROUP_USER):
            raise AccessError(_("No tenés permiso para realizar cambios inter-sucursal."))

    @api.model
    def _ibx_normalize_code(self, code):
        code = (code or "").strip()
        for prefix in ("Order ", "Pedido ", "Orden ", "ORDER ", "PEDIDO "):
            if code.startswith(prefix):
                code = code[len(prefix):].strip()
        return code

    @api.model
    def _ibx_find_order(self, code):
        """Busca la venta original en TODAS las compañías (sudo)."""
        code = self._ibx_normalize_code(code)
        if not code:
            return self.env["pos.order"]
        Order = self.env["pos.order"].sudo().with_context(active_test=False)
        order = Order.search([("uuid", "=", code)], limit=1)
        if not order:
            order = Order.search(
                ["|", ("pos_reference", "=", code), ("pos_reference", "=", "Order %s" % code)],
                limit=1,
            )
        if not order:
            # Búsqueda por número de orden (tracking_number); solo si es único
            found = Order.search([("tracking_number", "=", code), ("state", "in", ("paid", "done", "invoiced"))])
            if len(found) == 1:
                order = found
        return order

    @api.model
    def _ibx_line_exchanged_qty(self, origin_line):
        lines = self.env["trx.ibx.exchange.line"].sudo().search(
            [("origin_line_id", "=", origin_line.id), ("exchange_id.state", "in", ("draft", "done"))]
        )
        return sum(lines.mapped("qty"))

    @api.model
    def _ibx_line_status(self, origin_line, accepting_company):
        """Devuelve (qty_disponible, motivo_no_elegible o False)."""
        product = origin_line.product_id
        if product.type not in ("consu",) or not product.is_storable:
            return 0.0, _("No es un producto almacenable")
        if not product.product_tmpl_id._trx_ibx_exchange_allowed():
            return 0.0, _("La categoría del producto no acepta cambios inter-sucursal")
        if origin_line.qty <= 0:
            return 0.0, _("Línea de devolución")
        available = origin_line.qty - (origin_line.refunded_qty or 0.0) - self._ibx_line_exchanged_qty(origin_line)
        if float_compare(available, 0.0, precision_digits=3) <= 0:
            return 0.0, _("Ya fue devuelto o cambiado")
        return available, False

    @api.model
    def _ibx_check_order(self, order, accepting_company):
        if not order:
            return _("No se encontró ninguna venta con ese código.")
        if order.state not in ("paid", "done", "invoiced"):
            return _("La venta original no está confirmada (estado %s).", order.state)
        if order.amount_total <= 0:
            return _("La venta original es una devolución.")
        days = accepting_company.trx_ibx_days_limit
        if days and order.date_order and order.date_order < fields.Datetime.now() - timedelta(days=days):
            return _("La venta original tiene más de %s días (%s).", days, fields.Date.to_string(order.date_order))
        return False

    # ------------------------------------------------------------------
    # API llamada desde el POS
    # ------------------------------------------------------------------
    @api.model
    def ibx_lookup(self, code, config_id):
        self._ibx_check_user()
        config = self.env["pos.config"].browse(config_id)
        company = config.company_id
        order = self._ibx_find_order(code)
        error = self._ibx_check_order(order, company)
        if error:
            return {"ok": False, "error": error}
        invoice = order.account_move.filtered(lambda m: m.move_type == "out_invoice" and m.state == "posted")[:1]
        lines = []
        for line in order.lines:
            available, reason = self._ibx_line_status(line, company)
            unit_incl = line.price_subtotal_incl / line.qty if line.qty else 0.0
            lines.append(
                {
                    "origin_line_id": line.id,
                    "product_id": line.product_id.id,
                    "product_name": line.full_product_name or line.product_id.display_name,
                    "qty": line.qty,
                    "qty_available": available,
                    "unit_price_incl": float_round(unit_incl, precision_rounding=company.currency_id.rounding),
                    "eligible": bool(available) and not reason,
                    "reason": reason or "",
                }
            )
        return {
            "ok": True,
            "order": {
                "id": order.id,
                "name": order.name,
                "pos_reference": order.pos_reference,
                "date_order": fields.Datetime.to_string(order.date_order),
                "company_name": order.company_id.name,
                "company_id": order.company_id.id,
                "config_name": order.config_id.name,
                "is_fiscal": bool(invoice),
                "invoice_name": invoice.name if invoice else "",
                "same_company": order.company_id == company,
                "partner_name": order.partner_id.name or "",
            },
            "lines": lines,
        }

    @api.model
    def ibx_prepare(self, code, config_id, selected_lines):
        """Crea el cambio en estado 'draft' reservando las cantidades.
        selected_lines: [{'origin_line_id': int, 'qty': float}, ...]"""
        self._ibx_check_user()
        config = self.env["pos.config"].browse(config_id)
        company = config.company_id
        order = self._ibx_find_order(code)
        error = self._ibx_check_order(order, company)
        if error:
            raise UserError(error)
        session = config.current_session_id
        if not session or session.state not in ("opened", "opening_control"):
            raise UserError(_("El POS %s no tiene una sesión abierta.", config.name))
        invoice = order.account_move.filtered(lambda m: m.move_type == "out_invoice" and m.state == "posted")[:1]
        line_vals = []
        amount = 0.0
        cost = 0.0
        rounding = company.currency_id.rounding
        for sel in selected_lines:
            origin_line = order.lines.filtered(lambda l: l.id == int(sel.get("origin_line_id")))
            qty = float(sel.get("qty") or 0.0)
            if not origin_line or float_compare(qty, 0.0, precision_digits=3) <= 0:
                continue
            available, reason = self._ibx_line_status(origin_line, company)
            if reason:
                raise UserError(_("%s: %s", origin_line.product_id.display_name, reason))
            if float_compare(qty, available, precision_digits=3) > 0:
                raise UserError(
                    _("%s: cantidad %s mayor a la disponible para cambio (%s).", origin_line.product_id.display_name, qty, available)
                )
            unit_incl = origin_line.price_subtotal_incl / origin_line.qty if origin_line.qty else 0.0
            line_total = float_round(unit_incl * qty, precision_rounding=rounding)
            unit_cost = origin_line.product_id.with_company(company).standard_price
            line_vals.append(
                (
                    0,
                    0,
                    {
                        "origin_line_id": origin_line.id,
                        "product_id": origin_line.product_id.id,
                        "qty": qty,
                        "price_unit": origin_line.price_unit,
                        "discount": origin_line.discount,
                        "price_total": line_total,
                        "cost_unit": unit_cost,
                    },
                )
            )
            amount += line_total
            cost += unit_cost * qty
        if not line_vals:
            raise UserError(_("No se seleccionó ningún producto para el cambio."))
        exchange = self.sudo().create(
            {
                "company_id": company.id,
                "config_id": config.id,
                "session_id": session.id,
                "user_id": self.env.user.id,
                "origin_company_id": order.company_id.id,
                "origin_order_id": order.id,
                "origin_move_id": invoice.id if invoice else False,
                "origin_is_fiscal": bool(invoice),
                "amount": float_round(amount, precision_rounding=rounding),
                "amount_cost": cost,
                "line_ids": line_vals,
            }
        )
        return {
            "exchange_id": exchange.id,
            "name": exchange.name,
            "amount": exchange.amount,
            "same_company": exchange.same_company,
            "is_fiscal": exchange.origin_is_fiscal,
        }

    @api.model
    def ibx_cancel_draft(self, exchange_id):
        self._ibx_check_user()
        exchange = self.sudo().browse(exchange_id).exists()
        if exchange and exchange.state == "draft":
            exchange.write({"state": "cancel", "note": _("Cancelado desde el POS")})
        return True

    # ------------------------------------------------------------------
    # Ejecución (servidor, al sincronizar la venta nueva en B)
    # ------------------------------------------------------------------
    def _ibx_execute(self, pos_order, payment):
        """Ejecuta el cambio dentro de la transacción de la venta nueva.
        Todo lo de la compañía A corre con sudo + with_company(A)."""
        self.ensure_one()
        self = self.sudo()
        if self.state != "draft":
            return
        company_b = self.company_id
        company_a = self.origin_company_id
        rounding = company_b.currency_id.rounding
        if pos_order.company_id != company_b:
            raise UserError(_("El cambio %s fue preparado para otra compañía.", self.name))
        if float_compare(abs(payment.amount), self.amount, precision_rounding=rounding) != 0:
            raise UserError(
                _("El pago 'Cambio inter-sucursal' (%s) no coincide con el importe del cambio %s (%s).", payment.amount, self.name, self.amount)
            )
        if not company_a.trx_ibx_account_id or not company_a.trx_ibx_journal_id:
            raise UserError(
                _("La compañía %s no tiene configuradas las cuentas de cambio inter-sucursal (Ajustes de Punto de Venta).", company_a.name)
            )
        # 1) Nota de crédito en A
        refund = self._ibx_create_refund(company_a)
        # 2) Compensación en A: cancela el saldo a favor del cliente contra la cta cte con B
        settlement = self._ibx_create_settlement(company_a, company_b, refund)
        # 3) Ingreso de stock en B
        picking = self._ibx_create_return_picking(company_b)
        self.write(
            {
                "state": "done",
                "refund_move_id": refund.id,
                "settlement_move_id": settlement.id,
                "picking_id": picking.id,
                "pos_order_id": pos_order.id,
                "pos_payment_id": payment.id,
                "amount_refund": refund.amount_total,
                "date": fields.Datetime.now(),
            }
        )
        _logger.info(
            "[ibx] Cambio %s ejecutado: NC %s (%s) en %s, compensación %s, ingreso %s en %s, venta nueva %s",
            self.name, refund.name, refund.amount_total, company_a.name, settlement.name, picking.name, company_b.name, pos_order.name,
        )

    def _ibx_qty_by_product(self):
        qty_by_product = {}
        for line in self.line_ids:
            qty_by_product[line.product_id.id] = qty_by_product.get(line.product_id.id, 0.0) + line.qty
        return qty_by_product

    def _ibx_create_refund(self, company_a):
        self.ensure_one()
        reason = _("Cambio inter-sucursal %s en %s (venta %s)", self.name, self.company_id.name, self.origin_order_id.pos_reference or self.origin_order_id.name)
        invoice = self.origin_move_id
        if invoice and invoice.state == "posted" and invoice.move_type == "out_invoice":
            return self._ibx_create_fiscal_refund(company_a, invoice, reason)
        return self._ibx_create_nf_refund(company_a, reason)

    def _ibx_create_fiscal_refund(self, company_a, invoice, reason):
        """NC con el wizard account.move.reversal (asigna NC-A/B/C y CbtesAsoc;
        el action_post dispara el CAE vía l10n_ar_edi si el diario es electrónico)."""
        Wizard = self.env["account.move.reversal"].sudo().with_company(company_a)
        wiz = Wizard.with_context(active_model="account.move", active_ids=invoice.ids, active_id=invoice.id).create(
            {
                "journal_id": invoice.journal_id.id,
                "reason": reason,
                "date": fields.Date.context_today(self),
                "move_ids": [(6, 0, invoice.ids)],
            }
        )
        res = wiz.refund_moves()
        nc_id = res.get("res_id") if isinstance(res, dict) else False
        if not nc_id and wiz.new_move_ids:
            nc_id = wiz.new_move_ids[:1].id
        nc = self.env["account.move"].sudo().with_company(company_a).browse(nc_id)
        if not nc:
            raise UserError(_("No se pudo crear la nota de crédito en %s.", company_a.name))
        # Dejar solo los productos devueltos, con su cantidad
        qty_by_product = self._ibx_qty_by_product()
        commands = []
        for line in nc.invoice_line_ids:
            if line.display_type != "product":
                commands.append((2, line.id))
                continue
            remaining = qty_by_product.get(line.product_id.id, 0.0)
            if remaining <= 0:
                commands.append((2, line.id))
                continue
            take = min(remaining, line.quantity)
            qty_by_product[line.product_id.id] = remaining - take
            if float_compare(take, line.quantity, precision_digits=3) != 0:
                commands.append((1, line.id, {"quantity": take}))
        nc.write({"invoice_line_ids": commands})
        missing = [pid for pid, q in qty_by_product.items() if float_compare(q, 0.0, precision_digits=3) > 0]
        if missing or not nc.invoice_line_ids:
            raise UserError(
                _("La factura %s no contiene (o no alcanza) los productos seleccionados para el cambio.", invoice.name)
            )
        nc.action_post()
        return nc

    def _ibx_create_nf_refund(self, company_a, reason):
        """Venta original sin factura: NC interna en un diario de ventas SIN
        documentos fiscales de A (mismo tratamiento contable que la venta NF)."""
        order = self.origin_order_id
        journal = company_a.trx_ibx_nf_journal_id or order.config_id.journal_id
        if not journal or journal.type != "sale":
            raise UserError(_("La compañía %s no tiene un diario de ventas para la NC no fiscal.", company_a.name))
        if journal.l10n_latam_use_documents:
            raise UserError(
                _("El diario %s usa documentos fiscales; configurá en %s un 'Diario para NC de ventas no fiscales' sin documentos.", journal.name, company_a.name)
            )
        partner = order.partner_id or self.env.ref("l10n_ar.par_cfa", raise_if_not_found=False) or company_a.partner_id
        Move = self.env["account.move"].sudo().with_company(company_a)
        lines = []
        for line in self.line_ids:
            origin = line.origin_line_id
            lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "name": origin.full_product_name or line.product_id.display_name,
                        "quantity": line.qty,
                        "price_unit": origin.price_unit,
                        "discount": origin.discount,
                        "tax_ids": [(6, 0, origin.tax_ids.ids)],
                    },
                )
            )
        nc = Move.create(
            {
                "move_type": "out_refund",
                "company_id": company_a.id,
                "journal_id": journal.id,
                "partner_id": partner.id,
                "invoice_date": fields.Date.context_today(self),
                "ref": reason,
                "invoice_origin": order.pos_reference or order.name,
                "invoice_line_ids": lines,
            }
        )
        nc.action_post()
        return nc

    def _ibx_create_settlement(self, company_a, company_b, refund):
        """Reembolso de la NC en A como account.payment saliente en el diario
        IBXB (cuenta de pago = cta cte inter-sucursal). Deja al cliente en cero
        en A, la NC en estado "pagada", y el importe acreditado en la cta cte:
        A le debe ese importe a B (que es quien le dio el producto al cliente)."""
        recv_lines = refund.line_ids.filtered(lambda l: l.account_id.account_type == "asset_receivable")
        if not recv_lines:
            raise UserError(_("La NC %s no tiene línea de deudores.", refund.name))
        amount = abs(sum(recv_lines.mapped("balance")))
        if float_is_zero(amount, precision_rounding=company_a.currency_id.rounding):
            raise UserError(_("La NC %s tiene importe cero.", refund.name))
        journal = company_a.trx_ibx_bank_journal_id
        method_line = journal.outbound_payment_method_line_ids[:1]
        if not journal or not method_line:
            raise UserError(_("La compañía %s no tiene el diario de cobros inter-sucursal configurado.", company_a.name))
        if method_line.payment_account_id != company_a.trx_ibx_account_id:
            method_line.payment_account_id = company_a.trx_ibx_account_id
        label = _("Cambio inter-sucursal %s - NC %s - recibido en %s", self.name, refund.name, company_b.name)
        Payment = self.env["account.payment"].sudo().with_company(company_a)
        vals = {
            "payment_type": "outbound",
            "partner_type": "customer",
            "partner_id": refund.partner_id.commercial_partner_id.id,
            "amount": amount,
            "currency_id": refund.currency_id.id,
            "journal_id": journal.id,
            "payment_method_line_id": method_line.id,
            "company_id": company_a.id,
            "date": fields.Date.context_today(self),
            "memo": label,
        }
        # account_payment_pro (ADHOC): autocompleta "deudas a pagar" con TODAS las líneas
        # abiertas del partner (peligroso con Consumidor Final) y las concilia al postear.
        # Le fijamos exactamente las líneas de esta NC.
        if "to_pay_move_line_ids" in Payment._fields:
            vals["to_pay_move_line_ids"] = [(6, 0, recv_lines.ids)]
        payment = Payment.create(vals)
        if "to_pay_move_line_ids" in Payment._fields:
            payment.to_pay_move_line_ids = [(6, 0, recv_lines.ids)]
        payment.action_post()
        counterpart = payment.move_id.line_ids.filtered(lambda l: l.account_id.account_type == "asset_receivable")
        pending = (recv_lines + counterpart).filtered(lambda l: not l.reconciled)
        if len(pending) > 1:
            pending.reconcile()
        if any(not l.reconciled for l in recv_lines):
            raise UserError(_("No se pudo conciliar la NC %s con su reembolso inter-sucursal.", refund.name))
        return payment.move_id

    def _ibx_create_return_picking(self, company_b):
        """Devolución del cliente al depósito del POS que recibe (B)."""
        warehouse = self.config_id.picking_type_id.warehouse_id
        picking_type = warehouse.in_type_id
        if not warehouse or not picking_type:
            raise UserError(_("El POS %s no tiene depósito/tipo de operación de recepción.", self.config_id.name))
        customers = self.env.ref("stock.stock_location_customers")
        Picking = self.env["stock.picking"].sudo().with_company(company_b)
        moves = []
        for line in self.line_ids:
            product = line.product_id
            moves.append(
                (
                    0,
                    0,
                    {
                        # Odoo 19: stock.move ya no tiene campo `name`
                        "product_id": product.id,
                        "product_uom_qty": line.qty,
                        "product_uom": product.uom_id.id,
                        "location_id": customers.id,
                        "location_dest_id": warehouse.lot_stock_id.id,
                        "company_id": company_b.id,
                    },
                )
            )
        picking = Picking.create(
            {
                "picking_type_id": picking_type.id,
                "location_id": customers.id,
                "location_dest_id": warehouse.lot_stock_id.id,
                "origin": _("Cambio inter-sucursal %s (venta %s de %s)", self.name, self.origin_order_id.pos_reference or self.origin_order_id.name, self.origin_company_id.name),
                "partner_id": self.origin_order_id.partner_id.id or False,
                "company_id": company_b.id,
                "move_ids": moves,
            }
        )
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.button_validate()
        if picking.state != "done":
            raise UserError(_("No se pudo validar el ingreso de stock %s (estado %s).", picking.name, picking.state))
        return picking

    # ------------------------------------------------------------------
    # Cron: los preparados que nunca se confirmaron se cancelan
    # ------------------------------------------------------------------
    @api.model
    def _ibx_cron_expire_drafts(self, hours=12):
        limit = fields.Datetime.now() - timedelta(hours=hours)
        drafts = self.sudo().search([("state", "=", "draft"), ("date", "<", limit)])
        drafts.write({"state": "cancel", "note": _("Expirado: la venta nueva nunca se confirmó")})
        return True

    def action_view_documents(self):
        self.ensure_one()
        moves = self.refund_move_id | self.settlement_move_id
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", moves.ids)],
            "name": _("Documentos del cambio %s", self.name),
            "context": {"allowed_company_ids": self.env.companies.ids},
        }


class TrxIbxExchangeLine(models.Model):
    _name = "trx.ibx.exchange.line"
    _description = "Línea de cambio inter-sucursal"

    exchange_id = fields.Many2one("trx.ibx.exchange", required=True, ondelete="cascade", index=True)
    origin_line_id = fields.Many2one("pos.order.line", string="Línea de la venta original", required=True, index=True)
    product_id = fields.Many2one("product.product", required=True)
    qty = fields.Float(string="Cantidad", digits="Product Unit of Measure", required=True)
    price_unit = fields.Float(string="Precio unitario original", digits="Product Price")
    discount = fields.Float(string="Descuento (%)")
    price_total = fields.Float(string="Total con IVA", digits="Product Price")
    cost_unit = fields.Float(string="Costo unitario (B)", digits="Product Price")

    @api.constrains("qty")
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(_("La cantidad a cambiar debe ser positiva."))
