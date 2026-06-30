import frappe
from frappe.model.document import Document


class Tractor(Document):
    def validate(self):
        if self.ownership == "Owned":
            self.subcontractor = None
