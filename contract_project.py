# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ContractProject(models.Model):
    _inherit = 'project.project'

    is_contracting_project = fields.Boolean(
        string='مشروع مقاولات', default=False,
        help='فعّل هذا الخيار لتطبيق منطق BOQ والربط المحاسبي الإجباري على هذا المشروع.')

    boq_ids = fields.One2many('boq.item', 'project_id', string='بنود جدول الكميات')
    boq_count = fields.Integer(compute='_compute_boq_count')

    contract_value_original = fields.Monetary(
        string='قيمة العقد الأصلي', currency_field='currency_id')
    vo_ids = fields.One2many('contract.variation.order', 'project_id', string='أوامر التغيير')
    approved_vo_amount = fields.Monetary(
        string='مجموع أوامر التغيير المعتمدة', compute='_compute_contract_financials', store=True,
        currency_field='currency_id')
    revised_contract_value = fields.Monetary(
        string='قيمة العقد المراجعة', compute='_compute_contract_financials', store=True,
        currency_field='currency_id')

    contract_value = fields.Monetary(
        string='قيمة العقد الإجمالية (حسب BOQ)', compute='_compute_boq_totals', store=True,
        currency_field='currency_id')
    total_actual_cost = fields.Monetary(
        string='إجمالي التكلفة الفعلية', compute='_compute_boq_totals', store=True,
        currency_field='currency_id')
    total_variance = fields.Monetary(
        string='إجمالي الانحراف', compute='_compute_boq_totals', store=True,
        currency_field='currency_id')
    profitability_percent = fields.Float(
        string='نسبة الربحية %', compute='_compute_boq_totals', store=True)
    overall_completion_percent = fields.Float(
        string='نسبة الإنجاز الإجمالية %', compute='_compute_boq_totals', store=True)
    budget_alert_level = fields.Selection([
        ('normal', 'طبيعي'),
        ('warning', 'تحذير (85%+)'),
        ('exceeded', 'تجاوز الميزانية'),
    ], string='حالة الميزانية العامة', compute='_compute_boq_totals', store=True)

    unassigned_entries_count = fields.Integer(
        string='حركات غير مسندة لبند', compute='_compute_unassigned_entries')

    # Billing / Collection
    progress_billing_ids = fields.One2many('contract.progress.billing', 'project_id', string='شهادات الدفع المرحلية')
    total_billed = fields.Monetary(string='إجمالي المفوَّت', compute='_compute_billing_totals', store=True,
                                   currency_field='currency_id')
    total_collected = fields.Monetary(string='إجمالي المحصّل', compute='_compute_billing_totals', store=True,
                                      currency_field='currency_id')
    total_due = fields.Monetary(string='المتبقي للتحصيل', compute='_compute_billing_totals', store=True,
                                currency_field='currency_id')

    # Retention
    retention_release_ids = fields.One2many('contract.retention.release', 'project_id', string='صرف حجز الضمان')
    total_retention_withheld = fields.Monetary(string='إجمالي حجز الضمان', compute='_compute_retention_totals',
                                               store=True, currency_field='currency_id')
    total_retention_released = fields.Monetary(string='إجمالي المصروف من حجز الضمان', compute='_compute_retention_totals',
                                               store=True, currency_field='currency_id')
    retention_balance = fields.Monetary(string='رصيد حجز الضمان', compute='_compute_retention_totals',
                                        store=True, currency_field='currency_id')

    # Earned Value (basic)
    earned_value_percent = fields.Float(string='نسبة القيمة المكتسبة %', compute='_compute_earned_value', store=True)
    cost_performance_index = fields.Float(string='CPI', compute='_compute_earned_value', store=True, digits=(16, 3))
    schedule_performance_index = fields.Float(string='SPI', compute='_compute_earned_value', store=True, digits=(16, 3))
    estimate_at_completion = fields.Monetary(string='التكلفة التقديرية عند الإكمال (EAC)',
                                             compute='_compute_earned_value', store=True, currency_field='currency_id')
    cost_to_complete = fields.Monetary(string='التكلفة المتبقية للتكملة (CTC)',
                                       compute='_compute_earned_value', store=True, currency_field='currency_id')

    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', store=True, string='العملة')

    # -------------------------------------------------------------
    @api.depends('boq_ids')
    def _compute_boq_count(self):
        for rec in self:
            rec.boq_count = len(rec.boq_ids.filtered(lambda b: not b.is_section))

    @api.depends('boq_ids.planned_amount', 'boq_ids.actual_cost',
                 'boq_ids.completion_percent', 'boq_ids.parent_id')
    def _compute_boq_totals(self):
        for rec in self:
            # نأخذ فقط البنود الجذرية (بدون parent) لتفادي احتساب القيم مرتين
            root_items = rec.boq_ids.filtered(lambda b: not b.parent_id)
            rec.contract_value = sum(root_items.mapped('planned_amount'))
            rec.total_actual_cost = sum(root_items.mapped('actual_cost'))
            rec.total_variance = rec.contract_value - rec.total_actual_cost
            rec.profitability_percent = (
                (rec.total_variance / rec.contract_value) * 100.0
                if rec.contract_value else 0.0
            )
            consumption_percent = (
                (rec.total_actual_cost / rec.contract_value) * 100.0
                if rec.contract_value else 0.0
            )
            if consumption_percent >= 100:
                rec.budget_alert_level = 'exceeded'
            elif consumption_percent >= 85:
                rec.budget_alert_level = 'warning'
            else:
                rec.budget_alert_level = 'normal'
            total_planned = sum(root_items.mapped('planned_amount')) or 1.0
            rec.overall_completion_percent = sum(
                b.completion_percent * b.planned_amount for b in root_items
            ) / total_planned

    def _compute_unassigned_entries(self):
        MoveLine = self.env['account.move.line']
        for rec in self:
            rec.unassigned_entries_count = MoveLine.search_count([
                '|',
                ('project_id', '=', rec.id),
                ('move_id.project_id', '=', rec.id),
                ('boq_item_id', '=', False),
                ('is_general_expense', '=', False),
                ('parent_state', '=', 'posted'),
            ])

    # -------------------------------------------------------------
    def action_view_boq_items(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'بنود جدول الكميات',
            'res_model': 'boq.item',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_unassigned_entries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'حركات غير مسندة لبند',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': [
                '|',
                ('project_id', '=', self.id),
                ('move_id.project_id', '=', self.id),
                ('boq_item_id', '=', False),
                ('is_general_expense', '=', False),
                ('parent_state', '=', 'posted'),
            ],
        }
