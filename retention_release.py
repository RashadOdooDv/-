# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ContractRetentionRelease(models.Model):
    _name = 'contract.retention.release'
    _description = 'صرف حجز الضمان - Retention Release'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='رقم الطلب', required=True, copy=False, readonly=True, default=lambda self: _('جديد'))
    project_id = fields.Many2one(
        'project.project', string='المشروع', required=True, tracking=True,
        domain="[('is_contracting_project', '=', True)]", ondelete='restrict')
    partner_id = fields.Many2one('res.partner', string='المقاول/العميل', tracking=True)
    company_id = fields.Many2one('res.company', string='الشركة', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='العملة', required=True,
                                  default=lambda self: self.env.company.currency_id)

    date = fields.Date(string='التاريخ', required=True, default=fields.Date.context_today, tracking=True)
    release_amount = fields.Monetary(string='مبلغ الصرف', currency_field='currency_id', required=True)
    retention_balance = fields.Monetary(string='رصيد الضمان المتبقي', currency_field='currency_id',
                                        compute='_compute_balance')
    description = fields.Text(string='الوصف/ملاحظات')

    move_id = fields.Many2one('account.move', string='قيد الصرف', readonly=True, copy=False)

    state = fields.Selection([
        ('draft', 'مسودة'),
        ('requested', 'مُطلب'),
        ('approved', 'معتمد'),
        ('released', 'تم الصرف'),
        ('cancelled', 'ملغاة'),
    ], string='الحالة', default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('جديد')) == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code('contract.retention.release') or _('جديد')
        return super().create(vals_list)

    @api.depends('project_id')
    def _compute_balance(self):
        for rec in self:
            if not rec.project_id:
                rec.retention_balance = 0.0
                continue
            total_withheld = rec.project_id.total_retention_withheld or 0.0
            total_released = rec.project_id.total_retention_released or 0.0
            rec.retention_balance = total_withheld - total_released

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.partner_id = self.project_id.partner_id

    def action_request(self):
        self.write({'state': 'requested'})

    def action_approve(self):
        for rec in self:
            if rec.release_amount <= 0:
                raise UserError(_('مبلغ الصرف يجب أن يكون أكبر من الصفر.'))
            if rec.release_amount > rec.retention_balance:
                raise UserError(_('مبلغ الصرف أكبر من رصيد الضمان المتبقي.'))
            rec.state = 'approved'

    def action_release(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('يجب اعتماد الطلب قبل الصرف.'))
            if rec.move_id:
                raise UserError(_('تم إنشاء قيد الصرف مسبقاً.'))
            journal = self.env['account.journal'].search([
                ('type', '=', 'general'),
                ('company_id', '=', rec.company_id.id),
            ], limit=1)
            if not journal:
                raise UserError(_('لا توجد يومية عامة متاحة لصرف حجز الضمان.'))
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': rec.date,
                'ref': rec.name,
                'project_id': rec.project_id.id,
                'line_ids': [
                    (0, 0, {
                        'name': _('صرف حجز الضمان - %s') % rec.project_id.name,
                        'account_id': rec._get_retention_account().id,
                        'debit': rec.release_amount,
                        'credit': 0.0,
                        'partner_id': rec.partner_id.id,
                    }),
                    (0, 0, {
                        'name': _('صرف حجز الضمان - %s') % rec.project_id.name,
                        'account_id': rec._get_payable_account().id,
                        'debit': 0.0,
                        'credit': rec.release_amount,
                        'partner_id': rec.partner_id.id,
                    }),
                ],
            })
            move.action_post()
            rec.move_id = move.id
            rec.state = 'released'

    def action_cancel(self):
        for rec in self:
            if rec.move_id and rec.move_id.state == 'posted':
                raise UserError(_('لا يمكن إلغاء طلب مرتبط بقيد مرحّل. يرجى إلغاء القيد أولاً.'))
            rec.state = 'cancelled'

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('لا يوجد قيد صرف مرتبط.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('قيد صرف حجز الضمان'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def _get_retention_account(self):
        self.ensure_one()
        account = self.env['account.account'].search([
            ('account_type', '=', 'asset_current'),
            ('company_ids', 'in', [self.company_id.id]),
        ], limit=1)
        if not account:
            raise UserError(_('يرجى إعداد حساب حجز الضمان (أصول متداولة) المناسب.'))
        return account

    def _get_payable_account(self):
        self.ensure_one()
        account = self.env['account.account'].search([
            ('account_type', '=', 'liability_payable'),
            ('company_ids', 'in', [self.company_id.id]),
        ], limit=1)
        if not account:
            raise UserError(_('يرجى إعداد حساب الدائنين المناسب.'))
        return account
