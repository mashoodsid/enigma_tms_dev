frappe.ui.form.on("Transport Order", {
    setup(frm) {
        if (frm.is_new()) {
            frm.set_value("items", [])
            frm.set_value("stops", [])
        }
    },
    refresh(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.status !== "Cancelled") {
            frm.add_custom_button(__("Create Trip(s)"), () => {
                frappe.call({
                    method: "enigma_tms.transport_operations.doctype.transport_order.transport_order.create_trips",
                    args: { order_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Generating trips..."),
                    callback: (r) => {
                        if (r.message) {
                            frappe.msgprint(__("Created {0} trip(s).", [(r.message.created || []).length]));
                            frm.reload_doc();
                        }
                    },
                });
            }, __("Create"));

            frm.add_custom_button(__("Sales Invoice"), () => {
                frappe.call({
                    method: "enigma_tms.transport_operations.doctype.transport_order.transport_order.create_sales_invoice",
                    args: { order_name: frm.doc.name },
                    freeze: true,
                    callback: (r) => {
                        if (r.message) {
                            frappe.msgprint(__("Created: {0}", [(r.message.sales_invoices || []).join(", ")]));
                            frm.reload_doc();
                        }
                    },
                });
            }, __("Create"));
        }
    },
});


function clear_current_row_stop(frm, row) {
    const { route, idx } = row;
    const { stops } = frm.doc;

    const selectedRows = []
    stops?.forEach(r => {
        if (r.order_line == idx) {
            selectedRows.push(r)
        }
    })

    selectedRows.forEach(r => {
        frappe.model.clear_doc(r.doctype, r.name)
    })
    
    frm.refresh_field("stops")
}

function handle_default_stops(frm, row) {
    const { route } = row;
    if (!route) { return }

    frappe.db.get_value("Transport Route", route, ["from_location", "to_location"]).then(res => {
        const { message: { to_location, from_location } } = res;
        console.log(to_location, from_location)
        frm.add_child("stops", {
            "order_line": row.idx,
            "stop_type": "Pickup",
            "seq": 1,
            "location": from_location
        })
        frm.add_child("stops", {
            "order_line": row.idx,
            "stop_type": "Drop",
            "seq": 2,
            "location": to_location
        })
        frm.refresh_field("stops")
    })

}

function remove_stops_for_lane(frm, lane_idx) {
    const remaining = (frm.doc.stops || []).filter((s) => s.order_line !== lane_idx);
    frm.doc.stops = remaining;
    frm.refresh_field("stops");
}

frappe.ui.form.on("Transport Order Item", {
    items_add(frm, cdt, cdn) {
    },
    items_remove(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        remove_stops_for_lane(frm, row.idx);
    },
    route(frm, cdt, cdn) {
        const row = locals[cdt][cdn]
        clear_current_row_stop(frm, row)
        handle_default_stops(frm, row)
        const { route, trailer_type, commodity } = row;
        const { customer } = frm.doc;
        if (!route || !customer || !trailer_type) {
            return
        }

        frappe.call({
            method: "enigma_tms.transport_operations.doctype.transport_order.transport_order.get_customer_route_price",
            args: {
                customer: customer,
                route: route,
                trailer_type: trailer_type,
                commodity: commodity,
            },
            freeze: true,
            freeze_message: __("Getting price..."),
            callback: (r) => {
                if (flt(r.message)) {
                    frappe.model.set_value(cdt, cdn, "base_rate", flt(r.message));
                }
            },
        });
    },
    qty_trailers(frm, cdt, cdn) {
        const row = locals[cdt][cdn]
        set_lane_row_total(frm, row)
    },
    per_truck_trips(frm, cdt, cdn) {
        const row = locals[cdt][cdn]
        set_lane_row_total(frm, row)
    },
    qty(frm, cdt, cdn) {
        const row = locals[cdt][cdn]
        set_lane_row_total(frm, row)
    },
    base_rate(frm, cdt, cdn) {
        const row = locals[cdt][cdn]
        set_lane_row_total(frm, row)
    },
    line_total(frm, cdt, cdn) {
        calculate_totals(frm);
    }
})

function set_lane_row_total(frm, row) {
    const qt = flt(row.qty_trailers) || 1;
    const q = flt(row.qty) || 1;
    const br = flt(row.base_rate);

    frappe.model.set_value(row.doctype, row.name, "line_total", q * br);

    let total_weight = 0
    frm.doc.items.forEach(i => {
        total_weight += i.qty
    })
    frm.set_value("total_weight", total_weight)
}

function calculate_totals(frm) {
    let total = 0;
    (frm.doc.items || []).forEach(d => {
        total += flt(d.line_total);
    });
    frm.set_value("total", total);
    frm.set_value("selling_total", total);
    let taxes = flt(frm.doc.total_taxes);
    frm.set_value("grand_total", total + taxes);
}

frappe.ui.form.on("Transport Stop", {
    stops_add(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.order_line && frm.doc.items && frm.doc.items.length) {
            frappe.model.set_value(cdt, cdn, "order_line", frm.doc.items[frm.doc.items.length - 1].idx);
        }
    },

    order_line(frm, cdt, cdn) {
        const row = locals[cdt][cdn];

        const valid = (frm.doc.items || []).some((r) => r.idx === row.order_line);
        if (row.order_line && !valid) {
            frappe.msgprint({
                title: __("Invalid Lane #"),
                message: __("Lane #{0} does not exist in the Lanes table.", [row.order_line]),
                indicator: "orange",
            });
        }

        // Lane changed -> the set of valid locations changed, so clear
        // the previously selected location to force a fresh, valid pick.
        frappe.model.set_value(cdt, cdn, "location", null);
        frm.refresh_field("stops");
    },
});