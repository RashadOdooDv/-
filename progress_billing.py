# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ContractProgressBilling(models.Model):
    _name = 'contract.progress.billing'
    _description = 'شهادة دفع مرحلية - Interim Payment Certificate (IPC)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='رقم الشهادة', required=True, copy=False, readonly=True, default=lambda self: _('جديد'))
    project_id = fields.Many2one(
        'project.project', string='المشروع', required=True, tracking=True,
        domain="[('is_contracting_project', '=', True)]",
        ondelete='restrict')
    partner_id = fields.Many2one(
        'res.partner', string='العميل', required=True, tracking=True,
        ondelete='restrict')
    company_id = fields.Many2one('res.company', string='الشركة', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='العملة', required=True,
                                  default=lambda self: self.env.company.currency_id)

    date = fields.Date(string='تاريخ الشهادة', required=True, default=fields.Date.context_today, tracking=True)
    period_start = fields.Date(string='فترة من')
    period_end = fields.Date(string='فترة إلى')

    contract_value_original = fields.Monetary(string='قيمة العقد الأصلي', currency_field='currency_id')
    approved_vo_amount = fields.Monetary(string='مجموع أوامر التغيير المعتمدة', currency_field='currency_id', readonly=True)
    contract_value_revised = fields.Monetary(string='قيمة العقد المراجعة', currency_field='currency_id',
                                             compute='_compute_contract_values', store=True)

    line_ids = fields.One2many('contract.progress.billing.line', 'billing_id', string='بنود الشهادة')

    # المبالغ
    gross_amount = fields.Monetary(string='إجمالي المبلغ المعتمد', currency_field='currency_id',
                                   compute='_compute_amounts', store=True)
    previous_certified_amount = fields.Monetary(string='إجمالي الشهادات السابقة المعتمدة', currency_field='currency_id', default=0.0)
    net_amount_before_retention = fields.Monetary(string='صافي قبل حجز الضمان', currency_field='currency_id',
                                                  compute='_compute_amounts', store=True)
    retention_percent = fields.Float(string='نسبة حجز الضمان %', default=5.0)
    retention_amount = fields.Monetary(string='مبلغ حجز الضمان', currency_field='currency_id',
                                       compute='_compute_amounts', store=True)
    amount_due = fields.Monetary(string='صافي مستحق للدفع', currency_field='currency_id',
                                 compute='_compute_amounts', store=True)

    move_id = fields.Many2one('account.move', string='فاتورة العميل', readonly=True, copy=False)
    invoice_id = fields.Many2one('account.move', string='فاتورة مرتبطة', related='move_id', readonly=True)

    state = fields.Selection([
        ('draft', 'مسودة'),
        ('submitted', 'مُقدمة'),
        ('approved', 'معتمدة'),
        ('invoiced', 'تم إصدار فاتورة'),
        ('cancelled', 'ملغاة'),
    ], string='الحالة', default='draft', tracking=True)

    notes = fields.Text(string='ملاحظات')
    company_currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='عملة الشركة')

    _sql_constraints = [
        ('retention_percent_check', 'CHECK(retention_percent >= 0 AND retention_percent <= 100)',
         'نسبة حجز الضمان يجب أن تكون بين 0 و 100.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('جديد')) == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code('contract.progress.billing') or _('جديد')
        return super().create(vals_list)

    @api.depends('contract_value_original', 'approved_vo_amount')
    def _compute_contract_values(self):
        for rec in self:
            rec.contract_value_revised = (rec.contract_value_original or 0.0) + (rec.approved_vo_amount or 0.0)

    @api.depends('line_ids.certified_amount', 'previous_certified_amount', 'retention_percent')
    def _compute_amounts(self):
        for rec in self:
            gross = sum(rec.line_ids.mapped('certified_amount'))
            rec.gross_amount = gross
            net_before_ret = gross - (rec.previous_certified_amount or 0.0)
            rec.net_amount_before_retention = net_before_ret if net_before_ret > 0 else 0.0
            retention = (rec.net_amount_before_retention * (rec.retention_percent or 0.0)) / 100.0
            rec.retention_amount = retention
            rec.amount_due = rec.net_amount_before_retention - retention

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.partner_id = self.project_id.partner_id
            # جلب قيمة العقد الأصلي
            self.contract_value_original = self.project_id.contract_value or 0.0
            # جلب مجموع أوامر التغيير المعتمدة
            approved_vos = self.env['contract.variation.order'].search([
                ('project_id', '=', self.project_id.id),
                ('state', '=', 'approved'),
            ])
            self.approved_vo_amount = sum(approved_vos.mapped('approved_amount_total'))

    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('يجب إضافة بنود الشهادة قبل التقديم.'))
            rec.state = 'submitted'
        return True

    def action_approve(self):
        for rec in self:
            rec.state = 'approved'
        return True

    def action_cancel(self):
        for rec in self:
            if rec.move_id and rec.move_id.state == 'posted':
                raise UserError(_('لا يمكن إلغاء شهادة مربوطة بفاتورة مرحّلة. يرجى إلغاء الفاتورة أولاً.'))
            rec.state = 'cancelled'
        return True

    def action_draft(self):
        for rec in self:
            if rec.move_id:
                raise UserError(_('لا يمكن إرجاع للشهادة لمسودة بعد إصدار فاتورة.'))
            rec.state = 'draft'
        return True

    def action_create_invoice(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('يجب أن تكون الشهادة معتمدة قبل إصدار الفاتورة.'))
        if self.move_id:
            raise UserError(_('تم إصدار فاتورة لهذا الشهادة مسبقاً.'))
        if self.amount_due <= 0:
            raise UserError(_('صافي المستحق للدفع يجب أن يكون أكبر من الصفر.'))

        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            raise UserError(_('لا توجد يومية مبيعات متاحة لهذه الشركة.'))

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'project_id': self.project_id.id,
            'invoice_date': fields.Date.context_today(self),
            'journal_id': journal.id,
            'currency_id': self.currency_id.id,
            'ref': self.name,
            'invoice_line_ids': [(0, 0, {
                'name': _('شهادة دفع مرحلية %s - مشروع %s') % (self.name, self.project_id.name),
                'quantity': 1,
                'price_unit': self.amount_due,
                'account_id': self._get_sale_account().id,
            })],
        }
        move = self.env['account.move'].create(invoice_vals)
        self.move_id = move.id
        self.state = 'invoiced'
        return {
            'type': 'ir.actions.act_window',
            'name': _('فاتورة العميل'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': move.id,
        }

    def _get_sale_account(self):
        self.ensure_one()
        account = self.env['account.account'].search([
            ('account_type', '=', 'income'),
            ('company_ids', 'in', [self.company_id.id]),
        ], limit=1)
        if not account:
            raise UserError(_('لم يتم العثور على حساب إيرادات صالح لهذه الشركة. يرجى إعداد حسابات النظام المحاسبي.'))
        return account

    def action_view_invoice(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('لا توجد فاتورة مرتبطة بهذه الشهادة.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('فاتورة العميل'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }


class ContractProgressBillingLine(models.Model):
    _name = 'contract.progress.billing.line'
    _description = 'بنود شهادة الدفع المرحلية'
    _order = 'sequence, id'

    billing_id = fields.Many2one('contract.progress.billing', string='الشهادة', required=True,
                                 ondelete='cascade')
    sequence = fields.Integer(string='ترتيب', default=10)
    boq_item_id = fields.Many2one('boq.item', string='بند BOQ', required=True,
                                  domain="[('project_id', '=', parent.project_id), ('is_section', '=', False)]")
    project_id = fields.Many2one(related='billing_id.project_id', store=True)
    currency_id = fields.Many2one(related='billing_id.currency_id')

    planned_quantity = fields.Float(string='الكمية التعاقدية', related='boq_item_id.planned_quantity', readonly=True)
    unit_price = fields.Monetary(string='سعر الوحدة', related='boq_item_id.unit_price', readonly=True)
    contract_amount = fields.Monetary(string='قيمة البند التعاقدية', related='boq_item_id.planned_amount', readonly=True)

    previous_quantity = fields.Float(string='كمية منفذة في الشهادات السابقة')
    current_quantity = fields.Float(string='كمية منفذة هذه الشهادة', required=True)
    total_quantity_to_date = fields.Float(string='إجمالي الكمية حتى تاريخه',
                                          compute='_compute_quantities', store=True)
    certified_quantity = fields.Float(string='الكمية المعتمدة')
    certified_amount = fields.Monetary(string='المبلغ المعتمد', compute='_compute_amount', store=True)

    notes = fields.Char(string='ملاحظات')

    @api.depends('previous_quantity', 'current_quantity')
    def _compute_quantities(self):
        for rec in self:
            rec.total_quantity_to_date = (rec.previous_quantity or 0.0) + (rec.current_quantity or 0.0)

    @api.depends('certified_quantity', 'unit_price')
    def _compute_amount(self):
        for rec in self:
            rec.certified_amount = (rec.certified_quantity or 0.0) * (rec.unit_price or 0.0)

    @api.onchange('boq_item_id')
    def _onchange_boq_item_id(self):
        if self.boq_item_id:
            self.previous_quantity = 0.0
            self.current_quantity = 0.0
            self.certified_quantity = 0.0
