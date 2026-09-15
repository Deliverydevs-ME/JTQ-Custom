import frappe


def execute():
	fieldname = "custom_overtime_request_approver"
	custom_field = frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": fieldname})
	if custom_field:
		frappe.db.set_value("Custom Field", custom_field, "options", "User", update_modified=False)

	if frappe.db.exists("DocField", {"parent": "Employee", "fieldname": "overtime_request_approver"}):
		frappe.db.set_value(
			"DocField",
			{"parent": "Employee", "fieldname": "overtime_request_approver"},
			"options",
			"User",
			update_modified=False,
		)

	frappe.clear_cache(doctype="Employee")
