app_name = "enigma_tms"
app_title = "Enigma TMS"
app_publisher = "Enigma Logics"
app_description = "Transport Management System for road-freight fleet operations (KSA)"
app_email = "mashood@enigmalogics.com"
app_license = "mit"
required_apps = ["frappe", "erpnext"]

# ------------------------------------------------------------------
# Installation / migration — create roles, custom fields, defaults.
# create_custom_fields is idempotent, so running on every migrate keeps
# the standard-doctype extensions (Customer/Driver) in sync.
# ------------------------------------------------------------------
after_install = "enigma_tms.install.after_install"
after_migrate = "enigma_tms.install.after_migrate"

# ------------------------------------------------------------------
# Document Events — wire controller hooks for ERPNext docs we react to.
# (App's own doctypes handle their own logic in their controllers.)
# ------------------------------------------------------------------
doc_events = {
    "Sales Invoice": {
        "validate": "enigma_tms.transport_operations.doctype.transport_order.transport_order.handle_trip_closure",
        "after_delete": "enigma_tms.transport_operations.doctype.transport_order.transport_order.handle_trip_closure",
    },
    "Purchase Invoice": {
        "validate": "enigma_tms.transport_operations.doctype.transport_order.transport_order.handle_trip_closure",
        "after_delete": "enigma_tms.transport_operations.doctype.transport_order.transport_order.handle_trip_closure",
    },
    "Journal Entry": {
        "validate": "enigma_tms.transport_operations.doctype.transport_order.transport_order.handle_trip_closure",
        "after_delete": "enigma_tms.transport_operations.doctype.transport_order.transport_order.handle_trip_closure",
    },
}

# ------------------------------------------------------------------
# Scheduled tasks (placeholder — derived asset status refresh, etc.)
# ------------------------------------------------------------------
# scheduler_events = {}


fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            [
                "module",
                "in",
                ["Transport Operations", "Transport Pricing", "Transport Setup"],
            ]
        ],
    },
    {
        "dt": "Client Script",
        "filters": [
            [
                "module",
                "in",
                ["Transport Operations", "Transport Pricing", "Transport Setup"],
            ]
        ],
    },
]
