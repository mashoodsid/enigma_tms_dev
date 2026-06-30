import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint
from enigma_tms.pricing import compute_line_pricing, resolve_customer_rate


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
# Whitelisted actions (called from the form buttons)
# ====================================================================
@frappe.whitelist()
def create_trips(order_name):
    order = frappe.get_doc("Transport Order", order_name)
    if order.docstatus != 1:
        frappe.throw(_("Confirm (submit) the Order before generating Trips."))

    existing = frappe.get_all(
        "Trip", filters={"transport_order": order_name, "docstatus": ["<", 2]}
    )
    created = []
    for lane_no, item in enumerate(order.items, start=1):
        lane_stops = [s for s in order.stops if cint(s.order_line) == lane_no]
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
            trip.insert(ignore_permissions=True)
            created.append(trip.name)

    if created and order.status == "Confirmed":
        order.db_set("status", "Confirmed")
    return {"created": created, "already_had": len(existing)}


@frappe.whitelist()
def create_sales_invoice(order_name):
    """Create draft Sales Invoice(s) per billing_mode (§6)."""
    order = frappe.get_doc("Transport Order", order_name)
    settings = frappe.get_cached_doc("Transport Setting")
    freight_item = settings.freight_item
    if not freight_item:
        frappe.throw(
            _("Set a default Freight Linehaul Item in Transport Setting first.")
        )

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
    return {"sales_invoices": made}


def _make_si(order, settings, trips):

    si = frappe.new_doc("Sales Invoice")
    si.customer = order.customer
    si.company = _default_company()
    si.currency = order.currency
    si.company = settings.company
    si.cost_center = settings.cost_center
    if hasattr(si, "custom_transport_order"):
        si.custom_transport_order = order.name
    for t in trips:
        si.append(
            "items",
            {
                "cost_center": settings.cost_center,
                "item_code": settings.freight_item,
                "qty": 1,
                "rate": flt(t.selling_amount),
                "description": _("Transport — Trip {0}").format(t.name),
            },
        )
    template = order.taxes_and_charges or settings.default_sales_taxes_template
    if template:
        si.taxes_and_charges = template
        from erpnext.controllers.accounts_controller import get_taxes_and_charges

        for tax in get_taxes_and_charges("Sales Taxes and Charges Template", template):
            si.append("taxes", tax)
    si.insert(ignore_permissions=True)
    return si.name


def _default_company():
    return frappe.defaults.get_global_default("company") or frappe.db.get_value(
        "Company", {}, "name"
    )


# ---- ERPNext Sales Invoice hooks (wired in hooks.py) ----
def on_sales_invoice_submit(doc, method=None):
    order_name = getattr(doc, "custom_transport_order", None)
    if order_name and frappe.db.exists("Transport Order", order_name):
        frappe.db.set_value("Transport Order", order_name, "status", "Closed")


def on_sales_invoice_cancel(doc, method=None):
    order_name = getattr(doc, "custom_transport_order", None)
    if order_name and frappe.db.exists("Transport Order", order_name):
        order = frappe.get_doc("Transport Order", order_name)
        order.refresh_status_from_trips()


@frappe.whitelist()
def get_customer_route_price(customer, route, trailer_type, commodity):
    r = frappe.db.sql(
        f" select c.base_rate from  `tabCustomer Rate Card` p  inner join `tabRate Card Line` c on c.parent = p.name where p.customer = '{customer}' AND p.status='Active' AND c.trailer_type = '{trailer_type}' AND c.route = '{route}' AND c.commodity = '{commodity}' "
    )
    if not r:
        return 0

    return r[0][0]
