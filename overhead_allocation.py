# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class OverheadAllocation(models.Model):
    _name = 'overhead.allocation'
    _description = 'توزيع المصاريف الإدارية على بنود BOQ (Overhead Allocation)'
    _order = 'date desc, id desc'

    name = fields.Char(string='المرجع', required=True, copy=False, default=lambda self: _('جديد'))
    date = fields.Date(string='تاريخ التوزيع', default=fields.Date.context_today, required=True)

    scope = fields.Selection([
        ('general', 'مصروف عام (يوزَّع على كل المشاريع)'),
        ('project', 'مصروف خاص بمشروع محدد'),
    ], string='نطاق التوزيع', required=True, default='project', tracking=True)

    project_id = fields.Many2one(
        'project.project', string='المشروع',
        domain="[('is_contracting_project', '=', True)]")

    allocation_basis = fields.Selection([
        ('value', 'حسب القيمة التعاقدية للبند (Value)'),
        ('quantity', 'حسب الكمية المخططة (Quantity)'),
    ], string='أساس التوزيع', required=True, default='value')

    source_move_line_id = fields.Many2one(
        'account.move.line', string='المصروف المراد توزيعه', required=True,
        domain="[('is_general_expense', '=', True), ('overhead_allocated', '=', False),"
               " ('parent_state', '=', 'posted'), ('company_id', '=', company_id)]",
        help='اختر سطر القيد/الفاتورة الذي تم تصنيفه سابقًا كـ"مصروف عمومي غير مخصص".')
    amount_to_allocate = fields.Monetary(
        string='المبلغ المطلوب توزيعه', compute='_compute_amount', store=True)
    currency_id = fields.Many2one(
        'res.currency', related='source_move_line_id.company_currency_id', store=True, string='العملة')

    line_ids = fields.One2many('overhead.allocation.line', 'allocation_id', string='تفاصيل التوزيع')
    move_id = fields.Many2one('account.move', string='قيد إعادة التخصيص', readonly=True, copy=False)

    state = fields.Selection([
        ('draft', 'مسودة'),
        ('computed', 'تم الحساب'),
        ('done', 'مرحّل'),
    ], string='الحالة', default='draft', copy=False, tracking=True)

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    _sql_constraints = [
        ('source_move_line_uniq', 'unique(source_move_line_id)',
         'لا يمكن استخدام سطر المصروف نفسه في أكثر من عملية توزيع.'),
    ]

    # -------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('جديد')) == _('جديد'):
                vals['name'] = self.env['ir.sequence'].next_by_code('overhead.allocation') or _('جديد')
        return super().create(vals_list)

    @api.depends('source_move_line_id.debit', 'source_move_line_id.credit')
    def _compute_amount(self):
        for rec in self:
            line = rec.source_move_line_id
            rec.amount_to_allocate = line.debit - line.credit if line else 0.0

    @api.constrains('company_id', 'project_id', 'source_move_line_id')
    def _check_allocation_company(self):
        for rec in self:
            if rec.project_id and rec.project_id.company_id != rec.company_id:
                raise ValidationError(_('يجب أن يتبع المشروع شركة عملية التوزيع.'))
            if rec.source_move_line_id and rec.source_move_line_id.company_id != rec.company_id:
                raise ValidationError(_('يجب أن يتبع سطر المصروف شركة عملية التوزيع.'))

    @api.onchange('scope')
    def _onchange_scope(self):
        if self.scope == 'general':
            self.project_id = False

    # -------------------------------------------------------------
    def _get_target_boq_items(self):
        self.ensure_one()
        domain = [('is_section', '=', False), ('company_id', '=', self.company_id.id)]
        if self.scope == 'project':
            if not self.project_id:
                raise ValidationError(_('الرجاء تحديد المشروع عند اختيار نطاق "خاص بمشروع محدد".'))
            domain.append(('project_id', '=', self.project_id.id))
        else:
            domain.append(('project_id.is_contracting_project', '=', True))
        return self.env['boq.item'].search(domain)

    def action_compute_lines(self):
        for rec in self:
            if rec.state not in ('draft', 'computed'):
                raise UserError(_('لا يمكن إعادة حساب عملية توزيع تم ترحيلها.'))
            rec._check_source_move_line()
            rec.line_ids.unlink()
            items = rec._get_target_boq_items()
            if not items:
                raise UserError(_('لا توجد بنود BOQ مؤهلة للتوزيع ضمن هذا النطاق.'))

            weight_field = 'planned_amount' if rec.allocation_basis == 'value' else 'planned_quantity'
            total_weight = sum(items.mapped(weight_field))
            if not total_weight:
                raise UserError(_('لا يمكن التوزيع لأن إجمالي أساس التوزيع (القيمة/الكمية) للبنود المستهدفة = صفر.'))

            items_list = list(items)
            allocated_so_far = 0.0
            lines_vals = []
            currency = rec.currency_id or rec.company_id.currency_id
            for i, item in enumerate(items_list):
                weight = getattr(item, weight_field) or 0.0
                if i == len(items_list) - 1:
                    # آخر بند يستوعب فرق التقريب حتى يتطابق الإجمالي 100%
                    amount = rec.amount_to_allocate - allocated_so_far
                else:
                    amount = currency.round(rec.amount_to_allocate * (weight / total_weight))
                allocated_so_far += amount
                lines_vals.append((0, 0, {
                    'boq_item_id': item.id,
                    'weight': weight,
                    'weight_percent': (weight / total_weight * 100.0) if total_weight else 0.0,
                    'allocated_amount': amount,
                }))
            rec.line_ids = lines_vals
            rec.state = 'computed'

    def action_post_allocation(self):
        for rec in self:
            if rec.state != 'computed' or not rec.line_ids:
                raise UserError(_('يجب الضغط على "حساب التوزيع" أولًا قبل الترحيل.'))
            if rec.move_id:
                raise UserError(_('تم إنشاء قيد لهذه العملية بالفعل.'))
            rec._check_source_move_line()
            source = rec.source_move_line_id
            if any(line.boq_item_id.company_id != rec.company_id for line in rec.line_ids):
                raise ValidationError(_('يجب أن تتبع كل بنود BOQ شركة عملية التوزيع.'))

            debit_lines = [(0, 0, {
                'name': _('توزيع مصروف - %s') % (line.boq_item_id.display_name,),
                'account_id': source.account_id.id,
                'debit': line.allocated_amount if line.allocated_amount > 0 else 0.0,
                'credit': -line.allocated_amount if line.allocated_amount < 0 else 0.0,
                'boq_item_id': line.boq_item_id.id,
                'project_id': line.boq_item_id.project_id.id,
                'partner_id': source.partner_id.id,
            }) for line in rec.line_ids]

            credit_line = (0, 0, {
                'name': _('عكس مصروف عمومي تم توزيعه - %s') % (source.name or source.move_id.name or ''),
                'account_id': source.account_id.id,
                'debit': rec.amount_to_allocate if rec.amount_to_allocate < 0 else 0.0,
                'credit': rec.amount_to_allocate if rec.amount_to_allocate > 0 else 0.0,
                'is_general_expense': True,
                'project_id': rec.project_id.id if rec.scope == 'project' else False,
                'partner_id': source.partner_id.id,
            })

            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': rec._get_allocation_journal().id,
                'date': rec.date,
                'ref': _('توزيع مصروف عمومي: %s') % (source.name or source.move_id.name or ''),
                'project_id': rec.project_id.id if rec.scope == 'project' else False,
                'line_ids': debit_lines + [credit_line],
            })
            move.action_post()

            source.overhead_allocated = True
            rec.move_id = move.id
            rec.state = 'done'

    def _check_source_move_line(self):
        self.ensure_one()
        source = self.source_move_line_id
        if (
            not source
            or source.parent_state != 'posted'
            or not source.is_general_expense
            or source.overhead_allocated
            or source.company_id != self.company_id
            or source.account_id.account_type not in (
                'expense', 'expense_depreciation', 'expense_direct_cost',
            )
        ):
            raise ValidationError(_(
                'سطر المصدر يجب أن يكون مصروفًا عموميًا مرحّلًا وغير موزع، '
                'ومن شركة عملية التوزيع نفسها.'
            ))

    def _get_allocation_journal(self):
        journal = self.env['account.journal'].search([
            ('type', '=', 'general'), ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            raise UserError(_('لا توجد يومية عامة (Miscellaneous Operations) متاحة في هذه الشركة لترحيل قيد التوزيع.'))
        return journal

    def action_view_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('قيد إعادة التخصيص'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def action_reset_to_draft(self):
        for rec in self:
            if rec.move_id:
                raise UserError(_('لا يمكن إعادة هذا التوزيع إلى مسودة بعد ترحيله. قم بإلغاء قيد إعادة التخصيص أولًا.'))
            rec.line_ids.unlink()
            rec.state = 'draft'


class OverheadAllocationLine(models.Model):
    _name = 'overhead.allocation.line'
    _description = 'سطر تفاصيل توزيع المصروف الإداري'

    allocation_id = fields.Many2one('overhead.allocation', required=True, ondelete='cascade')
    boq_item_id = fields.Many2one('boq.item', string='بند BOQ', required=True)
    project_id = fields.Many2one(related='boq_item_id.project_id', string='المشروع', store=True)
    weight = fields.Float(string='الوزن (قيمة/كمية)')
    weight_percent = fields.Float(string='نسبة التوزيع %')
    allocated_amount = fields.Monetary(string='المبلغ الموزّع')
    currency_id = fields.Many2one(related='allocation_id.currency_id')
