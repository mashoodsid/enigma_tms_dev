# Enigma TMS

Transport Management System for a domestic Saudi road-transport (trailer fleet) business — owned + outsourced fleet, hybrid lane-based pricing, multi-lane orders, trip dispatch with office-attached photo POD, and ERPNext-native finance.

Built per blueprint **v2.1**. Standalone Frappe v15 app; finance (Sales/Purchase Invoice, VAT/ZATCA, GL) is handled by ERPNext.

## Flow

```
Transport Order (priced, multi-lane) → Create Trip(s) per lane → execute stops
→ office-attached photo POD → Sales/Purchase Invoice + owned-trip cost capture → profit
```

## Modules

- **Transport Setup** — Tractor, Trailer, Trailer Type, Transport Location, Transport Route
- **Transport Pricing** — Customer Rate Card, Subcontractor Rate Card
- **Transport Operations** — Transport Order, Trip, Transport Setting

## Install

```bash
cd frappe-bench
bench get-app /path/to/enigma_tms        # or: bench get-app <git-url>
bench --site <your-site> install-app enigma_tms
bench --site <your-site> migrate
```

Requires: Frappe v15, ERPNext v15, Python 3.10+.

## License

MIT
