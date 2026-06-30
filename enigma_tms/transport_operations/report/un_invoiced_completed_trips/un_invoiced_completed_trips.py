import frappe
from frappe import _


def execute(filters=None):
    filters = filters or {}
    values = {}
    extra = ""
    if filters.get("customer"):
        extra = "and t.customer = %(customer)s"
        values["customer"] = filters["customer"]

    rows = frappe.db.sql(
        f"""
        select t.name as trip, t.transport_order as transport_order, t.customer as customer,
               t.selling_amount as selling_amount, t.actual_end as completed_on,
               (select count(*) from `tabSales Invoice` si
                  where si.custom_transport_order = t.transport_order and si.docstatus = 1) as order_invoices
        from `tabTrip` t
        where t.docstatus = 1 and t.status = 'Completed' {extra}
        having order_invoices = 0
        order by t.actual_end asc
        """, values, as_dict=True,
    )
    columns = [
        {"label": _("Trip"), "fieldname": "trip", "fieldtype": "Link", "options": "Trip", "width": 130},
        {"label": _("Order"), "fieldname": "transport_order", "fieldtype": "Link", "options": "Transport Order", "width": 150},
        {"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 170},
        {"label": _("Selling"), "fieldname": "selling_amount", "fieldtype": "Currency", "width": 120},
        {"label": _("Completed On"), "fieldname": "completed_on", "fieldtype": "Datetime", "width": 160},
    ]
    return columns, rows
