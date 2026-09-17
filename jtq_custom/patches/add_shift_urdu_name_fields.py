from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(get_custom_fields(), update=True)


def get_custom_fields():
	return {
		"Shift Location": [
			{
				"fieldname": "custom_location_name_urdu",
				"fieldtype": "Data",
				"label": "Location Name (Urdu)",
				"insert_after": "location_name",
				"translatable": 1,
			},
		],
		"Shift Type": [
			{
				"fieldname": "custom_name_urdu",
				"fieldtype": "Data",
				"label": "Name (Urdu)",
				"insert_after": "end_time",
				"translatable": 1,
			},
		],
	}
