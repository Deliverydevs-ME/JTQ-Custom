import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, flt, getdate


BULK_SALARY_ASSIGNMENT_EVENT = "jtq_bulk_salary_assignments_completed"
BULK_SALARY_ASSIGNMENT_SYNC_LIMIT = 30


def sync_salary_structure_title(doc, method=None):
	if not doc.get("custom_salary_structure_title"):
		doc.custom_salary_structure_title = doc.name


def sync_additional_salary_controls(doc, method=None):
	if doc.get("custom_adjustment_type") == "Overtime":
		hours = flt(doc.get("custom_overtime_hours"))
		rate = flt(doc.get("custom_overtime_rate"))
		if hours and rate:
			doc.amount = hours * rate

	if doc.get("custom_paused"):
		doc.disabled = 1
	elif doc.get("custom_paused") == 0:
		doc.disabled = 0

	total_amount = flt(doc.get("custom_total_adjustment_amount"))
	if not total_amount:
		total_amount = get_default_total_amount(doc)

	doc.custom_total_adjustment_amount = total_amount
	doc.custom_paid_or_deducted_amount = flt(doc.get("custom_paid_or_deducted_amount"))
	doc.custom_remaining_balance = max(total_amount - doc.custom_paid_or_deducted_amount, 0)


def sync_advance_recovery_from_salary_slip(doc, method=None):
	additional_salaries = {
		row.additional_salary
		for row in doc.get("deductions", [])
		if row.additional_salary
	}

	for additional_salary in additional_salaries:
		sync_advance_recovery_balance(additional_salary)


def sync_advance_recovery_balance(additional_salary):
	import frappe

	doc = frappe.get_doc("Additional Salary", additional_salary)
	if doc.get("custom_adjustment_type") != "Advance Recovery":
		return

	recovered_amount = get_recovered_amount(additional_salary)
	total_amount = flt(doc.get("custom_total_adjustment_amount")) or get_default_total_amount(doc)
	doc.db_set(
		{
			"custom_total_adjustment_amount": total_amount,
			"custom_paid_or_deducted_amount": recovered_amount,
			"custom_remaining_balance": max(total_amount - recovered_amount, 0),
			"disabled": 1 if total_amount and recovered_amount >= total_amount else doc.disabled,
		},
		update_modified=False,
	)


def get_recovered_amount(additional_salary):
	import frappe

	return flt(
		frappe.db.sql(
			"""
			select sum(ded.amount)
			from `tabSalary Detail` ded
			inner join `tabSalary Slip` sal on sal.name = ded.parent
			where ded.parenttype = 'Salary Slip'
				and ded.parentfield = 'deductions'
				and ded.additional_salary = %(additional_salary)s
				and sal.docstatus = 1
			""",
			{"additional_salary": additional_salary},
		)[0][0]
	)


def get_default_total_amount(doc):
	if doc.get("is_recurring") and doc.get("from_date") and doc.get("to_date"):
		return flt(doc.amount) * get_month_count(doc.from_date, doc.to_date)
	return flt(doc.amount)


def get_month_count(from_date, to_date):
	from frappe.utils import getdate

	start_date = getdate(from_date)
	end_date = getdate(to_date)
	if end_date < start_date:
		return 0

	return ((end_date.year - start_date.year) * 12) + (end_date.month - start_date.month) + 1


def is_earning_eligible(date_of_joining, salary_slip_start_date, eligibility_after_days):
	eligibility_after_days = max(cint(eligibility_after_days), 0)
	if not eligibility_after_days:
		return True
	if not (date_of_joining and salary_slip_start_date):
		return False

	eligibility_date = getdate(add_days(date_of_joining, eligibility_after_days))
	return getdate(salary_slip_start_date) >= eligibility_date


def populate_salary_structure_components(doc, method=None):
	if not doc.get("earnings"):
		add_salary_component_rows(doc, "earnings", "Earning")
	if not doc.get("deductions"):
		add_salary_component_rows(doc, "deductions", "Deduction")


def add_salary_component_rows(doc, table_field, component_type):
	for component in get_salary_structure_components(component_type):
		row = doc.append(table_field, {})
		set_salary_detail_from_component(row, component)


@frappe.whitelist()
def get_salary_structure_components(component_type=None):
	filters = {"disabled": 0}
	if component_type:
		filters["type"] = component_type

	return frappe.get_all(
		"Salary Component",
		filters=filters,
		fields=[
			"name",
			"salary_component_abbr",
			"type",
			"depends_on_payment_days",
			"is_tax_applicable",
			"is_flexible_benefit",
			"variable_based_on_taxable_salary",
			"statistical_component",
			"exempted_from_income_tax",
			"do_not_include_in_total",
			"do_not_include_in_accounts",
			"deduct_full_tax_on_selected_payroll_date",
		],
		order_by="type asc, name asc",
	)


def set_salary_detail_from_component(row, component):
	row.salary_component = component.name
	row.abbr = component.salary_component_abbr
	row.amount = 0
	row.default_amount = 0
	row.additional_amount = 0
	row.amount_based_on_formula = 0
	row.formula = ""
	row.condition = ""
	row.depends_on_payment_days = component.depends_on_payment_days
	row.is_tax_applicable = component.is_tax_applicable
	row.is_flexible_benefit = component.is_flexible_benefit
	row.variable_based_on_taxable_salary = component.variable_based_on_taxable_salary
	row.statistical_component = component.statistical_component
	row.exempted_from_income_tax = component.exempted_from_income_tax
	row.do_not_include_in_total = component.do_not_include_in_total
	row.do_not_include_in_accounts = component.do_not_include_in_accounts
	row.deduct_full_tax_on_selected_payroll_date = component.deduct_full_tax_on_selected_payroll_date
	row.custom_jtq_auto_populated = 1
	row.custom_jtq_amount_changed = 0


@frappe.whitelist()
def get_employee_salary_structure_components(
	salary_structure,
	employee=None,
	assignment_from_date=None,
	date_of_joining=None,
):
	if not salary_structure:
		return {}

	salary_structure_doc = frappe.get_doc("Salary Structure", salary_structure)
	validate_salary_structure_for_employee_assignment(salary_structure_doc)
	earnings = get_employee_component_rows(salary_structure_doc.get("earnings"))

	return {
		"salary_structure": salary_structure_doc.name,
		"company": salary_structure_doc.company,
		"currency": salary_structure_doc.currency,
		"earnings": earnings,
		"deductions": get_employee_component_rows(salary_structure_doc.get("deductions")),
	}


def validate_salary_structure_for_employee_assignment(salary_structure_doc):
	if salary_structure_doc.docstatus != 1:
		frappe.throw(
			_("Salary Structure {0} must be submitted before assignment.").format(
				frappe.bold(salary_structure_doc.name)
			)
		)
	if salary_structure_doc.get("is_active") == "No":
		frappe.throw(
			_("Salary Structure {0} is inactive.").format(frappe.bold(salary_structure_doc.name))
		)


def get_employee_component_rows(rows):
	return [get_employee_component_row(row) for row in rows]


def get_employee_component_row(row):
	return {
		"salary_component": row.salary_component,
		"abbr": row.abbr,
		"amount": flt(row.amount),
		"year_to_date": flt(row.get("year_to_date")),
		"additional_salary": row.get("additional_salary"),
		"is_recurring_additional_salary": row.get("is_recurring_additional_salary"),
		"depends_on_payment_days": row.depends_on_payment_days,
		"is_tax_applicable": row.is_tax_applicable,
		"condition": row.condition,
		"formula": row.formula,
		"amount_based_on_formula": row.amount_based_on_formula,
		"statistical_component": row.statistical_component,
		"is_flexible_benefit": row.is_flexible_benefit,
		"variable_based_on_taxable_salary": row.variable_based_on_taxable_salary,
		"exempted_from_income_tax": row.exempted_from_income_tax,
		"do_not_include_in_total": row.do_not_include_in_total,
		"do_not_include_in_accounts": row.do_not_include_in_accounts,
		"deduct_full_tax_on_selected_payroll_date": row.deduct_full_tax_on_selected_payroll_date,
		"default_amount": flt(row.get("default_amount")) or flt(row.amount),
		"additional_amount": flt(row.get("additional_amount")),
		"tax_on_flexible_benefit": flt(row.get("tax_on_flexible_benefit")),
		"tax_on_additional_salary": flt(row.get("tax_on_additional_salary")),
	}


@frappe.whitelist()
def create_salary_assignment_from_employee(employee):
	if not employee:
		frappe.throw(_("Employee is required."))

	employee_doc = frappe.get_doc("Employee", employee)
	validate_salary_assignment_permissions(employee_doc)
	assignment = _create_salary_assignment_from_employee(employee_doc)

	frappe.msgprint(
		_("Salary Structure Assignment {0} created for Employee {1}.").format(
			frappe.bold(assignment.name), frappe.bold(employee_doc.name)
		),
		indicator="green",
	)

	return get_salary_assignment_result(employee_doc, assignment)


def _create_salary_assignment_from_employee(employee_doc):
	salary_structure = employee_doc.get("custom_salary_structure")
	from_date = employee_doc.get("custom_salary_assignment_from_date")

	if not salary_structure:
		frappe.throw(_("Please select Salary Structure in the Salary tab."))
	if not from_date:
		frappe.throw(_("Please select Assignment From Date in the Salary tab."))

	template = frappe.get_doc("Salary Structure", salary_structure)
	validate_salary_structure_for_employee_assignment(template)

	if employee_doc.company != template.company:
		frappe.throw(
			_("Selected Salary Structure belongs to {0}, but Employee belongs to {1}.").format(
				frappe.bold(template.company), frappe.bold(employee_doc.company)
			)
		)
	validate_employee_income_tax_slab(employee_doc, template)

	cancel_latest_salary_structure_assignment(employee_doc.name)

	assignment = create_employee_salary_structure_assignment(
		employee_doc,
		template,
		getdate(from_date),
	)

	employee_doc.db_set(
		"custom_current_salary_structure_assignment",
		assignment.name,
		update_modified=False,
	)
	return assignment


def get_salary_assignment_result(employee_doc, assignment):
	return {
		"employee": employee_doc.name,
		"employee_name": employee_doc.employee_name,
		"salary_structure": assignment.salary_structure,
		"salary_structure_assignment": assignment.name,
	}


def validate_salary_assignment_permissions(employee_doc):
	employee_doc.check_permission("write")
	for permission_type in ("create", "submit"):
		if not frappe.has_permission("Salary Structure Assignment", ptype=permission_type):
			frappe.throw(
				_("You do not have permission to {0} Salary Structure Assignments.").format(
					permission_type
				),
				frappe.PermissionError,
			)


@frappe.whitelist()
def bulk_create_salary_assignments_from_employees(employees):
	employee_names = normalize_employee_names(employees)
	if not employee_names:
		frappe.throw(_("Please select at least one Employee."))

	validate_bulk_salary_assignment_permissions()
	requested_by = frappe.session.user
	if len(employee_names) > BULK_SALARY_ASSIGNMENT_SYNC_LIMIT:
		frappe.enqueue(
			"jtq_custom.payroll.process_bulk_salary_assignments",
			queue="long",
			timeout=3000,
			enqueue_after_commit=True,
			employee_names=employee_names,
			requested_by=requested_by,
			publish_result=True,
		)
		return {"queued": True, "total": len(employee_names)}

	return process_bulk_salary_assignments(employee_names, requested_by=requested_by)


def normalize_employee_names(employees):
	if isinstance(employees, str):
		employees = frappe.parse_json(employees)
	if not isinstance(employees, (list, tuple)):
		frappe.throw(_("Employees must be provided as a list."))

	employee_names = []
	for employee in employees:
		if isinstance(employee, dict):
			employee = employee.get("name") or employee.get("employee")
		employee = cstr(employee).strip()
		if employee and employee not in employee_names:
			employee_names.append(employee)
	return employee_names


def validate_bulk_salary_assignment_permissions():
	for permission_type in ("create", "submit"):
		if not frappe.has_permission("Salary Structure Assignment", ptype=permission_type):
			frappe.throw(
				_("You do not have permission to {0} Salary Structure Assignments.").format(
					permission_type
				),
				frappe.PermissionError,
			)


def process_bulk_salary_assignments(employee_names, requested_by=None, publish_result=False):
	result = {"queued": False, "success": [], "failed": [], "total": len(employee_names)}
	total = len(employee_names)

	for index, employee in enumerate(employee_names, start=1):
		savepoint = f"jtq_salary_assignment_{index}"
		frappe.db.savepoint(savepoint)
		try:
			employee_doc = frappe.get_doc("Employee", employee)
			validate_salary_assignment_permissions(employee_doc)
			assignment = _create_salary_assignment_from_employee(employee_doc)
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			result["failed"].append({"employee": employee, "message": cstr(exc)})
			frappe.clear_messages()
		else:
			result["success"].append(get_salary_assignment_result(employee_doc, assignment))

		frappe.publish_progress(
			index * 100 / total,
			title=_("Creating Salary Structure Assignments"),
		)

	if publish_result:
		frappe.publish_realtime(
			BULK_SALARY_ASSIGNMENT_EVENT,
			message=result,
			user=requested_by,
			after_commit=True,
		)

	return result


def validate_employee_salary_components(employee_doc):
	if not employee_doc.get("custom_employee_earnings"):
		frappe.throw(_("Please fetch or add Earning components before creating Salary Assignment."))

	for table_field, label in (
		("custom_employee_earnings", _("Earnings")),
		("custom_employee_deductions", _("Deductions")),
	):
		seen_components = set()
		for row in employee_doc.get(table_field):
			if not row.salary_component:
				frappe.throw(_("{0} row {1}: Salary Component is required.").format(label, row.idx))
			if row.salary_component in seen_components:
				frappe.throw(
					_("{0} row {1}: Duplicate Salary Component {2}.").format(
						label, row.idx, frappe.bold(row.salary_component)
					)
				)
			seen_components.add(row.salary_component)
			if flt(row.amount) < 0:
				frappe.throw(_("{0} row {1}: Amount cannot be negative.").format(label, row.idx))


def validate_employee_income_tax_slab(employee_doc, salary_structure):
	income_tax_slab = employee_doc.get("custom_income_tax_slab")
	if not income_tax_slab:
		return

	slab = frappe.db.get_value(
		"Income Tax Slab",
		income_tax_slab,
		["docstatus", "disabled", "company", "currency"],
		as_dict=True,
	)
	if not slab:
		frappe.throw(_("Income Tax Slab {0} does not exist.").format(frappe.bold(income_tax_slab)))
	if slab.docstatus != 1:
		frappe.throw(_("Income Tax Slab {0} must be submitted.").format(frappe.bold(income_tax_slab)))
	if slab.disabled:
		frappe.throw(_("Income Tax Slab {0} is disabled.").format(frappe.bold(income_tax_slab)))
	if slab.company and slab.company != employee_doc.company:
		frappe.throw(
			_("Income Tax Slab {0} belongs to {1}, but Employee belongs to {2}.").format(
				frappe.bold(income_tax_slab), frappe.bold(slab.company), frappe.bold(employee_doc.company)
			)
		)
	if slab.currency and slab.currency != salary_structure.currency:
		frappe.throw(
			_("Income Tax Slab {0} currency is {1}, but Salary Structure currency is {2}.").format(
				frappe.bold(income_tax_slab), frappe.bold(slab.currency), frappe.bold(salary_structure.currency)
			)
		)


def cancel_latest_salary_structure_assignment(employee):
	latest_assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{
			"employee": employee,
			"docstatus": 1,
		},
		"name",
		order_by="from_date desc, creation desc",
	)
	if not latest_assignment:
		return

	assignment = frappe.get_doc("Salary Structure Assignment", latest_assignment)
	assignment.flags.ignore_permissions = True
	assignment.flags.skip_employee_salary_tab_clear = True
	assignment.cancel()


def unlink_salary_structure_on_assignment_cancel(doc, method=None):
	unlink_cancelled_salary_structure_assignment(
		doc.name,
		clear_salary_tab=not doc.flags.get("skip_employee_salary_tab_clear"),
	)


def unlink_cancelled_salary_structure_assignment(assignment, clear_salary_tab=True):
	assignment_data = frappe.db.get_value(
		"Salary Structure Assignment",
		assignment,
		["employee", "salary_structure", "income_tax_slab", "docstatus"],
		as_dict=True,
	)
	if not assignment_data or assignment_data.docstatus != 2:
		return

	employee_fields = frappe.db.get_value(
		"Employee",
		assignment_data.employee,
		[
			"custom_salary_structure",
			"custom_salary_assignment_from_date",
			"custom_current_salary_structure_assignment",
			"custom_income_tax_slab",
		],
		as_dict=True,
	)
	if employee_fields:
		updates = {}
		latest_active_assignment = frappe.db.get_value(
			"Salary Structure Assignment",
			{"employee": assignment_data.employee, "docstatus": 1},
			"name",
			order_by="from_date desc, creation desc",
		)
		is_current_assignment = employee_fields.custom_current_salary_structure_assignment == assignment
		is_stale_current_assignment = (
			assignment_data.salary_structure
			and not employee_fields.custom_current_salary_structure_assignment
			and not latest_active_assignment
			and employee_fields.custom_salary_structure == assignment_data.salary_structure
		)
		should_clear_salary_tab = clear_salary_tab and (
			is_current_assignment or is_stale_current_assignment
		)

		if is_current_assignment:
			updates["custom_current_salary_structure_assignment"] = None
		if should_clear_salary_tab:
			updates["custom_salary_structure"] = None
			updates["custom_salary_assignment_from_date"] = None
			updates["custom_income_tax_slab"] = None

		if updates:
			frappe.db.set_value(
				"Employee",
				assignment_data.employee,
				updates,
				update_modified=False,
			)
		if should_clear_salary_tab:
			clear_employee_salary_component_rows(assignment_data.employee)

	assignment_updates = {}
	if assignment_data.salary_structure:
		assignment_updates["salary_structure"] = None
	if assignment_data.income_tax_slab:
		assignment_updates["income_tax_slab"] = None
	if assignment_updates:
		frappe.db.set_value(
			"Salary Structure Assignment",
			assignment,
			assignment_updates,
			update_modified=False,
		)


def clear_employee_salary_component_rows(employee):
	for parentfield in ("custom_employee_earnings", "custom_employee_deductions"):
		frappe.db.delete(
			"Employee Salary Component Detail",
			{
				"parent": employee,
				"parenttype": "Employee",
				"parentfield": parentfield,
			},
		)


def unlink_cancelled_employee_salary_structure_assignments():
	for assignment in frappe.get_all(
		"Salary Structure Assignment",
		filters={
			"docstatus": 2,
			"salary_structure": ["is", "set"],
		},
		pluck="name",
	):
		unlink_cancelled_salary_structure_assignment(assignment)

	frappe.db.commit()


def create_employee_salary_structure_assignment(employee_doc, salary_structure, from_date):
	assignment = frappe.new_doc("Salary Structure Assignment")
	assignment.employee = employee_doc.name
	assignment.salary_structure = salary_structure.name
	assignment.company = employee_doc.company
	assignment.currency = salary_structure.currency
	assignment.from_date = from_date
	assignment.income_tax_slab = employee_doc.get("custom_income_tax_slab")

	assignment.flags.ignore_permissions = True
	assignment.insert()
	assignment.submit()
	return assignment
