import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(get_custom_fields(), update=True)
	backfill_shift_assignment_urdu_location()


def get_custom_fields():
	return {
		"Shift Assignment": [
			{
				"fieldname": "custom_shift_location_name_urdu",
				"fieldtype": "Data",
				"label": "Shift Location Name (Urdu)",
				"insert_after": "shift_location",
				"fetch_from": "shift_location.custom_location_name_urdu",
				"read_only": 1,
				"translatable": 1,
			},
		]
	}


def backfill_shift_assignment_urdu_location():
	frappe.db.sql(
		"""
		update `tabShift Assignment` assignment
		inner join `tabShift Location` location
			on location.name = assignment.shift_location
		set assignment.custom_shift_location_name_urdu = location.custom_location_name_urdu
		where ifnull(assignment.shift_location, '') != ''
			and ifnull(location.custom_location_name_urdu, '') != ''
		"""
	)
