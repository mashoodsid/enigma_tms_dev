# Enigma TMS — Quick Start Guide

Enigma TMS is a transport-management app for a road-freight (trailer) operation, built on ERPNext. It runs the full journey: **Transport Order → Trip (dispatch) → Proof of Delivery → Invoicing**, with hybrid lane-based pricing, owned + outsourced fleet, and ERPNext-native finance (VAT, GL, P&L).

---

## 1. Access

- **URL:** https://tms.enigmaerp.com
- **Login:** `Administrator` (or a user assigned the roles below)
- Everything lives under the **Transport Operations** workspace (left sidebar).

---

## 2. Key concepts (read once)

| Term | Meaning |
|---|---|
| **Tractor** | The prime mover (engine). Carries driver, odometer, fuel. Owned or Outsourced. |
| **Trailer** | The load unit. Has a type (Flatbed, Lowbed, Reefer…) and capacity. Owned or Outsourced. |
| **Transport Route (Lane)** | A From → To pair (e.g. Jeddah Port → Riyadh DC). |
| **Customer Rate Card** | The selling price per lane × trailer type (base + extra-stop + fuel + detention reference). Must be **Active**. |
| **Subcontractor Rate Card** | The buying cost per lane for an outsourced carrier. |
| **Transport Order** | The priced job. Can hold **multiple lanes**; each stop is tagged to its lane. |
| **Trip** | One trailer's run for a lane. A lane with N trailers generates N trips. |
| **POD** | Proof of delivery — photo(s) attached per drop stop by the office. |

---

## 3. End-to-end walkthrough (the demo flow)

> A complete sample (customer, fleet, routes, rate card, 3 orders, trips, POD, invoices) is already loaded so the dashboard and reports show live figures. The steps below let you run a **new** job yourself.

### Step 1 — Masters (one-time, mostly already set up)
Under **Setup** on the workspace:
1. **Trailer Type** — e.g. Flatbed, Lowbed.
2. **Transport Location** — your pickup/drop points (name, type, city).
3. **Transport Route** — pick a From and To location (the name builds automatically).
4. **Tractor** and **Trailer** — add your units; set **Ownership** (Owned, or Outsourced + the subcontractor supplier).
5. **Driver** — name + licence expiry (a trip is blocked if the driver's licence has expired).

### Step 2 — Pricing
Under **Pricing → Customer Rate Card**: create a card, set **Status = Active**, and add a line per lane:
- Route, Trailer Type, **Base Rate** (per trailer), optional Extra-Stop charge, Fuel Surcharge %, and Detention reference (free hours + rate/hour).
- (For outsourced work, add a **Subcontractor Rate Card** the same way.)

### Step 3 — Create a Transport Order
**Operations → Transport Order → New**:
1. Pick the **Customer**, set Billing Mode (Per Order = one invoice; Per Trip = invoice per trip).
2. **Lanes table:** add a row per lane — Route, Trailer Type, number of Trailers.
3. **Stops table:** add the pickups/drops. **Tag each stop with its Lane #** (1 = first lane, 2 = second…), and set the sequence and type (Pickup/Drop).
4. **Save**, then **Submit**. The price is pulled automatically from the active rate card and VAT is applied. (If no active rate matches the lane, submission is blocked — fix the rate card.)

### Step 4 — Generate Trips
On the submitted order click **Create → Create Trip(s)**. One trip is created per trailer, pre-loaded with that lane's stops and an even share of the selling value.

### Step 5 — Dispatch & run each Trip
Open each Trip (or use the **Dispatch Board** — Trip list → Kanban view):
1. Assign **Tractor**, **Trailer**, **Driver**; set Actual Start.
2. **Submit** the trip (checks licence + prevents double-booking the same asset).
3. As it runs, update **Status** (Assigned → Dispatched → … → Delivered → Completed) and the **stops** (arrival/departure times feed the detention suggestion).

### Step 6 — Proof of Delivery
When the driver sends the delivery photo (e.g. via WhatsApp), the office adds it to the trip's **POD** table — `Stop Seq` = the drop's sequence, attach the photo. **A trip can't reach Delivered/Completed until every drop has at least one POD photo.**

### Step 7 — Costs & profit
- **Owned trip:** add **Costs** rows (Fuel, Driver Pay, Tolls…). Trip Profit = selling − costs, shown on the trip. (Costs also post to the GL.)
- **Outsourced trip:** the subcontractor cost auto-fills from the Subcontractor Rate Card on submit.

### Step 8 — Invoice
- **Sales Invoice:** on the Transport Order click **Create → Sales Invoice** (consolidated or per-trip, per the billing mode). VAT is applied automatically.
- **Purchase Invoice (outsourced):** on the outsourced Trip click **Create → Purchase Invoice** for the subcontractor cost.
- When invoices are submitted, the order moves to **Closed**.

---

## 4. Dashboard & reports

- **Workspace dashboard:** KPI cards (Active Trips, In Transit, Open Orders, Trip Profit this month, fleet availability, routes, rate cards) + charts (trips per day, trip profit per month, by status, owned vs outsourced, by route, by trailer type).
- **Operations Dashboard** shortcut → a full charts page.
- **Reports** (Reports & Dashboard card): Trip Profitability, Route Profitability, Fleet Utilization, Un-invoiced Completed Trips, Outstanding Subcontractor Costs, Detention Captured vs Billed.

---

## 5. Roles

| Role | Does |
|---|---|
| **Order Desk** | Create & price Transport Orders |
| **Dispatcher** | Trips, assign tractor/trailer/driver, update stops, attach POD |
| **Transport Finance** | Invoicing, rate cards |
| **Transport Manager** | Everything + reports + price overrides |

Assign roles in **User** (avatar → Users) as needed.

---

## 6. Sample / demo data

The site is pre-loaded with demo data (customer "TMS Demo Customer", a small fleet, routes, an active rate card, 3 orders with trips, POD, and posted invoices). To remove just the demo orders/trips later:

```
bench --site tms.enigmaerp.com execute enigma_tms.demo.clear
```

---

## 7. What V1 includes — and what's next

**Included:** masters, hybrid lane pricing, multi-lane orders, trip dispatch + double-booking protection, office-attached photo POD, owned/outsourced costing + trip profit, detention capture, Sales/Purchase invoicing with 15% VAT + GL, dashboard, 6 reports, Kanban dispatch board.

**Planned (next phases):** driver mobile app with in-field POD, live GPS/map tracking, automated dispatch/route optimisation, driver shift scheduling, geofences, ZATCA Phase-2 (Fatoora) e-invoicing, and a customer self-service portal.

---

## 8. Notes for the administrator

- App id: `enigma_tms` · runs on Frappe/ERPNext v15.
- Global pricing/finance toggles live in **Transport Setting** (default billing mode, fuel-surcharge basis, default VAT template, service items, owned-cost GL accounts, licence-expiry gate).
- Owned-trip costs post to the GL via a Journal Entry (configurable in Transport Setting).