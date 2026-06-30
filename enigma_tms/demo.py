"""Demo data seeder for Enigma TMS — populates masters, orders, trips, POD and
costs so the dashboard/reports show realistic figures. Idempotent: re-running
skips if the demo customer already exists. NOT installed automatically — run with:

    bench --site <site> execute enigma_tms.demo.seed
    bench --site <site> execute enigma_tms.demo.clear   # to remove demo data
"""

import frappe
from frappe.utils import add_days, add_to_date, today, now_datetime

DEMO_CUSTOMER = "TMS Demo Customer"
DEMO_SUPPLIER = "Gulf Carriers (Demo)"
MARK = {"tms_demo": 1}


def _goc(doctype, key_filters, values):
    name = frappe.db.exists(doctype, key_filters)
    if name:
        return frappe.get_doc(doctype, name)
    doc = frappe.get_doc(dict(doctype=doctype, **values))
    doc.flags.ignore_permissions = True
    doc.flags.ignore_mandatory = False
    doc.insert()
    return doc


def seed():
    if frappe.get_all("Transport Order", filters={"customer": DEMO_CUSTOMER}, limit=1):
        print("Demo orders already exist — run enigma_tms.demo.clear first to reseed.")
        return

    # ---- POD demo file (reused on every proof row) ----
    podfile = frappe.get_doc({
        "doctype": "File", "file_name": "tms_demo_pod.txt", "is_private": 0,
        "content": "Enigma TMS demo proof of delivery",
    })
    podfile.flags.ignore_permissions = True
    podfile.insert()
    pod_url = podfile.file_url

    # ---- Masters ----
    flatbed = _goc("Trailer Type", {"type_name": "Flatbed"}, {"type_name": "Flatbed", "default_capacity_tons": 25})
    lowbed = _goc("Trailer Type", {"type_name": "Lowbed"}, {"type_name": "Lowbed", "default_capacity_tons": 40})

    def loc(nm, typ):
        return _goc("Transport Location", {"location_name": nm},
                    {"location_name": nm, "location_type": typ, "country": "Saudi Arabia"})
    jeddah = loc("Jeddah Port", "Port")
    riyadh = loc("Riyadh DC", "Warehouse")
    dammam = loc("Dammam Yard", "Factory")

    def route(frm, to, km, hrs):
        existing = frappe.get_all("Transport Route",
                                  filters={"from_location": frm.name, "to_location": to.name}, limit=1)
        if existing:
            return frappe.get_doc("Transport Route", existing[0].name)
        d = frappe.get_doc({"doctype": "Transport Route", "from_location": frm.name,
                            "to_location": to.name, "distance_km": km, "standard_transit_hours": hrs})
        d.flags.ignore_permissions = True
        d.insert()
        return d
    r1 = route(jeddah, riyadh, 949, 10)   # Jeddah -> Riyadh
    r2 = route(jeddah, dammam, 1340, 14)  # Jeddah -> Dammam

    # subcontractor
    sub = _goc("Supplier", {"supplier_name": DEMO_SUPPLIER},
               {"supplier_name": DEMO_SUPPLIER, "supplier_group": "Transporters",
                "supplier_type": "Company", "default_currency": "SAR"})

    # owned fleet
    def tractor(plate, ownership="Owned", subc=None):
        return _goc("Tractor", {"plate_number": plate},
                    {"plate_number": plate, "ownership": ownership, "subcontractor": subc, "make_model": "Volvo FH"})
    def trailer(plate, ttype, ownership="Owned", subc=None):
        return _goc("Trailer", {"plate_number": plate},
                    {"plate_number": plate, "trailer_type": ttype, "ownership": ownership,
                     "subcontractor": subc, "capacity_tons": 25})
    trc = [tractor(f"TRC-{i}") for i in range(1, 4)]
    otrc = tractor("OTRC-1", "Outsourced", sub.name)
    trl = [trailer("FL-1", flatbed.name), trailer("FL-2", flatbed.name), trailer("LB-1", lowbed.name)]
    otrl = trailer("OFL-1", flatbed.name, "Outsourced", sub.name)

    def driver(nm):
        existing = frappe.get_all("Driver", filters={"full_name": nm}, limit=1)
        if existing:
            return frappe.get_doc("Driver", existing[0].name)
        d = frappe.get_doc({"doctype": "Driver", "full_name": nm, "status": "Active",
                            "custom_driver_type": "Owned", "custom_license_expiry": add_days(today(), 365)})
        d.flags.ignore_permissions = True
        d.insert()
        return d
    drv = [driver(n) for n in ["Faisal Al-Harbi", "Omar Khan", "Yusuf Ali"]]
    odrv = driver("Subcon Driver")

    # ---- Rate cards ----
    crc = frappe.get_doc({
        "doctype": "Customer Rate Card", "customer": _customer().name, "status": "Active",
        "currency": "SAR", "valid_from": add_days(today(), -30),
        "lines": [
            _rcl(r1, flatbed, 2500), _rcl(r1, lowbed, 3500), _rcl(r2, flatbed, 1800),
        ],
    })
    crc.flags.ignore_permissions = True
    crc.insert()

    scrc = frappe.get_doc({
        "doctype": "Subcontractor Rate Card", "subcontractor": sub.name, "status": "Active",
        "currency": "SAR", "valid_from": add_days(today(), -30),
        "lines": [_rcl(r1, lowbed, 2800), _rcl(r2, flatbed, 1400)],
    })
    scrc.flags.ignore_permissions = True
    scrc.insert()

    cust = _customer()

    # ---- Order A: 2 lanes, owned ----
    oa = _order(cust, "Per Order", [
        dict(route=r1.name, trailer_type=flatbed.name, qty=2,
             stops=[("Pickup", jeddah.name), ("Drop", riyadh.name)]),
        dict(route=r2.name, trailer_type=flatbed.name, qty=1,
             stops=[("Pickup", jeddah.name), ("Drop", dammam.name)]),
    ])
    trips_a = _make_trips(oa)
    # T1, T2 completed (owned); T3 in transit
    _run_trip(trips_a[0], trc[0], trl[0], drv[0], "Completed", -9, pod_url, detention=True)
    _run_trip(trips_a[1], trc[1], trl[1], drv[1], "Completed", -8, pod_url)
    _run_trip(trips_a[2], trc[2], trl[2], drv[2], "In Transit", -3, pod_url)

    # ---- Order B: outsourced lowbed ----
    ob = _order(cust, "Per Trip", [
        dict(route=r1.name, trailer_type=lowbed.name, qty=1,
             stops=[("Pickup", jeddah.name), ("Drop", riyadh.name)]),
    ])
    trips_b = _make_trips(ob)
    _run_trip(trips_b[0], otrc, otrl, odrv, "Completed", -6, pod_url, outsourced=True)

    # ---- Order C: 2 flatbed; one dispatched, one left assigned (draft) ----
    oc = _order(cust, "Per Order", [
        dict(route=r2.name, trailer_type=flatbed.name, qty=2,
             stops=[("Pickup", jeddah.name), ("Drop", dammam.name)]),
    ])
    trips_c = _make_trips(oc)
    _run_trip(trips_c[0], trc[0], trl[0], drv[0], "Dispatched", -1, pod_url)
    # trips_c[1] left as Assigned draft

    frappe.db.commit()
    print("Seeded: 3 orders, %d trips, masters + rate cards." % (len(trips_a) + len(trips_b) + len(trips_c)))


def _customer():
    if frappe.db.exists("Customer", DEMO_CUSTOMER):
        return frappe.get_doc("Customer", DEMO_CUSTOMER)
    cg = "All Customer Groups" if frappe.db.exists("Customer Group", "All Customer Groups") else frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
    terr = "All Territories" if frappe.db.exists("Territory", "All Territories") else frappe.db.get_value("Territory", {"is_group": 0}, "name")
    d = frappe.get_doc({"doctype": "Customer", "customer_name": DEMO_CUSTOMER,
                        "customer_group": cg, "territory": terr})
    d.flags.ignore_permissions = True
    d.insert()
    return d


def _rcl(route, ttype, base):
    return {"route": route.name, "trailer_type": ttype.name, "base_rate": base,
            "extra_stop_charge": 300, "extra_stop_basis": "Flat", "fuel_surcharge_pct": 5,
            "detention_free_hours": 2, "detention_rate_per_hour": 50, "detention_basis": "Per Trailer",
            "min_charge": 0}


def _order(cust, billing, lanes):
    items, stops = [], []
    for i, lane in enumerate(lanes, start=1):
        items.append({"route": lane["route"], "trailer_type": lane["trailer_type"], "qty_trailers": lane["qty"]})
        for seq, (stype, locname) in enumerate(lane["stops"], start=1):
            stops.append({"order_line": i, "seq": seq, "stop_type": stype, "location": locname,
                          "planned_datetime": now_datetime()})
    o = frappe.get_doc({"doctype": "Transport Order", "customer": cust.name, "order_date": today(),
                        "currency": "SAR", "billing_mode": billing, "items": items, "stops": stops})
    o.flags.ignore_permissions = True
    o.insert()
    o.submit()
    return o


def _make_trips(order):
    from enigma_tms.transport_operations.doctype.transport_order.transport_order import create_trips
    res = create_trips(order.name)
    return [frappe.get_doc("Trip", n) for n in res["created"]]


def _run_trip(trip, tractor, trailer, driver, status, start_day_offset, pod_url, outsourced=False, detention=False):
    start = add_to_date(today(), days=start_day_offset, hours=6, as_datetime=True)
    end = add_to_date(start, hours=12)
    trip.tractor = tractor.name
    trip.trailer = trailer.name
    trip.driver = driver.name
    trip.actual_start = start
    trip.actual_end = end
    trip.odometer_start = 100000
    trip.odometer_end = 100000 + 950
    trip.status = status
    # stops execution; for completed/delivered trips attach a POD to EVERY stop
    # (completion now requires a POD on each stop) so auto-complete marks them done.
    for s in trip.stops:
        s.arrival_datetime = add_to_date(start, hours=2)
        # detention demo: long wait at one stop
        s.departure_datetime = add_to_date(start, hours=(6 if detention else 3))
        if status in ("Completed", "Delivered"):
            cap = "Delivery Note" if s.stop_type == "Drop" else "Cargo Condition"
            trip.append("pods", {"stop_seq": s.seq, "caption": cap, "photo": pod_url})
    # costs
    if outsourced:
        pass  # subcontractor cost auto-filled in before_submit
    else:
        trip.append("costs", {"cost_type": "Fuel", "description": "Diesel", "amount": 900})
        trip.append("costs", {"cost_type": "Driver Pay", "description": "Trip allowance", "amount": 400})
        trip.append("costs", {"cost_type": "Tolls", "description": "Highway", "amount": 120})
    trip.flags.ignore_permissions = True
    trip.save()
    trip.submit()


SERVICE_ITEMS = [
    ("Freight Linehaul", "freight_item"),
    ("Extra Stop", "extra_stop_item"),
    ("Detention", "detention_item"),
    ("Fuel Surcharge", "fuel_surcharge_item"),
]


def setup_finance():
    """VAT account + Sales Taxes template + service items + wire Transport Setting.
    Uses the existing Company and its default accounts. Idempotent."""
    company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
    comp = frappe.get_doc("Company", company)
    abbr = comp.abbr

    # 1) VAT account under Duties and Taxes
    duties = frappe.db.get_value("Account", {"company": company, "account_name": "Duties and Taxes", "is_group": 1}, "name") \
        or frappe.db.get_value("Account", {"company": company, "account_type": "Tax", "is_group": 1}, "name")
    vat_account = frappe.db.get_value("Account", {"company": company, "account_name": "VAT 15%"}, "name")
    if not vat_account and duties:
        acc = frappe.get_doc({"doctype": "Account", "account_name": "VAT 15%", "parent_account": duties,
                              "company": company, "account_type": "Tax", "tax_rate": 15})
        acc.flags.ignore_permissions = True
        acc.insert()
        vat_account = acc.name

    # 2) Sales Taxes and Charges Template
    tmpl = "KSA VAT 15%"
    if not frappe.db.exists("Sales Taxes and Charges Template", {"title": tmpl, "company": company}):
        t = frappe.get_doc({
            "doctype": "Sales Taxes and Charges Template", "title": tmpl, "company": company,
            "taxes": [{"charge_type": "On Net Total", "account_head": vat_account,
                       "description": "VAT @ 15%", "rate": 15, "cost_center": comp.cost_center}],
        })
        t.flags.ignore_permissions = True
        t.insert()
    tmpl_name = frappe.db.get_value("Sales Taxes and Charges Template", {"title": tmpl, "company": company}, "name")

    # 3) Service items (non-stock)
    for label, _field in SERVICE_ITEMS:
        if not frappe.db.exists("Item", label):
            it = frappe.get_doc({"doctype": "Item", "item_code": label, "item_name": label,
                                 "item_group": "Services", "stock_uom": "Nos", "is_stock_item": 0,
                                 "is_sales_item": 1, "is_purchase_item": 1})
            it.flags.ignore_permissions = True
            it.insert()

    # 4) Wire Transport Setting
    ts = frappe.get_doc("Transport Setting")
    ts.default_sales_taxes_template = tmpl_name
    for label, field in SERVICE_ITEMS:
        setattr(ts, field, label)
    ts.post_owned_costs_to_gl = 1
    ts.owned_cost_expense_account = comp.default_expense_account
    ts.owned_cost_credit_account = comp.default_cash_account
    ts.flags.ignore_permissions = True
    ts.save()
    frappe.db.commit()
    print("Finance set up on company %s (VAT, template, 4 items, Transport Setting)." % company)


def run_invoicing():
    """Create + submit Sales Invoices (per billing mode), Purchase Invoices for
    outsourced trips, and backfill owned-trip GL journal entries."""
    from enigma_tms.transport_operations.doctype.transport_order.transport_order import create_sales_invoice
    from enigma_tms.transport_operations.doctype.trip.trip import create_purchase_invoice

    orders = frappe.get_all("Transport Order", filters={"customer": DEMO_CUSTOMER, "docstatus": 1}, pluck="name")
    si_count = 0
    for o in orders:
        try:
            res = create_sales_invoice(o)
            for si in res.get("sales_invoices", []):
                doc = frappe.get_doc("Sales Invoice", si)
                if doc.docstatus == 0:
                    doc.submit()
                    si_count += 1
        except Exception as e:
            print("  SI skip for %s: %s" % (o, str(e)[:80]))

    pi_count = 0
    out_trips = frappe.get_all("Trip", filters={"customer": DEMO_CUSTOMER, "docstatus": 1,
                                                "ownership": "Outsourced", "status": "Completed"}, pluck="name")
    for t in out_trips:
        try:
            pi = create_purchase_invoice(t)
            doc = frappe.get_doc("Purchase Invoice", pi)
            if doc.docstatus == 0:
                doc.submit()
                pi_count += 1
        except Exception as e:
            print("  PI skip for %s: %s" % (t, str(e)[:80]))

    je_count = 0
    own_trips = frappe.get_all("Trip", filters={"customer": DEMO_CUSTOMER, "docstatus": 1,
                                                "ownership": "Owned", "status": "Completed"}, pluck="name")
    for t in own_trips:
        doc = frappe.get_doc("Trip", t)
        before = frappe.db.count("Journal Entry")
        doc.maybe_post_owned_costs_to_gl()
        if frappe.db.count("Journal Entry") > before:
            je_count += 1

    frappe.db.commit()
    print("Invoicing done: %d Sales Invoices, %d Purchase Invoices, %d owned-cost JEs." % (si_count, pi_count, je_count))


def finalize_demo():
    """One-shot: ensure seed + finance + invoicing all done."""
    if not frappe.db.exists("Customer", DEMO_CUSTOMER):
        seed()
    setup_finance()
    run_invoicing()
    print("Demo finalized.")


def test_pod_autocomplete():
    """Verify: attaching a POD photo to a single-drop trip auto-completes the drop."""
    name = frappe.db.get_value("Trip", {"status": "In Transit", "docstatus": 1}, "name") \
        or frappe.db.get_value("Trip", {"docstatus": 1}, "name")
    t = frappe.get_doc("Trip", name)
    drop = [s for s in t.stops if s.stop_type == "Drop"][0]
    before = drop.status
    t.pods = []                                  # clean any prior test rows
    t.append("pods", {"caption": "Delivery Note", "photo": "/files/tms_demo_pod.txt"})  # no stop_seq on purpose
    t.save()
    frappe.db.commit()
    t.reload()
    drop = [s for s in t.stops if s.stop_type == "Drop"][0]
    return {"trip": name, "before": before, "after": drop.status,
            "pod_linked_seq": [p.stop_seq for p in t.pods]}


def backfill_pods():
    """Make existing completed trips satisfy the new rule (every completed stop
    needs a POD) by adding a POD to any completed stop that lacks one."""
    fixed = []
    names = frappe.get_all("Trip", filters={"docstatus": 1, "status": ["in", ["Completed", "Delivered"]]}, pluck="name")
    for name in names:
        t = frappe.get_doc("Trip", name)
        pod_seqs = {p.stop_seq for p in t.pods if p.stop_seq}
        changed = False
        for s in t.stops:
            if s.status == "Completed" and s.seq not in pod_seqs:
                cap = "Delivery Note" if s.stop_type == "Drop" else "Cargo Condition"
                t.append("pods", {"stop_seq": s.seq, "caption": cap, "photo": "/files/tms_demo_pod.txt"})
                changed = True
        if changed:
            t.save()
            fixed.append(name)
    frappe.db.commit()
    return {"fixed": fixed}


def clear():
    """Remove demo data (best effort, in dependency order)."""
    for dt, filt in [
        ("Trip", {}), ("Transport Order", {}),
    ]:
        for n in frappe.get_all(dt, filters={"customer": DEMO_CUSTOMER}, pluck="name"):
            doc = frappe.get_doc(dt, n)
            if doc.docstatus == 1:
                doc.cancel()
            frappe.delete_doc(dt, n, force=1)
    frappe.db.commit()
    print("Cleared demo trips & orders. (Masters/rate cards left in place.)")
