import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    conds = ["tr.ownership = 'Owned'", "t.docstatus = 1", "t.status != 'Cancelled'"]
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
        select tr.name as tractor,
               tr.plate_number as plate_number,
               count(t.name) as trips,
               sum(t.actual_distance) as total_km,
               sum(t.trip_profit) as profit,
               max(t.actual_end) as last_trip
        from `tabTractor` tr
        left join `tabTrip` t
            on t.tractor = tr.name and {where}
        where tr.ownership = 'Owned'
        group by tr.name
        order by trips desc
        """, values, as_dict=True,
    )
    columns = [
        {"label": _("Tractor"), "fieldname": "tractor", "fieldtype": "Link", "options": "Tractor", "width": 110},
        {"label": _("Plate"), "fieldname": "plate_number", "fieldtype": "Data", "width": 120},
        {"label": _("Trips"), "fieldname": "trips", "fieldtype": "Int", "width": 80},
        {"label": _("Total km"), "fieldname": "total_km", "fieldtype": "Float", "width": 110},
        {"label": _("Profit"), "fieldname": "profit", "fieldtype": "Currency", "width": 130},
        {"label": _("Last Trip"), "fieldname": "last_trip", "fieldtype": "Datetime", "width": 160},
    ]
    return columns, rows
