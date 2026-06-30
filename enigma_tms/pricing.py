"""Server-side pricing engine and deterministic rate resolution.

Blueprint refs: §4.3 (formula), §4.4 (resolution), §4.5 (per-trip allocation).
All money math runs here (server-side), never JS-only, so API/bench writes
produce correct totals.
"""

import frappe
from frappe import _
from frappe.utils import flt, cint, getdate


def compute_line_pricing(
    *,
    base_rate,
    qty_trailers,
    qty=1,
    total_stops,
    extra_stop_charge=0,
    extra_stop_basis="Flat",
    fuel_surcharge_pct=0,
    min_charge=0,
    apply_fuel_on="Linehaul",
):
    """Return the priced components for one lane (§4.3).
    Detention is NOT computed here — it is execution-time and billed manually (§5.3).
    Works identically for selling (Customer Rate Card) and buying (Subcontractor).
    """
    base_rate = flt(base_rate)
    qty_trailers = cint(qty_trailers) or 1
    qty = flt(qty) or 1
    total_stops = cint(total_stops)
    extra_stop_charge = flt(extra_stop_charge)
    fuel_surcharge_pct = flt(fuel_surcharge_pct)
    min_charge = flt(min_charge)
    extra_stops = max(0, total_stops - 2)  # 1 pickup + 1 drop are standard
    total_trips = qty_trailers
    linehaul = total_trips * (qty * base_rate)
    stop_multiplier = total_trips if extra_stop_basis == "Per Trailer" else 1
    extra_stop_amount = extra_stops * extra_stop_charge * stop_multiplier
    fuel_base = linehaul + (extra_stop_amount if apply_fuel_on == "Subtotal" else 0)
    fuel_surcharge = fuel_base * fuel_surcharge_pct / 100.0
    computed = linehaul + extra_stop_amount + fuel_surcharge
    floor = min_charge * total_trips
    line_total = max(floor, computed)
    return {
        "extra_stops": extra_stops,
        "linehaul": flt(linehaul, 2),
        "extra_stop_amount": flt(extra_stop_amount, 2),
        "fuel_surcharge_amount": flt(fuel_surcharge, 2),
        "line_total": flt(line_total, 2),
    }


def resolve_rate_line(card_doctype, party_field, party, route, trailer_type, on_date):
    on_date = getdate(on_date)

    cards = frappe.get_all(
        card_doctype,
        filters={"status": "Active"},
        fields=["name", party_field, "valid_from", "valid_to"],
    )

    def date_ok(c):
        vf = getdate(c.valid_from) if c.valid_from else None
        vt = getdate(c.valid_to) if c.valid_to else None
        if vf and on_date < vf:
            return False
        if vt and on_date > vt:
            return False
        return True

    cards = [c for c in cards if date_ok(c)]
    if not cards:
        return None

    specific = [c for c in cards if c.get(party_field) == party]
    candidates = specific if specific else [c for c in cards if not c.get(party_field)]
    if not candidates:
        return None

    # Tie-break: latest valid_from (None sorts oldest).
    candidates.sort(
        key=lambda c: getdate(c.valid_from) if c.valid_from else getdate("1900-01-01"),
        reverse=True,
    )

    for c in candidates:
        card = frappe.get_doc(card_doctype, c["name"])
        for line in card.lines:
            if line.route == route and line.trailer_type == trailer_type:
                return line.as_dict()
    return None


def resolve_customer_rate(customer, route, trailer_type, on_date):
    return resolve_rate_line(
        "Customer Rate Card", "customer", customer, route, trailer_type, on_date
    )


def resolve_subcontractor_rate(subcontractor, route, trailer_type, on_date):
    return resolve_rate_line(
        "Subcontractor Rate Card",
        "subcontractor",
        subcontractor,
        route,
        trailer_type,
        on_date,
    )
