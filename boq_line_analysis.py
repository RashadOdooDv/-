# -*- coding: utf-8 -*-
from odoo import tools, fields, models


class BOQLineAnalysis(models.Model):
    """نموذج تحليلي للقراءة فقط (SQL View) مبني على بنود القيود المحاسبية
    المرتبطة بالمشاريع، لتقديم تقارير Pivot/Graph تفاعلية شبيهة بأدوات BI."""
    _name = 'boq.line.analysis'
    _description = 'تحليل تكاليف المشاريع (تقرير تفاعلي)'
    _auto = False
    _order = 'date desc'

    move_line_id = fields.Many2one('account.move.line', string='بند القيد', readonly=True)
    move_id = fields.Many2one('account.move', string='المستند', readonly=True)
    move_type = fields.Selection([
        ('entry', 'قيد يومية'),
        ('out_invoice', 'فاتورة عميل'),
        ('out_refund', 'إشعار دائن عميل'),
        ('in_invoice', 'فاتورة مورد'),
        ('in_refund', 'إشعار دائن مورد'),
    ], string='نوع المستند', readonly=True)
    state = fields.Selection([
        ('draft', 'مسودة'),
        ('posted', 'مرحّل'),
        ('cancel', 'ملغي'),
    ], string='الحالة', readonly=True)

    project_id = fields.Many2one('project.project', string='المشروع', readonly=True)
    boq_item_id = fields.Many2one('boq.item', string='بند BOQ', readonly=True)
    boq_parent_id = fields.Many2one('boq.item', string='القسم الرئيسي', readonly=True)
    account_id = fields.Many2one('account.account', string='الحساب', readonly=True)
    partner_id = fields.Many2one('res.partner', string='الجهة (المورد/العميل)', readonly=True)
    analytic_distribution = fields.Json(string='التوزيع التحليلي', readonly=True)

    date = fields.Date(string='التاريخ', readonly=True)
    company_id = fields.Many2one('res.company', string='الشركة', readonly=True)
    currency_id = fields.Many2one('res.currency', string='العملة', readonly=True)
    amount = fields.Monetary(string='المبلغ (مدين - دائن)', readonly=True)
    is_general_expense = fields.Boolean(string='مصروف عمومي', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    l.id                    AS id,
                    l.id                    AS move_line_id,
                    l.move_id               AS move_id,
                    m.move_type             AS move_type,
                    m.state                 AS state,
                    l.project_id            AS project_id,
                    l.boq_item_id           AS boq_item_id,
                    b.parent_id             AS boq_parent_id,
                    l.account_id            AS account_id,
                    l.partner_id            AS partner_id,
                    l.analytic_distribution AS analytic_distribution,
                    l.date                  AS date,
                    l.company_id            AS company_id,
                    l.currency_id           AS currency_id,
                    (l.debit - l.credit)    AS amount,
                    l.is_general_expense    AS is_general_expense
                FROM account_move_line l
                JOIN account_move m ON m.id = l.move_id
                JOIN account_account a ON a.id = l.account_id
                LEFT JOIN boq_item b ON b.id = l.boq_item_id
                WHERE a.account_type IN ('expense', 'expense_depreciation', 'expense_direct_cost')
                  AND l.display_type IS DISTINCT FROM 'line_section'
                  AND l.display_type IS DISTINCT FROM 'line_note'
            )
        """)
