# -*- coding: utf-8 -*-
{
    'name': 'إدارة المقاولات الهندسية - Contracting Management',
    'version': '19.0.1.0.0',
    'summary': 'نظام متكامل لإدارة المقاولات الهندسية: BOQ، ربط محاسبي إجباري، تتبع الربحية والانحرافات',
    'description': """
إدارة المقاولات الهندسية (Contracting Management)
====================================================
موديول مخصص لشركات المقاولات في الخليج ومصر واليمن، يبنى فوق أودو 19 مباشرة:

* جدول كميات (BOQ) هرمي لكل مشروع.
* ربط إجباري بين كل حركة مصروف/فاتورة وبند BOQ (أو تصنيفها كمصروف عمومي صراحة).
* كشف الحركات المحاسبية غير المسندة لأي مشروع أو بند.
* تقارير ربحية تفاعلية (Pivot / Graph) على غرار أدوات BI الحديثة.
* جاهز للعمل بأي عملة خليجية (SAR, AED, KWD, QAR, OMR, BHD) وكذلك EGP و YER.

هذه هي المرحلة الأولى (Phase 1) من خارطة طريق أشمل تغطي التوزيع الآلي للمصاريف،
الميزانيات، التقارير اليومية للموقع، المعدات، والاستقطاعات.
    """,
    'author': 'Odoo Contracting Solutions',
    'license': 'LGPL-3',
    'category': 'Industries/Construction',
    'depends': ['base', 'account', 'project', 'analytic'],
    'data': [
        'security/contracting_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'views/boq_item_views.xml',
        'views/contract_project_views.xml',
        'views/account_move_views.xml',
        'views/boq_line_analysis_views.xml',
        'views/overhead_allocation_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'sequence': 5,
}
