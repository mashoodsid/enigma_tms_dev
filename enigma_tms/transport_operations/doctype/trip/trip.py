import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    flt,
    getdate,
    now_datetime,
    today,
    time_diff_in_hours,
    cint,
    get_datetime,
)

from enigma_tms.pricing import (
    compute_line_pricing,
    resolve_subcontractor_rate,
    resolve_customer_rate,
)
from enigma_tms.asset_status import recompute_asset_status, has_overlap

DROP_DONE_STATUSES = ("Delivered", "Completed")


class Trip(Document):
    @property
    def tractor_status(self):
        return frappe.db.get_value("Tractor", self.tractor, "status") or ""

    def update_transport_order_status(self):
        if not self.transport_order:
            return
        try:
            to = frappe.get_doc("Transport Order", self.transport_order)
            for i in self.stops:
                for j in to.stops:
                    if (
                        i.order_line == j.order_line
                        and i.seq == j.seq
                        and i.stop_type == j.stop_type
                        and i.location == j.location
                    ):
                        frappe.db.set_value(
                            "Transport Stop", j.name, {"status": i.status}
                        )
        except Exception:
            frappe.log_error(
                "update_transport_order_status failed", frappe.get_traceback()
            )

    def update_status(self):
        if self.status == "Cancelled":
            return

        reqs = ["tractor", "trailer", "driver"]
        reqs_filled = all(
            self.get(i) is not None and str(self.get(i)) != "" for i in reqs
        )

        if self.status == "Draft":
            if reqs_filled:
                self.status = "Assigned"
            return

        if self.status == "Assigned":
            if not reqs_filled:
                self.status = "Draft"
                return

            # # "Validate Pick-up": move to In Transit once the Pickup stop has
            # # actually been arrived at.
            # pickup_stops = [s for s in self.stops if s.stop_type == "Pickup"]
            # if pickup_stops and any(s.arrival_datetime for s in pickup_stops):
            #     self.status = "In Transit"
            # return

        if self.status == "In Transit":
            # Mirror enforce_pod_gate's completion rule: every stop must be
            # Completed (i.e. have a POD) before the trip can be Completed.
            if self.stops and all(s.status == "Completed" for s in self.stops):
                self.status = "Completed"
            return

    # ---------------------------------------------------------------- validate
    def validate(self):
        if self.planned_start and not self.planned_end:
            from datetime import timedelta, datetime

            transit_hours = frappe.db.get_value(
                "Transport Route", self.route, "standard_transit_hours"
            )
            if transit_hours:
                start = datetime.strptime(
                    str(self.planned_start).split(".")[0], "%Y-%m-%d %H:%M:%S"
                )
                self.planned_end = start + timedelta(hours=cint(transit_hours))

        self.run_calculations()
        self.enforce_pod_gate()
        self.update_status()

        self.update_transport_order_status()

    def run_validations(self):
        for i in self.stops:
            if i.weight_tons <= 0 and i.status == "Completed":
                frappe.throw(f"Please add a weight for Stop Lane {i.order_line}, Sequence {i.seq}.")
                
    def before_update_after_submit(self):
        # Runs when an already-submitted Trip is edited (the dispatch workflow:
        # status/stops/POD/costs change after the trip is submitted).
        self.run_calculations()
        self.run_validations()
        self.enforce_pod_gate()
        self.update_status()
        self.update_transport_order_status()

    def run_calculations(self):
        self.sync_ownership()
        self.set_distance()
        self.stamp_pods()
        self.auto_update_stop_status()
        self.compute_costs()
        self.compute_detention()


    def _pod_seqs(self):
        """Set of stop seqs that have at least one POD. A POD left without a
        Stop Seq is auto-linked to the single Drop stop (single-drop trips)."""
        drops = [s for s in self.stops if s.stop_type == "Drop"]
        seqs = set()
        for p in self.pods:
            if not p.stop_seq and len(drops) == 1:
                p.stop_seq = drops[0].seq
            if p.stop_seq:
                seqs.add(p.stop_seq)
        return seqs

    def auto_update_stop_status(self):
        """A stop with a POD attached -> Completed; a stop with a recorded
        arrival -> Arrived (if still Pending). Completion always requires a POD
        (enforced in enforce_pod_gate).

        Reversal: if a stop is currently Completed but its POD was removed
        (seq no longer in pod_seqs), roll it back instead of leaving it stuck
        on Completed — otherwise enforce_pod_gate blocks every future save."""
        pod_seqs = self._pod_seqs()
        for s in self.stops:
            if s.seq in pod_seqs:
                s.status = "Completed"
            elif s.status == "Completed":
                # POD was removed after this stop was completed — revert.
                s.status = "Arrived" if s.arrival_datetime else "Pending"
            elif s.arrival_datetime and (s.status or "Pending") == "Pending":
                s.status = "Arrived"

    def compute_detention(self):
        """Per-stop waiting hours + a suggested excess-detention total (§5.3).
        Suggestion only — never auto-posted; dispatcher bills it manually."""
        free_hours = 0
        rate = (
            resolve_customer_rate(
                self.customer,
                self.route,
                self.trailer_type,
                getdate(self.actual_start or today()),
            )
            if self.route
            else None
        )
        if rate:
            free_hours = flt(rate.get("detention_free_hours"))
        total_excess = 0.0
        for s in self.stops:
            if s.arrival_datetime and s.departure_datetime:
                hrs = time_diff_in_hours(s.departure_datetime, s.arrival_datetime)
                s.waiting_hours = flt(max(0.0, hrs), 2)
                total_excess += max(0.0, s.waiting_hours - free_hours)
            else:
                s.waiting_hours = 0
        self.suggested_detention_hours = flt(total_excess, 2)

    def stamp_pods(self):
        for p in self.pods:
            if not p.uploaded_by:
                p.uploaded_by = frappe.session.user
            if not p.uploaded_on:
                p.uploaded_on = now_datetime()

    def sync_ownership(self):
        owns = []
        sub = None
        for asset_dt, name in (("Tractor", self.tractor), ("Trailer", self.trailer)):
            if name:
                o, s = frappe.db.get_value(
                    asset_dt, name, ["ownership", "subcontractor"]
                )
                owns.append(o)
                if o == "Outsourced" and s:
                    sub = s
        self.ownership = (
            "Outsourced" if "Outsourced" in owns else ("Owned" if owns else None)
        )
        self.subcontractor = sub if self.ownership == "Outsourced" else None

    def set_distance(self):
        if (
            self.odometer_start
            and self.odometer_end
            and self.odometer_end >= self.odometer_start
        ):
            self.actual_distance = flt(self.odometer_end - self.odometer_start, 2)

    def compute_costs(self):
        self.buying_total = flt(sum(flt(c.amount) for c in self.costs), 2)
        self.trip_profit = flt(flt(self.selling_amount) - self.buying_total, 2)

    def enforce_pod_gate(self):
        settings = frappe.get_doc("Transport Setting", "Transport Setting")
        if settings.allow_trip_completion_without_proofs:
            return
        
        """Two hard rules (§5.2a):
        1. A stop cannot be Completed unless it has a POD attached.
        2. A Trip cannot be Delivered/Completed unless every stop is Completed.
        """
        pod_seqs = self._pod_seqs()
        # Rule 1 — completed stop must have a POD
        for s in self.stops:
            if s.status == "Completed" and s.seq not in pod_seqs:
                frappe.throw(
                    _(
                        "Stop #{0} ({1} at {2}) cannot be Completed without a POD attached."
                    ).format(s.seq, s.stop_type, s.location)
                )
        # Rule 2 — trip completion requires all stops completed
        if self.status in DROP_DONE_STATUSES:
            pending = [s for s in self.stops if s.status != "Completed"]
            if pending:
                seqs = ", ".join(f"#{s.seq}" for s in pending)
                frappe.throw(
                    _(
                        "Trip cannot be {0} until all stops are Completed. "
                        "Pending stop(s): {1}."
                    ).format(self.status, seqs)
                )

    # ---------------------------------------------------------------- submit
    def before_submit(self):
        self.require_assignment()
        self.validate_driver_license()
        self.autofill_subcontractor_cost()
        self.compute_costs()
        self.check_overlap()

    def require_assignment(self):
        for field, label in (
            ("tractor", "Tractor"),
            ("trailer", "Trailer"),
            ("driver", "Driver"),
        ):
            if not self.get(field):
                frappe.throw(
                    _("Assign a {0} before submitting the Trip.").format(label)
                )

    def validate_driver_license(self):
        expiry = frappe.db.get_value("Driver", self.driver, "custom_license_expiry")
        if expiry and getdate(expiry) < getdate(today()):
            action = (
                frappe.db.get_single_value("Transport Setting", "license_expiry_action")
                or "Block"
            )
            msg = _("Driver {0}'s licence expired on {1}.").format(self.driver, expiry)
            if action == "Block":
                frappe.throw(msg)
            else:
                frappe.msgprint(msg, indicator="orange", alert=True)

    def autofill_subcontractor_cost(self):
        if self.ownership != "Outsourced" or not self.subcontractor:
            return
        if any(c.cost_type == "Subcontractor" for c in self.costs):
            return
        route = self._lane_route()
        if not route:
            return
        rate = resolve_subcontractor_rate(
            self.subcontractor,
            route,
            self.trailer_type,
            getdate(self.actual_start or today()),
        )
        if not rate:
            frappe.msgprint(
                _(
                    "No subcontractor rate found for this lane — enter the cost manually."
                ),
                indicator="orange",
                alert=True,
            )
            return
        priced = compute_line_pricing(
            base_rate=rate.get("base_rate"),
            qty_trailers=1,
            total_stops=len(self.stops),
            extra_stop_charge=rate.get("extra_stop_charge"),
            extra_stop_basis=rate.get("extra_stop_basis") or "Flat",
            fuel_surcharge_pct=rate.get("fuel_surcharge_pct"),
            min_charge=rate.get("min_charge"),
        )
        self.append(
            "costs",
            {
                "cost_type": "Subcontractor",
                "description": _("Auto from rate card"),
                "amount": priced["line_total"],
            },
        )

    def _lane_route(self):
        if not (self.transport_order and self.order_line):
            return None
        order = frappe.get_doc("Transport Order", self.transport_order)
        for item in order.items:
            if item.idx == self.order_line:
                return item.route
        return None

    def check_overlap(self):
        if not (self.actual_start and self.actual_end):
            return
        for asset_dt, name in (("Tractor", self.tractor), ("Trailer", self.trailer)):
            if name and has_overlap(
                asset_dt,
                name,
                self.actual_start,
                self.actual_end,
                exclude_trip=self.name,
            ):
                frappe.throw(
                    _("{0} {1} is already booked on an overlapping Trip.").format(
                        asset_dt, name
                    )
                )

    def on_submit(self):
        self.post_submit_effects()

    def on_update_after_submit(self):
        self.check_overlap()
        self.post_submit_effects()

    def post_submit_effects(self):
        for asset_dt, name in (("Tractor", self.tractor), ("Trailer", self.trailer)):
            recompute_asset_status(asset_dt, name)
        self.propagate_order_status()
        # Journal Entry creation moved to Transport Order level.
        # if self.status == "Completed" and self.ownership == "Owned":
        #     self.maybe_post_owned_costs_to_gl()

    def propagate_order_status(self):
        if self.transport_order:
            order = frappe.get_doc("Transport Order", self.transport_order)
            order.refresh_status_from_trips()

    # ---------------------------------------------------------------- GL
    def maybe_post_owned_costs_to_gl(self):
        settings = frappe.get_cached_doc("Transport Setting")
        if not settings.post_owned_costs_to_gl:
            return
        total = flt(
            sum(flt(c.amount) for c in self.costs if c.cost_type != "Subcontractor")
        )
        if total <= 0:
            return
        debit, credit = (
            settings.owned_cost_expense_account,
            settings.owned_cost_credit_account,
        )
        if not (debit and credit):
            frappe.msgprint(
                _(
                    "Owned-cost GL posting is on but expense/credit accounts are not set in Transport Setting — skipped."
                ),
                indicator="orange",
                alert=True,
            )
            return
        remark = f"Enigma TMS owned-trip costs for {self.name}"
        if frappe.db.exists(
            "Journal Entry", {"user_remark": remark, "docstatus": ["<", 2]}
        ):
            return
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.posting_date = today()
        je.user_remark = remark
        je.append("accounts", {"account": debit, "debit_in_account_currency": total})
        je.append("accounts", {"account": credit, "credit_in_account_currency": total})
        je.insert(ignore_permissions=True)
        je.submit()
        frappe.msgprint(
            _("Posted owned-trip costs to GL: {0}").format(je.name), alert=True
        )

    # ---------------------------------------------------------------- cancel
    def on_cancel(self):
        for inv_dt, field in (("Sales Invoice", "custom_transport_order"),):
            pass  # SI is per order, not per trip; guarded at order level.
        pi = frappe.get_all(
            "Purchase Invoice", filters={"custom_trip": self.name, "docstatus": 1}
        )
        if pi:
            frappe.throw(
                _(
                    "Cancel the linked Purchase Invoice ({0}) before cancelling this Trip."
                ).format(pi[0].name)
            )
        self.status = "Cancelled"
        for asset_dt, name in (("Tractor", self.tractor), ("Trailer", self.trailer)):
            recompute_asset_status(asset_dt, name)
        self.propagate_order_status()


# ====================================================================
# Whitelisted actions
# ====================================================================
@frappe.whitelist()
def create_purchase_invoice(trip_name):
    """Create a draft Purchase Invoice from an outsourced trip's Subcontractor cost (§6)."""
    trip = frappe.get_doc("Trip", trip_name)
    if trip.ownership != "Outsourced" or not trip.subcontractor:
        frappe.throw(
            _("Purchase Invoice applies to outsourced trips with a subcontractor only.")
        )

    # sub_cost = 0
    # for c in trip.costs:
    #     sub_cost += flt(c.amount)

    # if sub_cost <= 0:
    #     frappe.throw(_("No subcontractor cost recorded on this trip."))

    # settings = frappe.get_cached_doc("Transport Setting")
    # item = settings.freight_item
    # if not item:
    #     frappe.throw(
    #         _("Set a default Freight Linehaul Item in Transport Setting first.")
    #     )
    pi = frappe.new_doc("Purchase Invoice")
    pi.supplier = trip.subcontractor
    pi.company = trip.company

    if hasattr(pi, "custom_trip"):
        pi.custom_trip = trip.name

    for row in trip.costs:
        pi.append(
            "items",
            {
                "item_code": frappe.db.get_value(
                    "TMS Cost", row.tms_cost, "purchase_item"
                ),
                "qty": 1,
                "rate": row.amount,
                "description": _("Transport subcontracting — Trip {0}").format(
                    trip.name
                ),
            },
        )
    pi.insert(ignore_permissions=True)
    return pi.name


@frappe.whitelist()
def start_trip(trip, actual_start):
    """Start a Trip (In Transit) only if a POD captioned 'Dispatch Slip' is
    attached. `actual_start` comes from the Start Trip dialog's DateTime
    field on the client."""

    trip = frappe.get_doc("Trip", trip)
    if trip.status == "Cancelled":
        frappe.throw(_("Cannot start a Cancelled Trip."))

    tractor_status = frappe.db.get_value("Tractor", trip.tractor, "status")
    if tractor_status != "Available":
        in_transit_trip = frappe.db.get_value(
            "Trip", {"status": "In Transit", "tractor": trip.tractor}, "name"
        )
        frappe.throw(
            f"Tractor {trip.tractor} is not available. Please complete the in-transit trip ({in_transit_trip}) before starting a new trip."
        )

    trailer_status = frappe.db.get_value("Trailer", trip.trailer, "status")
    if trailer_status != "Available":
        in_transit_trip = frappe.db.get_value(
            "Trip", {"status": "In Transit", "trailer": trip.trailer}, "name"
        )
        frappe.throw(
            f"Trailer {trip.trailer} is not available. Please complete the in-transit trip ({in_transit_trip}) before starting a new trip."
        )

    # if not trip.pods:
    #     frappe.throw(_("Attach a POD before starting this Trip."))

    trip.actual_start = get_datetime(actual_start)
    trip.status = "In Transit"
    trip.save()
    return trip.name
