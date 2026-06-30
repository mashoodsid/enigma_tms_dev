import frappe
from frappe.model.document import Document


class Trailer(Document):
    def validate(self):
        if self.ownership == "Owned":
            self.subcontractor = None
