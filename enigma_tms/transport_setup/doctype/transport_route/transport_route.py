import frappe
from frappe.model.document import Document


class TransportRoute(Document):
    def validate(self):
        self.set_route_name()
        self.set_cross_border()

    def set_route_name(self):
        frm = self.from_location or "?"
        to = self.to_location or "?"
        # Prefer human-readable location names for the title.
        frm_name = frappe.db.get_value("Transport Location", self.from_location, "location_name") or frm
        to_name = frappe.db.get_value("Transport Location", self.to_location, "location_name") or to
        self.route_name = f"{frm_name} → {to_name}"

    def set_cross_border(self):
        self.is_cross_border = 1 if (self.from_country and self.to_country and self.from_country != self.to_country) else 0
