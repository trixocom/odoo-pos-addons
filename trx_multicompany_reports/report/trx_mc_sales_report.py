# Part of trx_multicompany_reports. Author: Trixocom. License: LGPL-3.
from odoo import fields, models


class TrxMcSalesReport(models.Model):
    """Ventas por razón social (CUIT) y local.

    Vista SQL de solo lectura que une:
    * líneas de ventas POS confirmadas (paid / done / invoiced), y
    * líneas de facturas y notas de crédito de clientes posteadas que NO
      provienen del POS (para no contar dos veces la venta facturada desde
      la caja).

    Pensada para la casa matriz (acceso a todas las compañías): agrupa por
    razón social (compañía raíz), local (compañía), punto de venta, día,
    producto y categoría. Importes en moneda de la compañía (sin conversión:
    la red opera en una sola moneda).
    """

    _name = "trx.mc.sales.report"
    _description = "Ventas por razón social (CUIT) y local"
    _auto = False
    _order = "date desc"
    _rec_name = "ref"

    ref = fields.Char(string="Comprobante / orden", readonly=True)
    date = fields.Date(string="Fecha", readonly=True)
    source = fields.Selection(
        [("pos", "Venta POS"), ("invoice", "Factura / NC (no POS)")],
        string="Origen",
        readonly=True,
    )
    trx_root_company_id = fields.Many2one("res.company", string="Razón social (CUIT)", readonly=True)
    company_id = fields.Many2one("res.company", string="Local (compañía)", readonly=True)
    config_id = fields.Many2one("pos.config", string="Punto de venta", readonly=True)
    journal_id = fields.Many2one("account.journal", string="Diario", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", readonly=True)
    user_id = fields.Many2one("res.users", string="Vendedor / cajero", readonly=True)
    product_id = fields.Many2one("product.product", string="Producto", readonly=True)
    product_tmpl_id = fields.Many2one("product.template", string="Plantilla de producto", readonly=True)
    product_categ_id = fields.Many2one("product.category", string="Categoría de producto", readonly=True)
    order_id = fields.Many2one("pos.order", string="Orden POS", readonly=True)
    move_id = fields.Many2one("account.move", string="Factura / NC", readonly=True)
    invoiced = fields.Boolean(string="Facturado", readonly=True)
    qty = fields.Float(string="Cantidad", readonly=True)
    price_subtotal = fields.Float(string="Neto (sin impuestos)", readonly=True)
    price_total = fields.Float(string="Total (con impuestos)", readonly=True)
    total_cost = fields.Float(string="Costo", readonly=True)
    margin = fields.Float(string="Margen", readonly=True)
    nbr_lines = fields.Integer(string="Líneas", readonly=True)

    def _select_pos(self):
        return """
            SELECT
                l.id AS id,
                s.pos_reference AS ref,
                (s.date_order AT TIME ZONE 'UTC' AT TIME ZONE COALESCE(cop.tz, 'UTC'))::date AS date,
                'pos' AS source,
                NULLIF(split_part(co.parent_path, '/', 1), '')::int AS trx_root_company_id,
                s.company_id AS company_id,
                ps.config_id AS config_id,
                s.sale_journal AS journal_id,
                s.partner_id AS partner_id,
                s.user_id AS user_id,
                l.product_id AS product_id,
                pp.product_tmpl_id AS product_tmpl_id,
                pt.categ_id AS product_categ_id,
                s.id AS order_id,
                s.account_move AS move_id,
                s.account_move IS NOT NULL AS invoiced,
                l.qty AS qty,
                SIGN(l.qty) * SIGN(l.price_unit) * ABS(l.price_subtotal) AS price_subtotal,
                SIGN(l.qty) * SIGN(l.price_unit) * ABS(l.price_subtotal_incl) AS price_total,
                COALESCE(l.total_cost, 0) AS total_cost,
                SIGN(l.qty) * SIGN(l.price_unit) * ABS(l.price_subtotal) - COALESCE(l.total_cost, 0) AS margin,
                1 AS nbr_lines
            FROM pos_order_line l
                JOIN pos_order s ON s.id = l.order_id
                LEFT JOIN pos_session ps ON ps.id = s.session_id
                LEFT JOIN res_company co ON co.id = s.company_id
                LEFT JOIN res_partner cop ON cop.id = co.partner_id
                LEFT JOIN product_product pp ON pp.id = l.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE s.state IN ('paid', 'done', 'invoiced')
        """

    def _select_invoice(self):
        # Facturas/NC de clientes posteadas que no provienen de una orden POS.
        # NC en negativo. Costo = cantidad x costo estándar (company-dependent,
        # jsonb por compañía en Odoo 17+).
        return """
            SELECT
                -aml.id AS id,
                m.name AS ref,
                m.invoice_date AS date,
                'invoice' AS source,
                NULLIF(split_part(co.parent_path, '/', 1), '')::int AS trx_root_company_id,
                aml.company_id AS company_id,
                NULL::int AS config_id,
                m.journal_id AS journal_id,
                m.commercial_partner_id AS partner_id,
                m.invoice_user_id AS user_id,
                aml.product_id AS product_id,
                pp.product_tmpl_id AS product_tmpl_id,
                pt.categ_id AS product_categ_id,
                NULL::int AS order_id,
                m.id AS move_id,
                TRUE AS invoiced,
                CASE WHEN m.move_type = 'out_refund' THEN -aml.quantity ELSE aml.quantity END AS qty,
                CASE WHEN m.move_type = 'out_refund' THEN -aml.price_subtotal ELSE aml.price_subtotal END AS price_subtotal,
                CASE WHEN m.move_type = 'out_refund' THEN -aml.price_total ELSE aml.price_total END AS price_total,
                (CASE WHEN m.move_type = 'out_refund' THEN -aml.quantity ELSE aml.quantity END)
                    * COALESCE((pp.standard_price ->> aml.company_id::text)::float, 0) AS total_cost,
                (CASE WHEN m.move_type = 'out_refund' THEN -aml.price_subtotal ELSE aml.price_subtotal END)
                    - (CASE WHEN m.move_type = 'out_refund' THEN -aml.quantity ELSE aml.quantity END)
                    * COALESCE((pp.standard_price ->> aml.company_id::text)::float, 0) AS margin,
                1 AS nbr_lines
            FROM account_move_line aml
                JOIN account_move m ON m.id = aml.move_id
                LEFT JOIN res_company co ON co.id = aml.company_id
                LEFT JOIN product_product pp ON pp.id = aml.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE m.move_type IN ('out_invoice', 'out_refund')
              AND m.state = 'posted'
              AND aml.display_type = 'product'
              AND NOT EXISTS (SELECT 1 FROM pos_order po WHERE po.account_move = m.id)
        """

    @property
    def _table_query(self):
        # Odoo 17+: con _table_query el modelo se lee desde esta subconsulta,
        # no se crea una vista en la base.
        return "%s UNION ALL %s" % (self._select_pos(), self._select_invoice())
