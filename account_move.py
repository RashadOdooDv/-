# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

# أنواع الحسابات التي يجب أن تُسند إجباريًا لبند BOQ أو تُصنَّف كمصروف عمومي صراحة
CONTROLLED_ACCOUNT_TYPES = (
    'expense',
    'expense_depreciation',
    'expense_direct_cost',
)
# أنواع البنود التي لا تخضع للتحقق (فواصل/ملاحظات/شروط الدفع)
EXCLUDED_DISPLAY_TYPES = ('line_section', 'line_note', 'payment_term')


class AccountMove(models.Model):
    _inherit = 'account.move'

    project_id = fields.Many2one(
        'project.project', string='المشروع', tracking=True,
        domain="[('is_contracting_project', '=', True)]",
        help='حدد المشروع الهندسي المرتبط بهذا المستند لتسهيل اختيار بنود BOQ في السطور.')

    def _post(self, soft=True):
        self._check_boq_allocation_required()
        return super()._post(soft=soft)

    def _check_boq_allocation_required(self):
        """يمنع ترحيل أي قيد/فاتورة تحتوي على سطر مصروف غير مرتبط ببند BOQ
        وغير مُصنَّف صراحةً كمصروف عمومي."""
        for move in self:
            mismatched_lines = move.line_ids.filtered(
                lambda line: line.boq_item_id and (
                    line.boq_item_id.project_id.company_id != move.company_id
                    or (move.project_id and line.boq_item_id.project_id != move.project_id)
                )
            )
            if mismatched_lines:
                raise UserError(_(
                    'لا يمكن ترحيل المستند لأن بند BOQ يجب أن يتبع شركة المستند '
                    'ومشروعه المحدد.'
                ))

            conflicting_lines = move.line_ids.filtered(
                lambda line: line.boq_item_id and line.is_general_expense
            )
            if conflicting_lines:
                raise UserError(_(
                    'لا يمكن تصنيف السطر نفسه كبند BOQ ومصروف عمومي في الوقت نفسه.'
                ))

            offending_lines = move.line_ids.filtered(
                lambda l: l.display_type not in EXCLUDED_DISPLAY_TYPES
                and l.account_id
                and l.account_id.account_type in CONTROLLED_ACCOUNT_TYPES
                and not l.boq_item_id
                and not l.is_general_expense
            )
            if offending_lines:
                accounts = ', '.join(offending_lines.mapped('account_id.display_name'))
                raise UserError(_(
                    'لا يمكن ترحيل هذا المستند (%(move)s) لأن السطور التالية غير مرتبطة '
                    'ببند BOQ ولم تُحدَّد كمصروف عمومي:\n%(accounts)s\n\n'
                    'الرجاء تحديد "بند BOQ" أو تفعيل خيار "مصروف عمومي غير مخصص لمشروع" '
                    'لكل سطر مصروف قبل الترحيل.'
                ) % {'move': move.name or move.ref or _('مسودة'), 'accounts': accounts})
