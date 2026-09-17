import frappe


def execute():
	make_property_setter(
		"Shift Location",
		None,
		"search_fields",
		"Data",
		"location_name,custom_location_name_urdu",
	)


def make_property_setter(doc_type, field_name, property_name, property_type, value):
	filters = {
		"doc_type": doc_type,
		"field_name": field_name,
		"property": property_name,
	}
	if frappe.db.exists("Property Setter", filters):
		property_setter = frappe.get_doc("Property Setter", filters)
		if property_setter.value != value:
			property_setter.value = value
			property_setter.save(ignore_permissions=True)
		return

	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocType" if not field_name else "DocField",
			"doc_type": doc_type,
			"field_name": field_name,
			"property": property_name,
			"property_type": property_type,
			"value": value,
		}
	).insert(ignore_permissions=True)
