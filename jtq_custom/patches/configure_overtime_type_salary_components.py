import frappe

def execute():
	field_name = "Overtime Type-custom_applicable_salary_components"
	if frappe.db.get_value("Custom Field", field_name, "fieldtype") not in (None, "Table MultiSelect"):
		# Frappe intentionally prevents changing a Data field to a child table in place.
		# The tracked Overtime Type customization recreates it with the requested table.
		frappe.delete_doc("Custom Field", field_name, force=True, ignore_permissions=True)
