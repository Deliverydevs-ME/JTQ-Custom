import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from hrms.payroll.doctype.salary_slip.salary_slip import (
	SalarySlip,
	get_salary_component_data,
)

from jtq_custom.payroll import get_month_count, is_earning_eligible


class JTQSalarySlip(SalarySlip):
	def validate(self):
		super().validate()
		self.set_attendance_time_details()

	def set_attendance_time_details(self):
		"""Copy attendance time totals for the Salary Slip period."""
		fields = {
			"late_entry": 0,
			"custom_late_entry_hours": 0,
			"early_exit": 0,
			"custom_early_exit_hours": 0,
			"custom_overtime_hours": 0,
		}

		if self.employee and self.start_date and self.end_date:
			attendance_details = frappe.db.sql(
				"""
				select
					coalesce(sum(late_entry), 0) as late_entry,
					coalesce(sum(custom_late_entry_hours), 0) as custom_late_entry_hours,
					coalesce(sum(early_exit), 0) as early_exit,
					coalesce(sum(custom_early_exit_hours), 0) as custom_early_exit_hours,
					coalesce(sum(custom_overtime_hours), 0) as custom_overtime_hours
				from `tabAttendance`
				where employee = %(employee)s
					and attendance_date between %(start_date)s and %(end_date)s
					and docstatus = 1
				""",
				{
					"employee": self.employee,
					"start_date": self.start_date,
					"end_date": self.end_date,
				},
				as_dict=True,
			)
			if attendance_details:
				fields.update(attendance_details[0])

		self.late_entry = cint(fields["late_entry"])
		self.custom_late_entry_hours = flt(fields["custom_late_entry_hours"])
		self.early_exit = cint(fields["early_exit"])
		self.custom_early_exit_hours = flt(fields["custom_early_exit_hours"])
		self.custom_overtime_hours = flt(fields["custom_overtime_hours"])

	def set_salary_structure_doc(self):
		super().set_salary_structure_doc()
		self._salary_structure_doc = add_employee_components_to_salary_structure(
			self._salary_structure_doc,
			self.employee,
		)

	def check_sal_struct(self):
		assignment = get_assigned_salary_structure(
			self.employee,
			start_date=self.start_date,
			end_date=self.end_date,
			joining_date=self.get("joining_date"),
			payroll_frequency=self.get("payroll_frequency"),
			salary_slip_based_on_timesheet=self.get("salary_slip_based_on_timesheet"),
		)
		if assignment:
			self.salary_structure = assignment.salary_structure
			return self.salary_structure

		self.salary_structure = None
		frappe.msgprint(
			_("No active or default Salary Structure found for employee {0} for the given dates").format(
				self.employee
			),
			title=_("Salary Structure Missing"),
		)

	def add_structure_component(self, struct_row, component_type):
		if (
			component_type == "earnings"
			and not self.is_structure_earning_eligible(struct_row.salary_component)
		):
			self.data[struct_row.abbr] = 0
			self.default_data[struct_row.abbr] = 0
			return

		employee_component = self.get_employee_component_row(
			component_type,
			struct_row.salary_component,
		)
		if not employee_component:
			super().add_structure_component(struct_row, component_type)
			return

		original_values = stash_salary_structure_row_values(struct_row)
		apply_employee_component_values(struct_row, employee_component)
		try:
			super().add_structure_component(struct_row, component_type)
		finally:
			restore_salary_structure_row_values(struct_row, original_values)

	def add_additional_salary_components(self, component_type):
		super().add_additional_salary_components(component_type)

		if component_type == "deductions":
			self.apply_advance_recovery_controls()

	def is_structure_earning_eligible(self, salary_component):
		eligibility_after_days = self.get_component_eligibility_after_days(salary_component)
		joining_date = self.get("joining_date") or frappe.db.get_value(
			"Employee", self.employee, "date_of_joining"
		)
		return is_earning_eligible(joining_date, self.start_date, eligibility_after_days)

	def get_component_eligibility_after_days(self, salary_component):
		if not hasattr(self, "_jtq_component_eligibility_days"):
			self._jtq_component_eligibility_days = {}

		if salary_component not in self._jtq_component_eligibility_days:
			self._jtq_component_eligibility_days[salary_component] = cint(
				frappe.get_cached_value(
					"Salary Component",
					salary_component,
					"custom_eligibility_after_days",
				)
			)

		return self._jtq_component_eligibility_days[salary_component]

	def apply_advance_recovery_controls(self):
		for additional_salary in get_active_advance_recoveries(
			self.employee, self.start_date, self.end_date
		):
			principal_amount = get_principal_amount(additional_salary)
			total_recovered = get_total_recovered_amount(additional_salary.name, exclude_salary_slip=self.name)
			pending_amount = max(principal_amount - total_recovered, 0)

			if not pending_amount:
				remove_additional_salary_row(self, additional_salary.name)
				continue

			deduction_amount = min(flt(additional_salary.amount), pending_amount)
			if not deduction_amount and additional_salary.get("custom_paused"):
				remove_additional_salary_row(self, additional_salary.name)
				continue

			component_data = get_salary_component_data(additional_salary.salary_component)
			self.update_component_row(
				component_data,
				deduction_amount,
				"deductions",
				frappe._dict(
					{
						"name": additional_salary.name,
						"overwrite": additional_salary.overwrite_salary_structure_amount,
						"is_recurring": additional_salary.is_recurring,
						"deduct_full_tax_on_selected_payroll_date": additional_salary.deduct_full_tax_on_selected_payroll_date,
					}
				),
				is_recurring=additional_salary.is_recurring,
			)

	def get_employee_component_row(self, component_type, salary_component):
		if not self.employee or not salary_component:
			return None

		if not hasattr(self, "_jtq_employee_component_map"):
			self._jtq_employee_component_map = {
				"earnings": get_employee_salary_component_map(
					self.employee,
					"custom_employee_earnings",
				),
				"deductions": get_employee_salary_component_map(
					self.employee,
					"custom_employee_deductions",
				),
			}

		return self._jtq_employee_component_map.get(component_type, {}).get(salary_component)


@frappe.whitelist()
def get_assigned_salary_structure(
	employee,
	start_date=None,
	end_date=None,
	joining_date=None,
	payroll_frequency=None,
	salary_slip_based_on_timesheet=0,
):
	if not employee:
		return None

	date_conditions = []
	values = {"employee": employee}
	for fieldname, value in {
		"start_date": start_date,
		"end_date": end_date,
		"joining_date": joining_date,
	}.items():
		if value:
			date_conditions.append(f"ssa.from_date <= %({fieldname})s")
			values[fieldname] = getdate(value)

	if not date_conditions:
		return None

	conditions = [
		"ssa.docstatus = 1",
		"ss.docstatus = 1",
		"ss.is_active = 'Yes'",
		"ssa.employee = %(employee)s",
		f"({' or '.join(date_conditions)})",
	]
	if not flt(salary_slip_based_on_timesheet) and payroll_frequency:
		conditions.append("ss.payroll_frequency = %(payroll_frequency)s")
		values["payroll_frequency"] = payroll_frequency

	assignments = frappe.db.sql(
		"""
		select
			ssa.name,
			ssa.employee,
			ssa.salary_structure,
			ssa.from_date,
			ssa.company,
			ssa.currency,
			ssa.income_tax_slab
		from `tabSalary Structure Assignment` ssa
		inner join `tabSalary Structure` ss on ss.name = ssa.salary_structure
		where {conditions}
		order by ssa.from_date desc, ssa.creation desc
		limit 1
		""".format(conditions=" and ".join(conditions)),
		values,
		as_dict=True,
	)
	return assignments[0] if assignments else None


def get_employee_salary_component_map(employee, parentfield):
	rows = frappe.get_all(
		"Employee Salary Component Detail",
		filters={
			"parent": employee,
			"parenttype": "Employee",
			"parentfield": parentfield,
		},
		fields=[
			"salary_component",
			"abbr",
			"amount",
			"default_amount",
			"additional_amount",
			"additional_salary",
			"is_recurring_additional_salary",
			"condition",
			"formula",
			"amount_based_on_formula",
			"depends_on_payment_days",
			"is_tax_applicable",
			"is_flexible_benefit",
			"variable_based_on_taxable_salary",
			"statistical_component",
			"exempted_from_income_tax",
			"do_not_include_in_total",
			"do_not_include_in_accounts",
			"deduct_full_tax_on_selected_payroll_date",
			"tax_on_flexible_benefit",
			"tax_on_additional_salary",
		],
	)
	return {row.salary_component: row for row in rows}


def add_employee_components_to_salary_structure(salary_structure, employee):
	"""Add employee-specific components that are not part of the selected template."""
	if not employee:
		return salary_structure

	salary_structure = frappe.copy_doc(salary_structure)
	for parentfield, employee_parentfield in (
		("earnings", "custom_employee_earnings"),
		("deductions", "custom_employee_deductions"),
	):
		structure_components = {
			row.salary_component for row in salary_structure.get(parentfield, [])
		}
		for employee_component in get_employee_salary_component_map(employee, employee_parentfield).values():
			if employee_component.salary_component in structure_components:
				continue

			salary_structure.append(
				parentfield,
				{
					"salary_component": employee_component.salary_component,
					**{
						fieldname: employee_component.get(fieldname)
						for fieldname in get_salary_detail_override_fields()
					},
				},
			)

	return salary_structure


def stash_salary_structure_row_values(row):
	return {
		fieldname: row.get(fieldname)
		for fieldname in get_salary_detail_override_fields()
	}


def restore_salary_structure_row_values(row, values):
	for fieldname, value in values.items():
		row.set(fieldname, value)


def apply_employee_component_values(struct_row, employee_component):
	for fieldname in get_salary_detail_override_fields():
		if fieldname == "amount":
			struct_row.amount = flt(employee_component.get("amount"))
			continue
		if employee_component.get(fieldname) is not None:
			struct_row.set(fieldname, employee_component.get(fieldname))


def get_salary_detail_override_fields():
	return [
		"abbr",
		"amount",
		"default_amount",
		"additional_amount",
		"additional_salary",
		"is_recurring_additional_salary",
		"condition",
		"formula",
		"amount_based_on_formula",
		"depends_on_payment_days",
		"is_tax_applicable",
		"is_flexible_benefit",
		"variable_based_on_taxable_salary",
		"statistical_component",
		"exempted_from_income_tax",
		"do_not_include_in_total",
		"do_not_include_in_accounts",
		"deduct_full_tax_on_selected_payroll_date",
		"tax_on_flexible_benefit",
		"tax_on_additional_salary",
	]


def get_active_advance_recoveries(employee, start_date, end_date):
	return frappe.get_all(
		"Additional Salary",
		filters={
			"employee": employee,
			"docstatus": 1,
			"type": "Deduction",
			"is_recurring": 1,
			"disabled": 0,
			"custom_adjustment_type": "Advance Recovery",
			"from_date": ["<=", end_date],
		},
		fields=[
			"name",
			"employee",
			"salary_component",
			"amount",
			"is_recurring",
			"from_date",
			"to_date",
			"overwrite_salary_structure_amount",
			"deduct_full_tax_on_selected_payroll_date",
			"custom_total_adjustment_amount",
			"custom_paused",
		],
	)


def get_principal_amount(additional_salary):
	return flt(additional_salary.custom_total_adjustment_amount) or (
		flt(additional_salary.amount)
		* get_month_count(additional_salary.from_date, additional_salary.to_date)
	)


def get_total_recovered_amount(additional_salary, exclude_salary_slip=None):
	conditions = [
		"ded.parenttype = 'Salary Slip'",
		"ded.parentfield = 'deductions'",
		"ded.additional_salary = %(additional_salary)s",
		"sal.docstatus = 1",
	]
	values = {"additional_salary": additional_salary}
	if exclude_salary_slip:
		conditions.append("ded.parent != %(exclude_salary_slip)s")
		values["exclude_salary_slip"] = exclude_salary_slip

	return flt(
		frappe.db.sql(
			"""
			select sum(ded.amount)
			from `tabSalary Detail` ded
			inner join `tabSalary Slip` sal on sal.name = ded.parent
			where {conditions}
			""".format(conditions=" and ".join(conditions)),
			values,
		)
		[0][0]
	)


def remove_additional_salary_row(salary_slip, additional_salary):
	rows = [
		row
		for row in salary_slip.get("deductions")
		if row.additional_salary != additional_salary
	]
	salary_slip.set("deductions", rows)
