import frappe
from frappe import _


def execute(filters=None):
    filters = filters or {}
    values = {}
    extra = ""
    if filters.get("subcontractor"):
        extra = "and t.subcontractor = %(subcontractor)s"
        values["subcontractor"] = filters["subcontractor"]

    rows = frappe.db.sql(
        f"""
        select t.name as trip, t.subcontractor as subcontractor, t.transport_order as transport_order,
               t.status as status,
               (select sum(c.amount) from `tabTrip Cost` c
                  where c.parent = t.name and c.cost_type = 'Subcontractor') as sub_cost,
               (select count(*) from `tabPurchase Invoice` pi
                  where pi.custom_trip = t.name and pi.docstatus = 1) as pi_count
        from `tabTrip` t
        where t.docstatus = 1 and t.ownership = 'Outsourced' {extra}
        having sub_cost > 0 and pi_count = 0
        order by t.creation asc
        """, values, as_dict=True,
    )
    columns = [
        {"label": _("Trip"), "fieldname": "trip", "fieldtype": "Link", "options": "Trip", "width": 130},
        {"label": _("Subcontractor"), "fieldname": "subcontractor", "fieldtype": "Link", "options": "Supplier", "width": 180},
        {"label": _("Order"), "fieldname": "transport_order", "fieldtype": "Link", "options": "Transport Order", "width": 150},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
        {"label": _("Subcontractor Cost"), "fieldname": "sub_cost", "fieldtype": "Currency", "width": 150},
    ]
    return columns, rows
