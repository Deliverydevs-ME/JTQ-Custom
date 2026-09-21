import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	ensure_employee_branch_urdu_is_data()
	create_custom_fields(get_custom_fields(), update=True)
	ensure_employee_branch_urdu_is_data()
	fix_branch_field_order()
	backfill_employee_branch_urdu()
	frappe.clear_cache(doctype="Branch")
	frappe.clear_cache(doctype="Employee")


def get_custom_fields():
	return {
		"Branch": [
			{
				"fieldname": "custom_branch_urdu",
				"fieldtype": "Data",
				"label": "Branch (Urdu)",
				"insert_after": "branch",
				"translatable": 1,
			},
		],
		"Employee": [
			{
				"fieldname": "custom_branch_urdu",
				"fieldtype": "Data",
				"label": "Branch (Urdu)",
				"insert_after": "branch",
				"fetch_from": "branch.custom_branch_urdu",
				"read_only": 1,
				"translatable": 1,
			},
		],
	}


def ensure_employee_branch_urdu_is_data():
	custom_field = "Employee-custom_branch_urdu"
	if not frappe.db.exists("Custom Field", custom_field):
		return

	frappe.db.set_value(
		"Custom Field",
		custom_field,
		{
			"fieldtype": "Data",
			"options": None,
			"fetch_from": "branch.custom_branch_urdu",
			"read_only": 1,
			"translatable": 1,
		},
		update_modified=False,
	)


def fix_branch_field_order():
	property_setter = frappe.db.exists(
		"Property Setter",
		{
			"doc_type": "Branch",
			"field_name": None,
			"property": "field_order",
		},
	)
	if not property_setter:
		return

	value = frappe.db.get_value("Property Setter", property_setter, "value")
	if not value:
		return

	try:
		field_order = json.loads(value)
	except ValueError:
		return

	changed = False
	field_order = ["custom_branch_urdu" if field == "branch_urdu" else field for field in field_order]
	if "custom_branch_urdu" not in field_order:
		insert_at = field_order.index("branch") + 1 if "branch" in field_order else 0
		field_order.insert(insert_at, "custom_branch_urdu")
		changed = True
	if "branch_urdu" in field_order:
		field_order = [field for field in field_order if field != "branch_urdu"]
		changed = True

	if changed or value != json.dumps(field_order):
		frappe.db.set_value("Property Setter", property_setter, "value", json.dumps(field_order), update_modified=False)


def backfill_employee_branch_urdu():
	frappe.db.sql(
		"""
		update `tabEmployee` employee
		inner join `tabBranch` branch
			on branch.name = employee.branch
		set employee.custom_branch_urdu = branch.custom_branch_urdu
		where ifnull(employee.branch, '') != ''
		"""
	)
