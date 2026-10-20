# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class BOQItem(models.Model):
    _name = 'boq.item'
    _description = 'بند جدول الكميات (BOQ Item)'
    _order = 'sequence, code'
    _parent_store = True
    _rec_name = 'display_name'

    # -------------------------------------------------------------
    # الحقول الأساسية
    # -------------------------------------------------------------
    sequence = fields.Integer(string='الترتيب', default=10)
    project_id = fields.Many2one(
        'project.project', string='المشروع', required=True,
        ondelete='cascade', index=True)
    code = fields.Char(string='الكود', required=True)
    name = fields.Char(string='وصف البند', required=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    # الهيكل الهرمي (أقسام رئيسية <-> بنود فرعية)
    parent_id = fields.Many2one(
        'boq.item', string='القسم الرئيسي', ondelete='cascade', index=True)
    child_ids = fields.One2many('boq.item', 'parent_id', string='البنود الفرعية')
    parent_path = fields.Char(index=True, unaccent=False)
    is_section = fields.Boolean(
        string='قسم رئيسي (بدون تسعير)', default=False,
        help='حدد هذا الخيار إذا كان البند عنوان قسم فقط ولا يحمل كمية/سعر مباشر.')

    # الكميات والتسعير (غير مطلوبة إذا كان البند قسمًا رئيسيًا)
    uom_id = fields.Many2one('uom.uom', string='وحدة القياس')
    planned_quantity = fields.Float(string='الكمية المخططة', digits='Product Unit of Measure')
    unit_price = fields.Monetary(string='سعر الوحدة')
    planned_amount = fields.Monetary(
        string='القيمة المخططة (العقد)', compute='_compute_planned_amount', store=True)

    # التنفيذ الفعلي
    executed_quantity = fields.Float(string='الكمية المنفذة فعلياً', digits='Product Unit of Measure')
    completion_percent = fields.Float(
        string='نسبة الإنجاز %', compute='_compute_completion', store=True)

    # الربط المحاسبي
    move_line_ids = fields.One2many(
        'account.move.line', 'boq_item_id', string='الحركات المحاسبية المرتبطة')
    actual_cost = fields.Monetary(
        string='التكلفة الفعلية', compute='_compute_actual_cost', store=True,
        help='مجموع كل الحركات المحاسبية المرحّلة والمرتبطة بهذا البند.')
    cost_variance = fields.Monetary(
        string='الانحراف (المخطط - الفعلي)', compute='_compute_actual_cost', store=True)
    cost_variance_percent = fields.Float(
        string='نسبة استهلاك الميزانية %', compute='_compute_actual_cost', store=True)
    budget_alert_level = fields.Selection([
        ('normal', 'طبيعي'),
        ('warning', 'تحذير (85%+)'),
        ('exceeded', 'تجاوز الميزانية'),
    ], string='حالة الميزانية', compute='_compute_actual_cost', store=True)

    currency_id = fields.Many2one(
        'res.currency', related='project_id.company_id.currency_id', store=True, string='العملة')
    company_id = fields.Many2one(
        'res.company', related='project_id.company_id', store=True, string='الشركة')

    _sql_constraints = [
        ('code_project_uniq', 'unique(code, project_id)',
         'كود البند يجب أن يكون فريدًا داخل نفس المشروع.'),
    ]

    # -------------------------------------------------------------
    # المحسوبات
    # -------------------------------------------------------------
    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'[{rec.code}] {rec.name}' if rec.code else rec.name

    @api.depends('planned_quantity', 'unit_price')
    def _compute_planned_amount(self):
        for rec in self:
            rec.planned_amount = (rec.planned_quantity or 0.0) * (rec.unit_price or 0.0)

    @api.depends(
        'planned_quantity', 'executed_quantity',
        'child_ids.completion_percent', 'child_ids.planned_amount',
    )
    def _compute_completion(self):
        for rec in self:
            if rec.child_ids:
                # القسم الرئيسي: متوسط مرجّح بقيمة البنود الفرعية
                total_planned = sum(rec.child_ids.mapped('planned_amount')) or 1.0
                rec.completion_percent = sum(
                    c.completion_percent * c.planned_amount for c in rec.child_ids
                ) / total_planned
            else:
                rec.completion_percent = (
                    (rec.executed_quantity / rec.planned_quantity) * 100.0
                    if rec.planned_quantity else 0.0
                )

    @api.depends('move_line_ids.debit', 'move_line_ids.credit',
                 'move_line_ids.parent_state', 'planned_amount',
                 'child_ids.actual_cost')
    def _compute_actual_cost(self):
        for rec in self:
            if rec.child_ids:
                actual = sum(rec.child_ids.mapped('actual_cost'))
            else:
                actual = sum(
                    (line.debit - line.credit) for line in rec.move_line_ids
                    if line.parent_state == 'posted'
                )
            rec.actual_cost = actual
            rec.cost_variance = rec.planned_amount - actual
            rec.cost_variance_percent = (
                (actual / rec.planned_amount) * 100.0 if rec.planned_amount else 0.0
            )
            if rec.cost_variance_percent >= 100:
                rec.budget_alert_level = 'exceeded'
            elif rec.cost_variance_percent >= 85:
                rec.budget_alert_level = 'warning'
            else:
                rec.budget_alert_level = 'normal'

    # -------------------------------------------------------------
    # القيود (Constraints)
    # -------------------------------------------------------------
    @api.constrains('planned_quantity', 'unit_price')
    def _check_positive_values(self):
        for rec in self:
            if rec.planned_quantity < 0 or rec.unit_price < 0:
                raise ValidationError(_('لا يمكن أن تكون الكمية أو سعر الوحدة بقيمة سالبة.'))

    @api.constrains('parent_id', 'project_id', 'is_section')
    def _check_parent_recursion(self):
        if not self._check_recursion():
            raise ValidationError(_('لا يمكن إنشاء تسلسل هرمي دائري بين بنود BOQ.'))
        for item in self:
            if item.parent_id and item.parent_id.project_id != item.project_id:
                raise ValidationError(_('يجب أن ينتمي البند والقسم الرئيسي إلى المشروع نفسه.'))
            if item.parent_id and not item.parent_id.is_section:
                raise ValidationError(_('لا يمكن إضافة بنود فرعية إلا تحت قسم رئيسي.'))
            if item.child_ids and not item.is_section:
                raise ValidationError(_('لا يمكن تحويل قسم يحتوي على بنود فرعية إلى بند عادي.'))
            if any(child.project_id != item.project_id for child in item.child_ids):
                raise ValidationError(_('يجب أن تنتمي كل البنود الفرعية إلى مشروع القسم نفسه.'))

    @api.onchange('is_section')
    def _onchange_is_section(self):
        if self.is_section:
            self.planned_quantity = 0.0
            self.unit_price = 0.0
