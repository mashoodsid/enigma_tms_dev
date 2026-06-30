# Enigma TMS — scaffold notes

Generated from blueprint **v2.1**. This documents how to install, where the scaffold
deviates from the blueprint (and why), and what's intentionally left for the next slice.

## Install (on a Frappe v15 + ERPNext v15 bench)

```bash
cd frappe-bench
bench get-app /path/to/enigma_tms          # or a git URL
bench --site <site> install-app enigma_tms
bench --site <site> migrate
```

`after_install` creates the roles, custom fields, the Transport Setting single, and the
"Transporters" supplier group. Requires **Python 3.10+**.

After install, open **Transport Setting** and set: default service items (Freight Linehaul,
Extra Stop, Detention, Fuel Surcharge — create as non-stock sales Items), default Sales
Taxes template (KSA VAT 15%), and the owned-cost GL accounts (debit expense + credit
cash/clearing) since GL posting is enabled.

## Deviations from blueprint v2.1 (forced by Frappe, or pragmatic)

1. **POD table location.** The blueprint drew `pod` as a table *inside* the Transport Stop.
   Frappe has **no grandchild tables** (Stop is already a child of Trip), so **Trip POD is a
   child table on the Trip** (`pods`), each row referencing its drop via **`stop_seq`**. The
   no-POD-no-complete gate is enforced in `trip.py` (`enforce_pod_gate`).
2. **`order_line` = lane number.** A stop ties to its lane via `order_line` = the Order Item's
   **1-based idx** (Int), since child rows can't be stably linked before save. The pricing
   engine and trip generator group stops by this lane number.
3. **Shared `Rate Card Line`.** One child doctype is reused by both Customer and Subcontractor
   rate cards (DRY). On the subcontractor card the same fields (`base_rate`, …) are read as
   **cost**. Functionally identical to the blueprint's `base_cost` naming.
4. **Owned-cost GL posting (per your decision "also post to GL").** On a completed **owned**
   trip, `trip.py` posts a **Journal Entry** debiting the configured expense account and
   crediting the configured cash/clearing account for the non-subcontractor cost rows. If
   either account is unset it skips with a warning. Idempotent (guards on a user-remark key).
5. **Invoice links via custom fields.** `Sales Invoice.custom_transport_order` and
   `Purchase Invoice.custom_trip` are added in `install.py` to drive the Order→`Closed`
   transition and PI linkage.
6. **Trip assignment not field-mandatory.** Tractor/Trailer/Driver are required at **submit**
   (`before_submit`), not at field level, so `Create Trip(s)` can generate unassigned stubs.
7. **`allow_on_submit`** on Trip status / stops / pods / costs / actual times / odometer, so
   the office works the trip after it's dispatched (submitted).

## Implemented (V1 per blueprint §10)

- Masters: Tractor, Trailer, Trailer Type, Transport Location, Transport Route (+ Driver/
  Customer/Supplier extensions via custom fields).
- Pricing: Customer & Subcontractor Rate Cards + server-side engine (`pricing.py`, §4.3) +
  deterministic resolution (§4.4).
- Transport Order: multi-lane, stops-on-line, server-side pricing, credit gate, status
  lifecycle (§5.4), `Create Trip(s)` (per-lane, even per-trip selling allocation §4.5).
- Trip: tractor+trailer+driver, overlap double-booking check, licence gate, 8-step status,
  Trip Cost capture, outsourced subcontractor auto-cost, owned-cost GL posting, per-drop
  multi-photo POD gate, activity log.
- Finance: Sales Invoice per `billing_mode`, Purchase Invoice for outsourced trips.
- Derived asset status (§3.6), Workspace, roles.

## Next slice (still V1 scope, not yet generated)

- **Reports** (§8.5): Trip Profitability, Fleet Utilization, Route Profitability,
  Un-invoiced Completed Trips, Outstanding Subcontractor Costs, Detention Captured vs Billed
  — add as Query/Script Reports.
- **Dashboard**: Number Cards + Dashboard Charts as fixtures on the Workspace.
- **Dispatch board**: a Kanban Board on Trip grouped by `status` (+ drag-to-assign JS).
- **Detention suggestion (§5.3)**: compute `max(0, waiting − free)` per stop from
  arrival/departure and surface it as a suggested manual Detention invoice line.
- **`frappe.realtime`** push for the dispatch board.

## Validation done here

All 16 doctype JSONs parse; all Python compiles (syntax). Runtime behaviour is untestable
without a bench (no local Frappe; Python here is 3.9). Install on a v15 bench to exercise.