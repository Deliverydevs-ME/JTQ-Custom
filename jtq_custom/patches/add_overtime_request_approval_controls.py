import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(get_custom_fields(), update=True)
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
