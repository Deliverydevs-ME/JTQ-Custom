from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Overtime Type": [
				{
					"fieldname": "custom_public_holiday_multiplier",
					"fieldtype": "Float",
					"label": "Public Holiday Multiplier",
					"default": "1",
					"description": "Multiplier applied to overtime worked on a public holiday.",
					"insert_after": "custom_section_break_lbmsp",
				},
				{
					"fieldname": "custom_weekend_multiplier",
					"fieldtype": "Float",
					"label": "Weekend Multiplier",
					"default": "1",
					"description": "Multiplier applied to overtime worked on a weekend.",
					"insert_after": "custom_public_holiday_multiplier",
				},
			]
		},
		update=True,
	)
