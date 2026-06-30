import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from enigma_tms.pricing import resolve_customer_rate


def execute(filters=None):
    filters = filters or {}
    conds = [["docstatus", "=", 1], ["suggested_detention_hours", ">", 0]]
    if filters.get("customer"):
        conds.append(["customer", "=", filters["customer"]])

    trips = frappe.get_all(
        "Trip", filters=conds,
        fields=["name", "customer", "route", "trailer_type", "status",
                "suggested_detention_hours", "actual_start"],
        order_by="creation desc",
    )
    data = []
    for t in trips:
        rate = resolve_customer_rate(t.customer, t.route, t.trailer_type,
                                     getdate(t.actual_start or today())) if t.route else None
        rate_per_hr = flt(rate.get("detention_rate_per_hour")) if rate else 0
        data.append({
            "trip": t.name, "customer": t.customer, "route": t.route, "status": t.status,
            "captured_hours": flt(t.suggested_detention_hours, 2),
            "rate_per_hour": rate_per_hr,
            "estimated_amount": flt(flt(t.suggested_detention_hours) * rate_per_hr, 2),
        })

    columns = [
        {"label": _("Trip"), "fieldname": "trip", "fieldtype": "Link", "options": "Trip", "width": 130},
        {"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 160},
        {"label": _("Route"), "fieldname": "route", "fieldtype": "Link", "options": "Transport Route", "width": 140},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": _("Captured Hours"), "fieldname": "captured_hours", "fieldtype": "Float", "width": 120},
        {"label": _("Ref Rate/Hr"), "fieldname": "rate_per_hour", "fieldtype": "Currency", "width": 110},
        {"label": _("Est. Amount (to bill)"), "fieldname": "estimated_amount", "fieldtype": "Currency", "width": 150},
    ]
    return columns, data
