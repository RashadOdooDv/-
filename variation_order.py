# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ContractVariationOrder(models.Model):
    _name = 'contract.variation.order'
    _description = 'أمر التغيير (Variation Order - VO)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='رقم أمر التغيير', required=True, copy=False, readonly=True, default=lambda self: _('جديد'))
    project_id = fields.Many2one(
        'project.project', string='المشروع', required=True, tracking=True,
        domain="[('is_contracting_project', '=', True)]", ondelete='restrict')
    partner_id = fields.Many2one('res.partner', string='العميل', tracking=True, ondelete='restrict')
    company_id = fields.Many2one('res.company', string='الشركة', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='العملة', required=True,
                                  default=lambda self: self.env.company.currency_id)

    date = fields.Date(string='التاريخ', required=True, default=fields.Date.context_today, tracking=True)
    reference = fields.Char(string='مرجع خارجي')
    description = fields.Text(string='الوصف')

    line_ids = fields.One2many('contract.variation.order.line', 'vo_id', string='بنود أمر التغيير')

    requested_amount_total = fields.Monetary(string='المبلغ المطلوب إجمالي', currency_field='currency_id',
                                             compute='_compute_amounts', store=True)
    approved_amount_total = fields.Monetary(string='المبلغ المعتمد إجمالي', currency_field='currency_id',
                                           compute='_compute_amounts', store=True)

    state = fields.Selection([
        ('draft', 'مسودة'),
        ('submitted', 'مُقدم'),
        ('approved', 'معتمد'),
        ('refused', 'مرفوض'),
        ('cancelled', 'ملغاة'),
    ], string='الحالة', default='draft', tracking=True)

    notes = fields.Text(string='ملاحظات')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('جديد')) == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code('contract.variation.order') or _('جديد')
        return super().create(vals_list)

    @api.depends('line_ids.requested_amount', 'line_ids.approved_amount')
    def _compute_amounts(self):
        for rec in self:
            rec.requested_amount_total = sum(rec.line_ids.mapped('requested_amount'))
            rec.approved_amount_total = sum(rec.line_ids.mapped('approved_amount'))

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.partner_id = self.project_id.partner_id

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        for rec in self:
            if any(line.approved_amount == 0 and line.requested_amount != 0 for line in rec.line_ids):
                raise UserError(_('هناك بنود طلب تغيير ولم يُحدد المبلغ المعتمد لها.'))
            rec.state = 'approved'

    def action_refuse(self):
        self.write({'state': 'refused'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_draft(self):
        self.write({'state': 'draft'})


class ContractVariationOrderLine(models.Model):
    _name = 'contract.variation.order.line'
    _description = 'بنود أمر التغيير'
    _order = 'sequence, id'

    vo_id = fields.Many2one('contract.variation.order', string='أمر التغيير', required=True, ondelete='cascade')
    sequence = fields.Integer(string='ترتيب', default=10)
    boq_item_id = fields.Many2one('boq.item', string='بند BOQ',
                                  domain="[('project_id', '=', parent.project_id), ('is_section', '=', False)]")
    project_id = fields.Many2one(related='vo_id.project_id', store=True)
    currency_id = fields.Many2one(related='vo_id.currency_id')

    description = fields.Char(string='الوصف')
    requested_quantity = fields.Float(string='الكمية المطلوبة')
    requested_amount = fields.Monetary(string='المبلغ المطلوب', currency_field='currency_id')
    approved_quantity = fields.Float(string='الكمية المعتمدة')
    approved_amount = fields.Monetary(string='المبلغ المعتمد', currency_field='currency_id')

    @api.onchange('boq_item_id')
    def _onchange_boq_item_id(self):
        if self.boq_item_id:
            self.description = self.boq_item_id.display_name
