import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

TMS_ROLES = [
    ("Order Desk", "Create & price Transport Orders."),
    ("Dispatcher", "Dispatch trips, assign tractor/trailer/driver, update stops, attach POD."),
    ("Transport Finance", "Invoicing, rate cards, manual price overrides."),
    ("Transport Manager", "Full access + reports + price-override authority."),
]


def after_install():
    create_roles()
    create_tms_custom_fields()
    ensure_transport_setting()
    ensure_supplier_group()
    ensure_workspace()
    ensure_dashboard()
    ensure_dashboard_page()
    ensure_kanban()
    frappe.db.commit()


def after_migrate():
    # Idempotent: keep custom fields + workspace + dashboard + board in sync on every migrate.
    create_tms_custom_fields()
    ensure_workspace()
    ensure_dashboard()
    ensure_dashboard_page()
    ensure_kanban()


def ensure_workspace():
    # Frappe doesn't reliably auto-import app workspaces; import it explicitly if missing.
    if frappe.db.exists("Workspace", "Transport Operations"):
        return
    path = frappe.get_app_path(
        "enigma_tms", "workspace", "transport_operations", "transport_operations.json"
    )
    if os.path.exists(path):
        from frappe.modules.import_file import import_file_by_path
        import_file_by_path(path, force=True)


def create_roles():
    for role_name, desc in TMS_ROLES:
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({
                "doctype": "Role",
                "role_name": role_name,
                "desk_access": 1,
                "description": desc,
            }).insert(ignore_permissions=True)


def create_tms_custom_fields():
    custom_fields = {
        "Customer": [
            {
                "fieldname": "custom_tms_section",
                "label": "Transport Management",
                "fieldtype": "Section Break",
                "insert_after": "default_currency",
                "collapsible": 1,
            },
            {
                "fieldname": "custom_default_billing_mode",
                "label": "Default Billing Mode",
                "fieldtype": "Select",
                "options": "\nPer Order\nPer Trip",
                "insert_after": "custom_tms_section",
                "description": "Default invoicing grain for this customer's transport orders.",
            },
        ],
        "Driver": [
            {
                "fieldname": "custom_tms_section",
                "label": "Transport Management",
                "fieldtype": "Section Break",
                "insert_after": "status",
                "collapsible": 1,
            },
            {
                "fieldname": "custom_driver_type",
                "label": "Driver Type",
                "fieldtype": "Select",
                "options": "Owned\nSubcontractor",
                "default": "Owned",
                "insert_after": "custom_tms_section",
            },
            {
                "fieldname": "custom_subcontractor",
                "label": "Subcontractor",
                "fieldtype": "Link",
                "options": "Supplier",
                "insert_after": "custom_driver_type",
                "depends_on": "eval:doc.custom_driver_type=='Subcontractor'",
            },
            {
                "fieldname": "custom_national_id_iqama",
                "label": "National ID / Iqama",
                "fieldtype": "Data",
                "insert_after": "custom_subcontractor",
            },
            {
                "fieldname": "custom_license_expiry",
                "label": "License Expiry",
                "fieldtype": "Date",
                "insert_after": "custom_national_id_iqama",
            },
        ],
       # "Sales Invoice": [
       #     {
       #         "fieldname": "custom_transport_order",
       #         "label": "Transport Order",
       #         "fieldtype": "Link",
       #         "options": "Transport Order",
       #         "insert_after": "customer",
       #         "read_only": 1,
       #         "print_hide": 1,
       #     },
      #  ],
        "Purchase Invoice": [
            {
                "fieldname": "custom_trip",
                "label": "Trip",
                "fieldtype": "Link",
                "options": "Trip",
                "insert_after": "supplier",
                "read_only": 1,
                "print_hide": 1,
            },
        ],
    }
    create_custom_fields(custom_fields, update=True)


def ensure_transport_setting():
    if not frappe.db.exists("Transport Setting", "Transport Setting"):
        doc = frappe.get_doc({"doctype": "Transport Setting"})
        doc.flags.ignore_mandatory = True
        doc.insert(ignore_permissions=True)


TRIP_SUBMITTED = '[["Trip","docstatus","=",1]]'

NUMBER_CARDS = [
    # Operations
    dict(name="TMS Active Trips", label="Active Trips", document_type="Trip", function="Count",
         filters_json='[["Trip","docstatus","=",1],["Trip","status","not in",["Completed","Cancelled"]]]'),
    dict(name="TMS Trips In Transit", label="In Transit", document_type="Trip", function="Count",
         filters_json='[["Trip","docstatus","=",1],["Trip","status","=","In Transit"]]'),
    dict(name="TMS Trips This Month", label="Trips This Month", document_type="Trip", function="Count",
         filters_json='[["Trip","docstatus","=",1],["Trip","creation","Timespan","this month"]]'),
    dict(name="TMS Trip Profit This Month", label="Trip Profit (This Month)", document_type="Trip",
         function="Sum", aggregate_function_based_on="trip_profit",
         filters_json='[["Trip","docstatus","=",1],["Trip","creation","Timespan","this month"]]'),
    dict(name="TMS Open Orders", label="Open Orders", document_type="Transport Order", function="Count",
         filters_json='[["Transport Order","status","in",["Confirmed","In Progress"]]]'),
    # Masters / fleet
    dict(name="TMS Tractors Available", label="Tractors Available", document_type="Tractor", function="Count",
         filters_json='[["Tractor","status","=","Available"]]'),
    dict(name="TMS Trailers Available", label="Trailers Available", document_type="Trailer", function="Count",
         filters_json='[["Trailer","status","=","Available"]]'),
    dict(name="TMS Total Tractors", label="Total Tractors", document_type="Tractor", function="Count",
         filters_json='[]'),
    dict(name="TMS Total Trailers", label="Total Trailers", document_type="Trailer", function="Count",
         filters_json='[]'),
    dict(name="TMS Routes", label="Routes", document_type="Transport Route", function="Count",
         filters_json='[]'),
    dict(name="TMS Active Rate Cards", label="Active Rate Cards", document_type="Customer Rate Card",
         function="Count", filters_json='[["Customer Rate Card","status","=","Active"]]'),
]

DASHBOARD_CHARTS = [
    dict(name="TMS Trips by Status", document_type="Trip", chart_type="Group By",
         group_by_based_on="status", group_by_type="Count", type="Donut", filters_json=TRIP_SUBMITTED),
    dict(name="TMS Owned vs Outsourced", document_type="Trip", chart_type="Group By",
         group_by_based_on="ownership", group_by_type="Count", type="Donut", filters_json=TRIP_SUBMITTED),
    dict(name="TMS Trips Per Day", document_type="Trip", chart_type="Count",
         based_on="creation", time_interval="Daily", timeseries=1, type="Line", filters_json=TRIP_SUBMITTED),
    dict(name="TMS Trip Profit Per Month", document_type="Trip", chart_type="Sum",
         based_on="creation", value_based_on="trip_profit", time_interval="Monthly", timeseries=1,
         type="Bar", filters_json=TRIP_SUBMITTED),
    dict(name="TMS Orders by Status", document_type="Transport Order", chart_type="Group By",
         group_by_based_on="status", group_by_type="Count", type="Bar", filters_json="[]"),
    dict(name="TMS Trips by Route", document_type="Trip", chart_type="Group By",
         group_by_based_on="route", group_by_type="Count", type="Bar", filters_json=TRIP_SUBMITTED),
    dict(name="TMS Trips by Trailer Type", document_type="Trip", chart_type="Group By",
         group_by_based_on="trailer_type", group_by_type="Count", type="Bar", filters_json=TRIP_SUBMITTED),
    dict(name="TMS Trailers by Type", document_type="Trailer", chart_type="Group By",
         group_by_based_on="trailer_type", group_by_type="Count", type="Donut", filters_json="[]"),
    dict(name="TMS Tractors by Ownership", document_type="Tractor", chart_type="Group By",
         group_by_based_on="ownership", group_by_type="Count", type="Donut", filters_json="[]"),
]


def ensure_dashboard():
    """Number Cards + Dashboard Charts for the Operations workspace (idempotent)."""
    for c in NUMBER_CARDS:
        # Number Card is auto-named by label, so dedupe on label.
        if frappe.db.exists("Number Card", c["label"]):
            continue
        doc = frappe.get_doc({
            "doctype": "Number Card", "label": c["label"],
            "type": "Document Type", "document_type": c["document_type"],
            "function": c["function"], "aggregate_function_based_on": c.get("aggregate_function_based_on"),
            "filters_json": c["filters_json"], "is_public": 1, "show_percentage_stats": 1,
            "stats_time_interval": "Monthly", "module": "Transport Operations",
        })
        doc.flags.ignore_permissions = True
        doc.insert()

    for ch in DASHBOARD_CHARTS:
        if frappe.db.exists("Dashboard Chart", ch["name"]):
            continue
        doc = frappe.get_doc({
            "doctype": "Dashboard Chart", "name": ch["name"], "chart_name": ch["name"],
            "chart_type": ch["chart_type"], "document_type": ch["document_type"],
            "group_by_based_on": ch.get("group_by_based_on"), "group_by_type": ch.get("group_by_type"),
            "based_on": ch.get("based_on"), "value_based_on": ch.get("value_based_on"),
            "time_interval": ch.get("time_interval"), "timeseries": ch.get("timeseries", 0),
            "type": ch["type"], "timespan": "Last Quarter", "filters_json": ch.get("filters_json", "[]"),
            "is_public": 1, "module": "Transport Operations",
        })
        doc.flags.ignore_permissions = True
        doc.insert()


def ensure_dashboard_page():
    """A dedicated 'Transport Operations' Dashboard grouping the charts + key cards."""
    if frappe.db.exists("Dashboard", "Transport Operations"):
        return
    charts = [
        ("TMS Trips Per Day", "Full"), ("TMS Trip Profit Per Month", "Full"),
        ("TMS Trips by Status", "Half"), ("TMS Owned vs Outsourced", "Half"),
        ("TMS Orders by Status", "Half"), ("TMS Trips by Route", "Half"),
        ("TMS Trips by Trailer Type", "Half"), ("TMS Trailers by Type", "Half"),
        ("TMS Tractors by Ownership", "Half"),
    ]
    cards = ["Active Trips", "In Transit", "Open Orders",
             "Trips This Month", "Trip Profit (This Month)",
             "Tractors Available", "Trailers Available"]
    doc = frappe.get_doc({
        "doctype": "Dashboard", "dashboard_name": "Transport Operations", "module": "Transport Operations",
        "is_default": 0,
        "charts": [{"chart": c, "width": w} for c, w in charts],
        "cards": [{"card": c} for c in cards],
    })
    doc.flags.ignore_permissions = True
    doc.insert()


def ensure_kanban():
    """A shared Kanban dispatch board on Trip grouped by status (idempotent)."""
    if frappe.db.exists("Kanban Board", "TMS Dispatch Board"):
        return
    statuses = ["Assigned", "Dispatched", "At Pickup", "Loaded", "In Transit", "At Drop", "Delivered", "Completed"]
    board = frappe.get_doc({
        "doctype": "Kanban Board", "kanban_board_name": "TMS Dispatch Board",
        "reference_doctype": "Trip", "field_name": "status", "private": 0,
        "columns": [{"column_name": s, "status": "Active", "indicator": "Gray"} for s in statuses],
    })
    board.flags.ignore_permissions = True
    board.insert()


def ensure_supplier_group():
    # Subcontractors live under a "Transporters" supplier group.
    if not frappe.db.exists("Supplier Group", "Transporters"):
        parent = "All Supplier Groups" if frappe.db.exists("Supplier Group", "All Supplier Groups") else None
        frappe.get_doc({
            "doctype": "Supplier Group",
            "supplier_group_name": "Transporters",
            "parent_supplier_group": parent,
            "is_group": 0,
        }).insert(ignore_permissions=True)
