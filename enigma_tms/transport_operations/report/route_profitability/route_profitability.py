import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    conds = ["t.docstatus = 1", "t.status != 'Cancelled'", "t.route is not null"]
    values = {}
    if filters.get("from_date"):
        conds.append("t.creation >= %(from_date)s")
        values["from_date"] = filters["from_date"]
    if filters.get("to_date"):
        conds.append("t.creation <= %(to_date)s")
        values["to_date"] = filters["to_date"] + " 23:59:59"
    where = " and ".join(conds)

    rows = frappe.db.sql(
        f"""
        select t.route as route,
               count(t.name) as trips,
               sum(t.selling_amount) as selling,
               sum(t.buying_total) as buying,
               sum(t.trip_profit) as profit
        from `tabTrip` t
        where {where}
        group by t.route
        order by profit desc
        """, values, as_dict=True,
    )
    for r in rows:
        r["margin_pct"] = flt(r.profit / r.selling * 100, 1) if r.selling else 0

    columns = [
        {"label": _("Route"), "fieldname": "route", "fieldtype": "Link", "options": "Transport Route", "width": 220},
        {"label": _("Trips"), "fieldname": "trips", "fieldtype": "Int", "width": 80},
        {"label": _("Selling"), "fieldname": "selling", "fieldtype": "Currency", "width": 130},
        {"label": _("Buying"), "fieldname": "buying", "fieldtype": "Currency", "width": 130},
        {"label": _("Profit"), "fieldname": "profit", "fieldtype": "Currency", "width": 130},
        {"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 90},
    ]
    return columns, rows
