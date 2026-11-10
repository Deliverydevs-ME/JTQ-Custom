import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def execute():
	field_name = "Overtime Type-custom_applicable_salary_components"
	if frappe.db.get_value("Custom Field", field_name, "fieldtype") not in (None, "Table MultiSelect"):
		# Frappe intentionally prevents changing a Data field to a child table in place.
		frappe.delete_doc("Custom Field", field_name, force=True, ignore_permissions=True)

	create_custom_fields(
		{
			"Overtime Type": [
				{
					"fieldname": "custom_applicable_salary_components",
					"fieldtype": "Table MultiSelect",
					"label": "Applicable Salary Components",
					"options": "Overtime Applicable Salary Component",
					"depends_on": 'eval:doc.custom_overtime_amount_calculation == "Salary Component Based"',
					"mandatory_depends_on": 'eval:doc.custom_overtime_amount_calculation == "Salary Component Based"',
					"insert_after": "custom_overtime_amount_calculation",
				}
			]
		},
		update=True,
	)
