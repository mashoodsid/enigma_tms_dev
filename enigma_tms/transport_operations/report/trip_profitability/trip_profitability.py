import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    conditions = [["docstatus", "=", 1], ["status", "!=", "Cancelled"]]
    if filters.get("customer"):
        conditions.append(["customer", "=", filters["customer"]])
    if filters.get("ownership"):
        conditions.append(["ownership", "=", filters["ownership"]])
    if filters.get("from_date"):
        conditions.append(["creation", ">=", filters["from_date"]])
    if filters.get("to_date"):
        conditions.append(["creation", "<=", filters["to_date"] + " 23:59:59"])

    rows = frappe.get_all(
        "Trip", filters=conditions,
        fields=["name", "customer", "route", "status", "ownership", "tractor", "trailer",
                "selling_amount", "buying_total", "trip_profit"],
        order_by="creation desc",
    )
    for r in rows:
        r["margin_pct"] = flt(r.trip_profit / r.selling_amount * 100, 1) if r.selling_amount else 0

    columns = [
        {"label": _("Trip"), "fieldname": "name", "fieldtype": "Link", "options": "Trip", "width": 130},
        {"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
        {"label": _("Route"), "fieldname": "route", "fieldtype": "Link", "options": "Transport Route", "width": 130},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": _("Ownership"), "fieldname": "ownership", "fieldtype": "Data", "width": 90},
        {"label": _("Tractor"), "fieldname": "tractor", "fieldtype": "Link", "options": "Tractor", "width": 90},
        {"label": _("Trailer"), "fieldname": "trailer", "fieldtype": "Link", "options": "Trailer", "width": 90},
        {"label": _("Selling"), "fieldname": "selling_amount", "fieldtype": "Currency", "width": 110},
        {"label": _("Buying"), "fieldname": "buying_total", "fieldtype": "Currency", "width": 110},
        {"label": _("Profit"), "fieldname": "trip_profit", "fieldtype": "Currency", "width": 110},
        {"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 90},
    ]
    return columns, rows
