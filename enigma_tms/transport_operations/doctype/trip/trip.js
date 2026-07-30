frappe.ui.form.on("Trip", {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.ownership === "Outsourced" && frm.doc.status !== "Cancelled") {
            frm.add_custom_button(__("Purchase Invoice"), () => {
                frappe.call({
                    method: "enigma_tms.transport_operations.doctype.trip.trip.create_purchase_invoice",
                    args: { trip_name: frm.doc.name },
                    freeze: true,
                    callback: (r) => {
                        if (r.message) {
                            frappe.msgprint(__("Created: {0}", [r.message]));
                        }
                    },
                });
            }, __("Create"));
        }

        if (frm.doc.docstatus === 1 && frm.doc.status === "Assigned") {
            frm.add_custom_button(__("Start Trip"), () => {
                show_start_trip_dialog(frm);
            });
        }

        // Quick visual cue for the POD gate on drop stops.
        if (frm.doc.docstatus != 1) {
            frm.dashboard.set_headline(`The assigned tractor status is currently "On Trip". This trip can only be started when tractor status becomes "Available".`)
        }


        // if (frm.doc.docstatus === 1 && ["Delivered", "Completed"].indexOf(frm.doc.status) === -1) {
        //     const drops = (frm.doc.stops || []).filter((s) => s.stop_type === "Drop");
        //     const pod_seqs = (frm.doc.pods || []).map((p) => p.stop_seq);
        //     const missing = drops.filter((s) => pod_seqs.indexOf(s.seq) === -1);
        //     if (missing.length) {
        //         frm.dashboard.set_headline(
        //             __("{0} drop stop(s) still need a POD photo before this trip can be Delivered/Completed.", [missing.length])
        //         );
        //     }
        // }
    },

    tractor(frm) {
        const { tractor, change_driver_trailer } = frm.doc;
        console.log(tractor, change_driver_trailer)
        console.log(tractor && !change_driver_trailer)
        if (tractor && !change_driver_trailer) {
            frappe.db.get_value("Tractor", tractor, ['default_driver', "default_trailer"]).then(res => {
                console.log(res)
                const { message: { default_driver, default_trailer } } = res;
                // if (default_driver && default_trailer) {
                frm.set_value("trailer", default_trailer || "")
                frm.set_value("driver", default_driver || "")
                // }
            })
        }
    }
});

function show_start_trip_dialog(frm) {
    const has_dispatch_slip = (frm.doc.pods || []).some(
        (p) => (p.caption || "").trim() === "Dispatch Slip"
    );
    if (!frm.doc.pods?.length) {
        frappe.msgprint({
            title: __("POD Required"),
            indicator: "red",
            message: __('Attach a POD before starting this trip.'),
        });
        return;
    }

    const dialog = new frappe.ui.Dialog({
        title: __("Start Trip"),
        fields: [
            {
                fieldname: "actual_start",
                fieldtype: "Datetime",
                label: __("Actual Start"),
                reqd: 1,
                default: frappe.datetime.now_datetime(),
            },
        ],
        primary_action_label: __("Start Trip"),
        primary_action: (values) => {
            frappe.call({
                method: "enigma_tms.transport_operations.doctype.trip.trip.start_trip",
                args: {
                    trip: frm.doc.name,
                    actual_start: values.actual_start,
                },
                freeze: true,
                freeze_message: __("Starting trip..."),
                callback: (r) => {
                    if (r.message) {
                        dialog.hide();
                        frappe.msgprint(__("Trip started."));
                        frm.reload_doc();
                    }
                },
            });
        },
    });

    dialog.show();
}