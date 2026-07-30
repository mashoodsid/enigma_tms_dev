import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint
from enigma_tms.pricing import compute_line_pricing, resolve_customer_rate

"""
make assignement field manadatory and other  in trip
start trip when tractor availabel
make trailer and driver editable like sales invoice edit posting date and time option in sales invoice
"""


class TransportOrder(Document):
    def validate(self):
        self.set_billing_mode()
        self.set_taxes_default()
        self.validate_stops()
        self.price_lines()
        self.compute_totals()

    def set_taxes_default(self):
        if not self.taxes_and_charges:
            self.taxes_and_charges = frappe.db.get_single_value(
                "Transport Setting", "default_sales_taxes_template"
            )

    def set_billing_mode(self):
        if self.billing_mode:
            return
        mode = frappe.db.get_value(
            "Customer", self.customer, "custom_default_billing_mode"
        )
        if not mode:
            mode = frappe.db.get_single_value(
                "Transport Setting", "default_billing_mode"
            )
        self.billing_mode = mode or "Per Order"

    def validate_stops(self):
        n = len(self.items)
        lane_stop_count = {i + 1: 0 for i in range(n)}
        for s in self.stops:
            if not s.order_line or cint(s.order_line) < 1 or cint(s.order_line) > n:
                frappe.throw(
                    _(
                        "Stop (seq {0}) references Lane # {1}, which does not exist. Valid lanes: 1..{2}."
                    ).format(s.seq, s.order_line, n)
                )
            lane_stop_count[cint(s.order_line)] += 1
        for i, item in enumerate(self.items, start=1):
            if lane_stop_count.get(i, 0) == 0:
                frappe.throw(
                    _(
                        "Lane {0} ({1} / {2}) has no stops. Add at least a pickup and a drop."
                    ).format(i, item.route, item.trailer_type)
                )
            item.total_stops = lane_stop_count[i]

    def price_lines(self):
        apply_fuel_on = (
            frappe.db.get_single_value("Transport Setting", "apply_fuel_on")
            or "Linehaul"
        )
        for item in self.items:
            if item.manual_price_flag:
                # Manager-entered price: keep base_rate/line_total as typed, just recompute amounts shell.
                continue
            rate = resolve_customer_rate(
                self.customer, item.route, item.trailer_type, self.order_date
            )
            if not rate:
                frappe.throw(
                    _(
                        "No active rate found for lane {0} / {1} for {2}. "
                        "A Transport Manager may enter a manual price."
                    ).format(item.route, item.trailer_type, self.customer),
                    title=_("Rate Not Found"),
                )
            item.base_rate = rate.get("base_rate")
            item.extra_stop_charge = rate.get("extra_stop_charge")
            item.extra_stop_basis = rate.get("extra_stop_basis") or "Flat"
            item.fuel_surcharge_pct = rate.get("fuel_surcharge_pct")
            item.min_charge = rate.get("min_charge")

            priced = compute_line_pricing(
                base_rate=item.base_rate,
                qty_trailers=item.qty_trailers,
                # per_truck_trips=item.per_truck_trips,
                qty=item.qty,
                total_stops=item.total_stops,
                extra_stop_charge=item.extra_stop_charge,
                extra_stop_basis=item.extra_stop_basis,
                fuel_surcharge_pct=item.fuel_surcharge_pct,
                min_charge=item.min_charge,
                apply_fuel_on=apply_fuel_on,
            )
            item.extra_stop_amount = priced["extra_stop_amount"]
            item.fuel_surcharge_amount = priced["fuel_surcharge_amount"]
            item.line_total = priced["line_total"]

    def compute_totals(self):
        self.total = flt(sum(flt(i.line_total) for i in self.items), 2)
        self.selling_total = self.total
        self.total_taxes = self._compute_taxes()
        self.grand_total = flt(self.total + self.total_taxes, 2)

    def _compute_taxes(self):
        if not self.taxes_and_charges:
            return 0.0
        rows = frappe.get_all(
            "Sales Taxes and Charges",
            filters={
                "parent": self.taxes_and_charges,
                "parenttype": "Sales Taxes and Charges Template",
            },
            fields=["charge_type", "rate"],
        )
        pct = sum(
            flt(r.rate)
            for r in rows
            if r.charge_type in ("On Net Total", "On Paid Amount")
        )
        return flt(self.total * pct / 100.0, 2)

    # ---------------------------------------------------------------- submit
    def before_submit(self):
        for item in self.items:
            if not item.line_total:
                frappe.throw(
                    _(
                        "Lane {0} has no price. Resolve the rate before confirming."
                    ).format(item.idx)
                )
        self.check_credit_limit()
        self.status = "Confirmed"

    def check_credit_limit(self):
        try:
            from erpnext.selling.doctype.customer.customer import check_credit_limit

            company = frappe.defaults.get_user_default(
                "Company"
            ) or frappe.db.get_default("Company")
            if company:
                check_credit_limit(
                    self.customer, company, extra_amount=self.grand_total
                )
        except frappe.ValidationError:
            raise
        except Exception:
            # Credit feature optional — never hard-fail scaffolding if not configured.
            pass

    def on_cancel(self):
        open_trips = frappe.get_all(
            "Trip",
            filters={
                "transport_order": self.name,
                "docstatus": ["<", 2],
                "status": ["!=", "Cancelled"],
            },
        )
        if open_trips:
            frappe.throw(
                _(
                    "Cancel or close the {0} linked Trip(s) before cancelling this Order."
                ).format(len(open_trips))
            )
        self.status = "Cancelled"

    # ---------------------------------------------------------------- lifecycle
    def refresh_status_from_trips(self):
        trips = frappe.get_all(
            "Trip",
            filters={"transport_order": self.name, "docstatus": ["<", 2]},
            fields=["status"],
        )
        if not trips:
            new = "Confirmed" if self.docstatus == 1 else self.status
        elif all(t.status == "Completed" for t in trips):
            new = "Completed"
        elif any(t.status not in ("Assigned",) for t in trips):
            new = "In Progress"
        else:
            new = "Confirmed"
        if new != self.status and self.status != "Closed":
            self.db_set("status", new)


# ====================================================================
# Helpers
# ====================================================================
def _add_order_comment(order_name, text):
    """Log an activity comment on the Transport Order timeline.

    Wrapped in try/except so a failure to log a comment never blocks the
    actual document creation/deletion that triggered it.
    """
    try:
        frappe.get_doc("Transport Order", order_name).add_comment("Comment", text)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Failed to add comment on Transport Order {order_name}",
        )


# ====================================================================
# Whitelisted actions (called from the form buttons)
# ====================================================================
@frappe.whitelist()
def create_trips(order_name):
    order = frappe.get_doc("Transport Order", order_name)
    if order.docstatus != 1:
        frappe.throw(_("Confirm (submit) the Order before generating Trips."))

    if not order.stops:
        frappe.throw(_("No Stops are available in Transport Order for creating Trips."))

    existing = frappe.get_all(
        "Trip", filters={"transport_order": order_name, "docstatus": ["<", 2]}
    )
    created = []
    for lane_no, item in enumerate(order.items, start=1):
        lane_stops = [s for s in order.stops if cint(s.order_line) == lane_no]
        print(lane_stops)
        total_trips = (cint(item.qty_trailers) or 1) * (cint(item.per_truck_trips) or 1)
        per_trip_selling = flt(item.line_total) / total_trips if total_trips else 0
        for _n in range(total_trips):
            trip = frappe.new_doc("Trip")
            trip.transport_order = order.name
            trip.customer = order.customer
            trip.order_line = lane_no
            trip.trailer_type = item.trailer_type
            trip.route = item.route
            trip.selling_amount = flt(per_trip_selling, 2)
            trip.status = "Assigned"
            for s in lane_stops:
                trip.append(
                    "stops",
                    {
                        "order_line": s.order_line,
                        "seq": s.seq,
                        "stop_type": s.stop_type,
                        "location": s.location,
                        "contact_person": s.contact_person,
                        "contact_phone": s.contact_phone,
                        "planned_datetime": s.planned_datetime,
                        "load_description": s.load_description,
                        "weight_tons": s.weight_tons,
                        "status": "Pending",
                    },
                )
            trip.insert(ignore_permissions=True, ignore_mandatory=True)
            created.append(trip.name)

    if created and order.status == "Confirmed":
        order.db_set("status", "Confirmed")

    if created:
        trip_list = ", ".join(created)
        _add_order_comment(
            order.name,
            _("{0} Trip(s) generated: {1}").format(len(created), trip_list),
        )

    return {"created": created, "already_had": len(existing)}


@frappe.whitelist()
def create_sales_invoice(order_name):
    order = frappe.get_doc("Transport Order", order_name)
    settings = frappe.get_cached_doc("Transport Setting")

    completed_trips = frappe.get_all(
        "Trip",
        filters={
            "transport_order": order.name,
            "docstatus": 1,
            "status": "Completed",
        },
        fields=["name", "selling_amount"],
    )
    if not completed_trips:
        frappe.throw(_("No completed Trips to invoice yet."))

    made = []
    if order.billing_mode == "Per Trip":
        for t in completed_trips:
            made.append(_make_si(order, settings, [t]))
    else:
        made.append(_make_si(order, settings, completed_trips))

    order.db_set("status", "Completed - Invoiced")
    return {"sales_invoices": made}


def _make_si(order, settings, trips):

    si = frappe.new_doc("Sales Invoice")
    si.customer = order.customer
    si.company = _default_company()
    si.currency = order.currency
    si.company = settings.company
    si.cost_center = settings.cost_center
    si.po_no = order.customer_po_no
    si.po_date = order.order_date
    # si.custom_transport_order = order.name

    remarks = ""
    for row in order.items:
        item = frappe.db.get_value("Commodity", row.commodity, "sales_item")

        if not item:
            frappe.throw(f"Item is not set commodity {row.commodity}")

        route_name = frappe.db.get_value("Transport Route", row.route, "route_name")
        trailer, trailer_type = frappe.db.get_value(
            "Trip",
            {"order_line": row.idx, "transport_order": order.name},
            ["trailer", "trailer_type"],
        )
        trailer_doc = frappe.get_doc("Trailer", trailer)
        desc = ""

        for i in range(0, cint(row.qty_trailers)):
            desc += f"""{route_name} {trailer_doc.plate_number} ({flt(trailer_doc.capacity_tons)} TON) \n """

        invoice_item = {
            "cost_center": settings.cost_center,
            "item_code": item,
            "qty": flt(row.qty),
            "rate": flt(row.base_rate),
            "description": desc,
        }

        si.append("items", invoice_item)

    for t in trips:
        remarks += _("Transport — Trip {0}").format(t.name)

    template = order.taxes_and_charges or settings.default_sales_taxes_template
    if template:
        si.taxes_and_charges = template
        from erpnext.controllers.accounts_controller import get_taxes_and_charges

        for tax in get_taxes_and_charges("Sales Taxes and Charges Template", template):
            si.append("taxes", tax)

    si.remarks = remarks
    # for key in to_wise_trips.keys():
    si.append("custom_transport_orders", {"transport_order": order.name})

    si.insert(ignore_permissions=True)

    trip_list = ", ".join(t.name for t in trips)
    _add_order_comment(
        order.name,
        _("Sales Invoice <b>{0}</b> generated for Trip(s): {1}").format(
            si.name, trip_list
        ),
    )

    return si.name


def _default_company():
    return frappe.defaults.get_global_default("company") or frappe.db.get_value(
        "Company", {}, "name"
    )


def handle_trip_closure(self, method=None):
    if not self.get("custom_transport_order"):
        return

    order = frappe.get_doc("Transport Order", self.get("custom_transport_order"))

    sales = frappe.db.get_value(
        "Sales Invoice",
        {
            "custom_transport_order": order.name,
            "docstatus": ["!=", 2],
        },
        "name",
    )
    purchase = frappe.db.get_value(
        "Purchase Invoice",
        {
            "custom_transport_order": order.name,
            "docstatus": ["!=", 2],
        },
        "name",
    )
    jvs = frappe.db.get_value(
        "Journal Entry",
        {
            "custom_transport_order": order.name,
            "docstatus": ["!=", 2],
        },
        "name",
    )
    if sales and (purchase or jvs):
        frappe.db.set_value("Transport Order", order.name, "status", "Closed")


# ---- ERPNext Sales Invoice hooks (wired in hooks.py) ----
def on_sales_invoice_submit(doc, method=None):
    order_name = getattr(doc, "custom_transport_order", None)
    if order_name and frappe.db.exists("Transport Order", order_name):
        frappe.db.set_value("Transport Order", order_name, "status", "Closed")


def on_sales_invoice_cancel(doc, method=None):
    orders = getattr(doc, "custom_transport_orders", None)
    for i in orders:
        order_name = i.transport_order
        if order_name and frappe.db.exists("Transport Order", order_name):
            order = frappe.get_doc("Transport Order", order_name)
            order.refresh_status_from_trips()


@frappe.whitelist()
def get_customer_route_price(customer, route, trailer_type, commodity):
    r = frappe.db.sql(
        f" select c.base_rate from  `tabCustomer Rate Card` p  inner join `tabRate Card Line` c on c.parent = p.name where p.customer = '{customer}' AND p.status='Active' AND c.trailer_type = '{trailer_type}' AND c.route = '{route}' AND c.commodity = '{commodity}' ",
        debug=True,
    )
    if not r:
        return 0

    return r[0][0]


@frappe.whitelist()
def create_purchase_invoices(order_name):
    from frappe.utils import flt, today

    order = frappe.get_doc("Transport Order", order_name)
    settings = frappe.get_cached_doc("Transport Setting")
    company = settings.company or _default_company()

    trips = frappe.get_all(
        "Trip", filters={"transport_order": order_name, "docstatus": 1}, fields=["name"]
    )

    created_docs = []

    # subcontractor -> {"items": [...], "trips": set()}
    subcontractor_bucket = {}

    for t in trips:
        trip = frappe.get_doc("Trip", t.name)
        if not trip.tractor:
            continue

        tractor = frappe.get_doc("Tractor", trip.tractor)

        if tractor.ownership == "Outsourced":
            if not tractor.subcontractor:
                continue

            for cost in trip.costs:
                if not cost.tms_cost:
                    continue

                tms_cost = frappe.get_doc("TMS Cost", cost.tms_cost)
                if not tms_cost.purchase_item:
                    continue

                bucket = subcontractor_bucket.setdefault(
                    tractor.subcontractor, {"items": [], "trips": set()}
                )
                bucket["items"].append(
                    {
                        "item_code": tms_cost.purchase_item,
                        "qty": 1,
                        "rate": flt(cost.amount),
                        "description": cost.description,
                    }
                )
                bucket["trips"].add(trip.name)

        elif tractor.ownership == "Owned":
            for cost in trip.costs:
                if not cost.tms_cost:
                    continue
                tms_cost = frappe.get_doc("TMS Cost", cost.tms_cost)
                if not tms_cost.purchase_item:
                    continue

                expense_account = frappe.db.get_value(
                    "Item Default",
                    {"parent": tms_cost.purchase_item, "company": company},
                    "expense_account",
                )

                credit_account = frappe.db.get_value(
                    "Driver", trip.driver, "custom_cash_account"
                )
                if not expense_account:
                    expense_account = frappe.db.get_value(
                        "Company", company, "default_expense_account"
                    )

                if not expense_account or not credit_account:
                    continue

                amount = flt(cost.amount)
                if amount <= 0:
                    continue

                je = frappe.new_doc("Journal Entry")
                je.voucher_type = "Journal Entry"
                je.custom_transport_order = order.name
                je.posting_date = today()
                je.user_remark = f"owned-trip costs for {trip.name}"
                je.company = company

                je.append(
                    "accounts",
                    {
                        "cost_center": settings.cost_center,
                        "account": expense_account,
                        "debit_in_account_currency": amount,
                        "party_type": "",
                        "party": "",
                    },
                )

                je.append(
                    "accounts",
                    {
                        "cost_center": settings.cost_center,
                        "account": credit_account,
                        "credit_in_account_currency": amount,
                        "party_type": "",
                        "party": "",
                    },
                )

                je.insert(ignore_permissions=True)
                created_docs.append(je.name)

                _add_order_comment(
                    order.name,
                    _(
                        "Journal Entry <b>{0}</b> generated for owned-trip costs of Trip {1}"
                    ).format(je.name, trip.name),
                )

    # ---- One Purchase Invoice per subcontractor, covering all their trips ----
    for subcontractor, bucket in subcontractor_bucket.items():
        if not bucket["items"]:
            continue

        pi = frappe.new_doc("Purchase Invoice")
        pi.supplier = subcontractor
        pi.custom_transport_order = order.name
        pi.company = company

        trip_names = sorted(bucket["trips"])
        if hasattr(pi, "custom_trip") and len(trip_names) == 1:
            pi.custom_trip = trip_names[0]

        for item in bucket["items"]:
            pi.append("items", item)

        pi.insert(ignore_permissions=True)
        created_docs.append(pi.name)

        trip_list = ", ".join(trip_names)
        _add_order_comment(
            order.name,
            _(
                "Purchase Invoice <b>{0}</b> generated for Subcontractor {1} "
                "covering Trip(s): {2}"
            ).format(pi.name, subcontractor, trip_list),
        )

    return created_docs


@frappe.whitelist()
def delete_draft_journal_entries(order):
    jv = frappe.db.get_list(
        "Journal Entry",
        {
            "custom_transport_order": order,
            "docstatus": 0,
        },
    )

    for i in jv:
        je_name = i.name if hasattr(i, "name") else i.get("name")
        frappe.delete_doc("Journal Entry", je_name)
        frappe.msgprint(f"Journal entry {je_name} has been deleted")
        _add_order_comment(
            order,
            _("Journal Entry <b>{0}</b> was deleted.").format(je_name),
        )


@frappe.whitelist()
def create_bulk_order_invoice(orders):
    import json

    if not orders:
        return

    settings = frappe.get_cached_doc("Transport Setting")
    orders = json.loads(orders)

    customers = []
    transport_orders = []
    to_wise_trips = {}
    remarks = ""

    for order_name in orders:
        order = frappe.get_doc("Transport Order", order_name)
        customers.append(order.customer)
        transport_orders.append(order.as_dict())

        existing_invoice = frappe.db.sql(
            f"""
            SELECT si.name, sto.transport_order FROM `tabSales Invoice Transport Orders` sto 
            INNER JOIN `tabSales Invoice` si 
            ON si.name = sto.parent
            WHERE si.docstatus != 2 AND sto.transport_order = '{order.name}'
        """,
            debug=True,
        )

        if existing_invoice:
            existing_invoice = existing_invoice[0]
            frappe.throw(
                f"Invoice {existing_invoice[0]} already exists against Transport Order {order.name}."
            )

        if order.billing_mode == "Per Trip":
            frappe.throw(
                f"Cannot include Transport Order {order.name} in this trip because bulk invoicing is only supported for Transport Orders with the billing type 'Per Order'."
            )

        trips = frappe.get_all(
            "Trip",
            filters={
                "transport_order": order.name,
            },
            fields=["name", "status"],
        )

        for t in trips:
            if t.get("status") != "Completed":
                frappe.throw(
                    f"No completed Trips to invoice yet for Transport Order {order.name}."
                )

            remarks += f"Transport Order: {order.name}  — Trip: {t.name} \n"

        if order.get("name") not in to_wise_trips:
            to_wise_trips[order.get("name")] = []

        to_wise_trips[order.get("name")].extend(trips)
    f = customers[0]
    for c in customers:
        if c != f:
            frappe.throw("Cannot Create Single bulk invoice for different Customers")

    made = []
    first_to = transport_orders[0]
    sales_invoice = frappe.new_doc("Sales Invoice")
    sales_invoice.customer = first_to.customer
    sales_invoice.company = first_to.company
    sales_invoice.currency = first_to.currency
    sales_invoice.cost_center = settings.cost_center
    sales_invoice.po_no = ",".join([i.customer_po_no or "" for i in transport_orders])

    for to in transport_orders:
        for row in to["items"]:
            item = frappe.db.get_value("Commodity", row["commodity"], "sales_item")

            if not item:
                frappe.throw(f"Item is not set commodity {row['commodity']}")

            route_name = frappe.db.get_value(
                "Transport Route", row["route"], "route_name"
            )
            trailer = frappe.db.get_value(
                "Trip",
                {"order_line": row.idx, "transport_order": to["name"]},
                ["trailer"],
            )

            trailer_doc = frappe.get_doc("Trailer", trailer)
            desc = ""

            for _ in range(cint(row["qty_trailers"])):
                desc += f"""{route_name} {trailer_doc.plate_number} ({flt(trailer_doc.capacity_tons)} TON) \n """

            invoice_item = {
                "cost_center": settings.cost_center,
                "item_code": item,
                "qty": flt(row["qty"]),
                "rate": flt(row["base_rate"]),
                "description": desc,
            }

            sales_invoice.append("items", invoice_item)

    template = settings.default_sales_taxes_template
    if template:
        sales_invoice.taxes_and_charges = template
        from erpnext.controllers.accounts_controller import get_taxes_and_charges

        for tax in get_taxes_and_charges("Sales Taxes and Charges Template", template):
            sales_invoice.append("taxes", tax)

    for key in to_wise_trips.keys():
        sales_invoice.append("custom_transport_orders", {"transport_order": key})

    sales_invoice.remarks = remarks
    sales_invoice.insert(ignore_permissions=True)

    for i in orders:
        transport_order = frappe.get_doc("Transport Order", i)
        transport_order.db_set("status", "Completed - Invoiced")

    return f"Sales Invoice Generated {sales_invoice.name}"
