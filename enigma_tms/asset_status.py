"""Derived asset status (§3.6).

`Tractor.status` / `Trailer.status` are display-only convenience fields,
recomputed from Trip records. Double-booking is enforced by the Trip overlap
validation (§5.2), NOT by reading these flags.
"""

import frappe
from frappe.utils import now_datetime


def recompute_asset_status(asset_doctype, asset_name):
    """Set status to On Trip when a submitted Trip covers 'now'; otherwise leave
    manual states (Under Maintenance / Inactive) untouched and default Available.
    """
    if not asset_name:
        return

    current = frappe.db.get_value(asset_doctype, asset_name, "status")
    # Never auto-override manually-set unavailable states.
    if current in ("Under Maintenance", "Inactive"):
        return

    field = "tractor" if asset_doctype == "Tractor" else "trailer"
    now = now_datetime()

    on_trip = frappe.db.exists(
        "Trip",
        {
            field: asset_name,
            "docstatus": 1,
            "status": ["in", ["In Transit"]],
            "actual_start": ["<=", now],
        },
    )
    new_status = "On Trip" if on_trip else "Available"
    if new_status != current:
        frappe.db.set_value(asset_doctype, asset_name, "status", new_status, update_modified=False)


def has_overlap(asset_doctype, asset_name, start, end, exclude_trip=None):
    """True if another submitted, non-cancelled Trip uses this asset in [start, end]."""
    if not (asset_name and start and end):
        return False
    field = "tractor" if asset_doctype == "Tractor" else "trailer"
    filters = {
        field: asset_name,
        "docstatus": 1,
        "status": ["!=", "Cancelled"],
        "actual_start": ["<", end],
        "actual_end": [">", start],
    }
    if exclude_trip:
        filters["name"] = ["!=", exclude_trip]
    return bool(frappe.db.exists("Trip", filters))
