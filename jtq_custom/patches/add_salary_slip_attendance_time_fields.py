from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(get_custom_fields(), update=True)


def get_custom_fields():
	return {
		"Salary Slip": [
			{
				"fieldname": "custom_attendance_details_section",
				"fieldtype": "Section Break",
				"label": "Attendance Details",
				"insert_after": "payment_days",
			},
			{
				"fieldname": "late_entry",
				"fieldtype": "Int",
				"label": "Late Entries",
				"read_only": 1,
				"allow_on_submit": 1,
				"insert_after": "custom_attendance_details_section",
			},
			{
				"fieldname": "custom_late_entry_hours",
				"fieldtype": "Float",
				"label": "Late Entry Hours",
				"precision": "2",
				"read_only": 1,
				"allow_on_submit": 1,
				"insert_after": "late_entry",
			},
			{
				"fieldname": "custom_attendance_details_column_break",
				"fieldtype": "Column Break",
				"insert_after": "custom_late_entry_hours",
			},
			{
				"fieldname": "early_exit",
				"fieldtype": "Int",
				"label": "Early Exits",
				"read_only": 1,
				"allow_on_submit": 1,
				"insert_after": "custom_attendance_details_column_break",
			},
			{
				"fieldname": "custom_early_exit_hours",
				"fieldtype": "Float",
				"label": "Early Exit Hours",
				"precision": "2",
				"read_only": 1,
				"allow_on_submit": 1,
				"insert_after": "early_exit",
			},
			{
				"fieldname": "custom_overtime_hours",
				"fieldtype": "Float",
				"label": "Overtime Hours",
				"precision": "2",
				"read_only": 1,
				"allow_on_submit": 1,
				"insert_after": "custom_early_exit_hours",
			},
		]
	}
