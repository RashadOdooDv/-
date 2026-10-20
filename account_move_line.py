# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    project_id = fields.Many2one(
        'project.project', string='المشروع', index=True,
        help='المشروع الهندسي المرتبط بهذا البند. يُستخدم لتصفية بنود BOQ المتاحة.')
    boq_item_id = fields.Many2one(
        'boq.item', string='بند BOQ', index=True,
        domain="[('project_id', '=', project_id), ('is_section', '=', False)]",
        help='بند جدول الكميات الذي يُحمَّل عليه هذا المصروف/الإيراد.')
    is_general_expense = fields.Boolean(
        string='مصروف عمومي غير مخصص لمشروع',
        help='فعّل هذا الخيار صراحة إذا كان هذا البند مصروفًا عموميًا لا يخص مشروعًا أو بندًا محددًا '
             '(مثال: مصاريف إدارية عامة للشركة).')
    overhead_allocated = fields.Boolean(
        string='تم توزيعه على البنود', default=False, copy=False,
        help='يُفعَّل تلقائيًا بعد توزيع هذا المصروف العمومي على بنود BOQ عبر معالج التوزيع، '
             'لمنع توزيعه مرتين.')

    # -------------------------------------------------------------
    @api.onchange('boq_item_id')
    def _onchange_boq_item_id(self):
        if self.boq_item_id:
            self.project_id = self.boq_item_id.project_id
            self.is_general_expense = False

    @api.onchange('is_general_expense')
    def _onchange_is_general_expense(self):
        if self.is_general_expense:
            self.boq_item_id = False

    @api.model_create_multi
    def create(self, vals_list):
        boq_item_ids = [vals.get('boq_item_id') for vals in vals_list if vals.get('boq_item_id')]
        boq_items = {item.id: item for item in self.env['boq.item'].browse(boq_item_ids).exists()}
        for vals in vals_list:
            item = boq_items.get(vals.get('boq_item_id'))
            if item and not vals.get('project_id'):
                vals['project_id'] = item.project_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('boq_item_id') and 'project_id' not in vals:
            item = self.env['boq.item'].browse(vals['boq_item_id']).exists()
            if item:
                vals = {**vals, 'project_id': item.project_id.id}
        return super().write(vals)

    @api.constrains('project_id', 'boq_item_id', 'is_general_expense')
    def _check_boq_project(self):
        for line in self:
            if line.boq_item_id and line.is_general_expense:
                raise ValidationError(_('لا يمكن ربط السطر ببند BOQ وتصنيفه كمصروف عمومي في الوقت نفسه.'))
            if line.boq_item_id and line.project_id != line.boq_item_id.project_id:
                raise ValidationError(_('يجب أن ينتمي بند BOQ والمشروع المحدد في السطر إلى المشروع نفسه.'))
