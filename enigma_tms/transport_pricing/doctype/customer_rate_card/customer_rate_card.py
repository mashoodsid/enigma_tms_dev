import frappe
from frappe import _
from frappe.model.document import Document


class CustomerRateCard(Document):
    def validate(self):
        self.validate_unique_lanes()
        self.validate_dates()

    def validate_unique_lanes(self):
        seen = set()

        for line in self.lines:
            key = (line.route, line.trailer_type, line.commodity)
            if key in seen:
                frappe.throw(
                    _(
                        "Duplicate lane in rate card: {0} {1} {3} Each commodity + route + trailer  type may appear once."
                    ).format(line.route, line.trailer_type, line.commodity)
                )
            seen.add(key)

    def validate_dates(self):
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            frappe.throw(_("Valid To cannot be before Valid From."))
