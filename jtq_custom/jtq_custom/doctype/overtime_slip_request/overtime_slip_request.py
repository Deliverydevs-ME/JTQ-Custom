# Copyright (c) 2026, Delivery Devs
# For license information, please see license.txt

import calendar

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate
from hrms.hr.utils import get_holiday_list_for_employee


APPROVED_STATUS = "Approved"
CANCELLED_STATUS = "Cancelled"


class OvertimeSlipRequest(Document):
	def validate(self):
		self.set_employee_details()
		validate_date_range(self.from_date, self.to_date, required=False)
		self.validate_overtime_details()
		self.total_overtime_hours = round(
			sum(flt(row.custom_overtime_hours) for row in self.overtime_details), 2
		)
		self.validate_self_approval()

	def before_submit(self):
		if not self.overtime_details:
			frappe.throw(_("Fetch at least one Attendance record with overtime before submitting."))

	def on_submit(self):
		self.sync_additional_salaries()

	def on_update(self):
		self.sync_additional_salaries()

	def on_update_after_submit(self):
		self.sync_additional_salaries()

	def on_cancel(self):
		self.cancel_linked_additional_salaries()

	def set_employee_details(self):
		if not self.employee:
			return
		employee = frappe.db.get_value(
			"Employee",
			self.employee,
			["employee_name", "company", "department", "designation"],
			as_dict=True,
		)
		if not employee:
			frappe.throw(_("Employee {0} was not found.").format(self.employee))
		self.employee_name = employee.employee_name
		self.company = employee.company
		self.department = employee.department
		self.designation = employee.designation

	def validate_overtime_details(self):
		if not self.overtime_details:
			return
		attendance = get_attendance_by_name([row.reference_document for row in self.overtime_details])
		seen = set()
		for row in self.overtime_details:
			if row.reference_document in seen:
				frappe.throw(_("Attendance {0} is included more than once.").format(row.reference_document))
			seen.add(row.reference_document)
			source = attendance.get(row.reference_document)
			if not source or source.employee != self.employee:
				frappe.throw(_("Attendance {0} is not eligible for this request.").format(row.reference_document))
			if self.from_date and self.to_date and not (
				getdate(self.from_date) <= getdate(source.attendance_date) <= getdate(self.to_date)
			):
				frappe.throw(_("Attendance {0} is outside the selected date range.").format(row.reference_document))
			if not row.overtime_type:
				frappe.throw(_("Select an Overtime Type for Attendance {0}.").format(row.reference_document))
			if not frappe.db.get_value("Overtime Type", row.overtime_type, "custom_overtime_salary_component"):
				frappe.throw(_("Set an Overtime Salary Component on Overtime Type {0}.").format(row.overtime_type))
			row.date = source.attendance_date
			row.custom_overtime_hours = flt(source.custom_overtime_hours, 2)

	def validate_self_approval(self):
		if self.status != APPROVED_STATUS or not self.has_value_changed("status"):
			return
		if not frappe.db.get_single_value("HR Settings", "custom_prevent_self_overtime_approval"):
			return
		if frappe.db.get_value("Employee", self.employee, "user_id") == frappe.session.user:
			frappe.throw(_("Self-approval for Overtime Slip Requests is not allowed."))

	def sync_additional_salaries(self):
		if self.status == APPROVED_STATUS:
			self.create_additional_salaries()
		elif self.status == CANCELLED_STATUS:
			self.cancel_linked_additional_salaries()

	def create_additional_salaries(self):
		if not self.overtime_details:
			frappe.throw(_("Fetch at least one Attendance record with overtime before approval."))
		self.validate_paid_attendance_is_not_reused()
		groups = self.get_additional_salary_groups()
		existing = self.get_linked_additional_salaries()
		if existing:
			self.link_existing_additional_salaries(existing, groups)
			return

		for group in groups.values():
			additional_salary = frappe.get_doc(
				{
					"doctype": "Additional Salary",
					"employee": self.employee,
					"company": self.company,
					"salary_component": group.salary_component,
					"payroll_date": self.from_date,
					"amount": group.amount,
					"custom_adjustment_type": "Overtime",
					"custom_overtime_hours": group.hours,
					"custom_overtime_rate": group.rate,
					"ref_doctype": self.doctype,
					"ref_docname": self.name,
				}
			).insert(ignore_permissions=True)
			additional_salary.submit()
			for row in group.rows:
				row.db_set("additional_salary", additional_salary.name, update_modified=False)

	def get_additional_salary_groups(self):
		groups = {}
		for row in self.overtime_details:
			overtime_type = frappe.get_cached_doc("Overtime Type", row.overtime_type)
			rate = get_overtime_rate(overtime_type, self.employee, row.reference_document, row.date)
			key = (overtime_type.custom_overtime_salary_component, round(rate, 6))
			group = groups.setdefault(
				key,
				frappe._dict(
					{"salary_component": key[0], "rate": rate, "hours": 0.0, "amount": 0.0, "rows": []}
				),
			)
			group.hours += flt(row.custom_overtime_hours)
			group.amount += flt(row.custom_overtime_hours) * rate
			group.rows.append(row)
		for group in groups.values():
			group.hours = round(group.hours, 2)
			group.amount = round(group.amount, 2)
		return groups

	def validate_paid_attendance_is_not_reused(self):
		paid = get_paid_attendance_names([row.reference_document for row in self.overtime_details], self.name)
		if paid:
			frappe.throw(_("Attendance {0} has already been approved for overtime payment.").format(", ".join(paid)))

	def get_linked_additional_salaries(self):
		return frappe.get_all(
			"Additional Salary",
			filters={"ref_doctype": self.doctype, "ref_docname": self.name, "docstatus": ["!=", 2]},
			fields=["name", "salary_component", "custom_overtime_rate"],
		)

	def link_existing_additional_salaries(self, existing, groups):
		existing_by_key = {
			(row.salary_component, round(flt(row.custom_overtime_rate), 6)): row.name for row in existing
		}
		if set(existing_by_key) != set(groups):
			frappe.throw(_("Linked Additional Salary records do not match the approved overtime details."))
		for key, group in groups.items():
			for row in group.rows:
				row.db_set("additional_salary", existing_by_key[key], update_modified=False)

	def cancel_linked_additional_salaries(self):
		for row in self.get_linked_additional_salaries():
			doc = frappe.get_doc("Additional Salary", row.name)
			if doc.docstatus == 1:
				doc.cancel()


@frappe.whitelist()
def get_attendance_overtime_details(employee, from_date, to_date, request_name=None):
	validate_date_range(from_date, to_date)
	if not employee:
		frappe.throw(_("Employee is required."))
	rows = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
			"custom_overtime_hours": [">", 0],
		},
		fields=["name", "attendance_date", "custom_overtime_hours"],
		order_by="attendance_date asc, name asc",
	)
	paid = get_paid_attendance_names([row.name for row in rows], request_name)
	return [
		{"reference_document": row.name, "date": row.attendance_date, "custom_overtime_hours": flt(row.custom_overtime_hours, 2)}
		for row in rows
		if row.name not in paid
	]


def get_attendance_by_name(names):
	if not names:
		return {}
	return {
		row.name: row
		for row in frappe.get_all(
			"Attendance",
			filters={"name": ["in", names], "docstatus": 1},
			fields=["name", "employee", "attendance_date", "custom_overtime_hours"],
		)
		if flt(row.custom_overtime_hours) > 0
	}


def get_paid_attendance_names(names, request_name=None):
	if not names:
		return set()
	return set(
		frappe.db.sql(
			"""
			select detail.reference_document
			from `tabOvertime Slip Request Detail` detail
			inner join `tabOvertime Slip Request` request on request.name = detail.parent
			where detail.parenttype = 'Overtime Slip Request'
				and detail.reference_document in %(names)s
				and request.name != %(request_name)s
				and request.status = %(status)s
				and request.docstatus != 2
			""",
			{"names": names, "request_name": request_name or "", "status": APPROVED_STATUS},
			pluck="reference_document",
		)
	)


def validate_date_range(from_date, to_date, required=True):
	if not from_date or not to_date:
		if required:
			frappe.throw(_("From Date and To Date are required."))
		return
	if getdate(to_date) < getdate(from_date):
		frappe.throw(_("To Date cannot be before From Date."))


def get_overtime_rate(overtime_type, employee, attendance_name, attendance_date):
	if overtime_type.custom_overtime_amount_calculation == "Fixed Hourly Rate":
		base_rate = flt(overtime_type.custom_hourly_rate)
		if base_rate <= 0:
			frappe.throw(_("Set a positive Hourly Rate on Overtime Type {0}.").format(overtime_type.name))
	else:
		base_rate = get_component_based_hourly_rate(overtime_type, employee, attendance_name, attendance_date)
	return round(base_rate * get_overtime_multiplier(overtime_type, employee, attendance_date), 6)


def get_component_based_hourly_rate(overtime_type, employee, attendance_name, attendance_date):
	components = {row.salary_component for row in overtime_type.custom_applicable_salary_components}
	if not components:
		frappe.throw(_("Select Applicable Salary Components on Overtime Type {0}.").format(overtime_type.name))
	assignment = frappe.db.sql(
		"""
		select salary_structure from `tabSalary Structure Assignment`
		where employee = %(employee)s and docstatus = 1 and from_date <= %(date)s
		order by from_date desc limit 1
		""",
		{"employee": employee, "date": attendance_date},
		pluck="salary_structure",
	)
	if not assignment:
		frappe.throw(_("No active Salary Structure Assignment was found for Employee {0}.").format(employee))
	structure = frappe.get_cached_doc("Salary Structure", assignment[0])
	monthly_amount = sum(flt(row.amount) for row in structure.earnings if row.salary_component in components)
	if monthly_amount <= 0:
		frappe.throw(_("Applicable Salary Components have no amount in Salary Structure {0}.").format(structure.name))
	shift_hours = flt(frappe.db.get_value("Attendance", attendance_name, "custom_shift_hours"))
	if shift_hours <= 0:
		frappe.throw(_("Attendance {0} does not have Shift Hours for overtime-rate calculation.").format(attendance_name))
	days = calendar.monthrange(getdate(attendance_date).year, getdate(attendance_date).month)[1]
	return monthly_amount / days / shift_hours


def get_overtime_multiplier(overtime_type, employee, attendance_date):
	standard = flt(overtime_type.custom_standard_multiplier) or 1
	holiday_list = get_holiday_list_for_employee(employee, raise_exception=False)
	if not holiday_list:
		return standard
	holiday = frappe.db.get_value(
		"Holiday", {"parent": holiday_list, "holiday_date": attendance_date}, ["weekly_off"], as_dict=True
	)
	if holiday and holiday.weekly_off and overtime_type.custom_apply_for_weekend:
		return flt(overtime_type.custom_weekend_multiplier) or standard
	if holiday and not holiday.weekly_off and overtime_type.custom_apply_for_public_holiday:
		return flt(overtime_type.custom_public_holiday_multiplier) or standard
	return standard
