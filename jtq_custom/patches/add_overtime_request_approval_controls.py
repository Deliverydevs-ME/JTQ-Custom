import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


STATUS_MANAGER_ROLE = "Overtime Slip Request Status Manager"


def execute():
	create_custom_fields(get_custom_fields(), update=True)
	ensure_status_manager_role()
	frappe.clear_cache(doctype="HR Settings")


def get_custom_fields():
	return {
		"HR Settings": [
			{
				"fieldname": "custom_prevent_self_overtime_approval",
				"fieldtype": "Check",
				"label": "Prevent Self Approval for Overtime Request",
				"default": "0",
				"description": (
					"Prevent an employee from approving their own Overtime Slip Request, "
					"even when they are the configured approver or have an HR approval role."
				),
				"insert_after": "prevent_self_expense_approval",
			},
		]
	}


def ensure_status_manager_role():
	if frappe.db.exists("Role", STATUS_MANAGER_ROLE):
		return

	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": STATUS_MANAGER_ROLE,
			"desk_access": 1,
		}
	).insert(ignore_permissions=True)
