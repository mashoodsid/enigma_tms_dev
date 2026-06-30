import frappe
from frappe.model.document import Document


class TransportSetting(Document):
    pass


def get_settings():
    return frappe.get_cached_doc("Transport Setting")
