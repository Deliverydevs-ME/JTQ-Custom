# Copyright (c) 2026, Delivery Devs
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate, now_datetime, time_diff_in_hours


APPROVER_ROLES = {"System Manager", "HR Manager"}


class OvertimeSlipRequest(Document):
	def validate(self):
		self.set_employee_details()
		self.validate_dates_and_times()
		self.set_total_overtime_hours()
		self.validate_approver()

	def before_submit(self):
		if self.status == "Rejected":
			frappe.throw(frappe._("Rejected Overtime Slip Request cannot be submitted."))

		if self.status != "Approved":
			if not self.can_current_user_approve():
				frappe.throw(frappe._("Only the Overtime Request Approver can approve this request."))
			self.status = "Approved"
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()

	def on_cancel(self):
		self.db_set("status", "Cancelled", update_modified=False)

	def set_employee_details(self):
		if not self.employee:
			return

		employee = frappe.db.get_value(
			"Employee",
			self.employee,
			[
				"employee_name",
				"company",
				"department",
				"designation",
				"custom_overtime_request_approver",
			],
			as_dict=True,
		)
		if not employee:
			frappe.throw(frappe._("Employee {0} was not found.").format(self.employee))

		self.employee_name = employee.employee_name
		self.company = employee.company
		self.department = employee.department
		self.designation = employee.designation
		self.overtime_request_approver = employee.custom_overtime_request_approver

	def validate_dates_and_times(self):
		if not (self.from_date and self.to_date and self.from_time and self.to_time):
			return

		if getdate(self.to_date) < getdate(self.from_date):
			frappe.throw(frappe._("To Date cannot be before From Date."))

		start = get_datetime(f"{self.from_date} {self.from_time}")
		end = get_datetime(f"{self.to_date} {self.to_time}")
		if end <= start:
			frappe.throw(frappe._("To Time must be after From Time."))

	def set_total_overtime_hours(self):
		if not (self.from_date and self.to_date and self.from_time and self.to_time):
			self.total_overtime_hours = 0
			return

		start = get_datetime(f"{self.from_date} {self.from_time}")
		end = get_datetime(f"{self.to_date} {self.to_time}")
		self.total_overtime_hours = round(time_diff_in_hours(end, start), 2)

	def validate_approver(self):
		if not self.overtime_request_approver:
			frappe.throw(
				frappe._("Set Overtime Request Approver on Employee {0} before creating request.").format(
					self.employee
				)
			)

		if not frappe.db.get_value("User", self.overtime_request_approver, "enabled"):
			frappe.throw(frappe._("Overtime Request Approver must be an enabled User."))

	def can_current_user_approve(self):
		return can_user_approve(self.overtime_request_approver)

	@frappe.whitelist()
	def approve(self):
		if self.docstatus != 0:
			frappe.throw(frappe._("Only draft Overtime Slip Requests can be approved."))
		if not self.can_current_user_approve():
			frappe.throw(frappe._("Only the Overtime Request Approver can approve this request."))

		self.status = "Approved"
		self.approved_by = frappe.session.user
		self.approved_on = now_datetime()
		self.rejection_reason = None
		self.save()
		return self.name

	@frappe.whitelist()
	def reject(self, rejection_reason=None):
		if self.docstatus != 0:
			frappe.throw(frappe._("Only draft Overtime Slip Requests can be rejected."))
		if not self.can_current_user_approve():
			frappe.throw(frappe._("Only the Overtime Request Approver can reject this request."))

		self.status = "Rejected"
		self.rejection_reason = rejection_reason or self.rejection_reason
		if not self.rejection_reason:
			frappe.throw(frappe._("Rejection Reason is required."))
		self.save()
		return self.name


def can_user_approve(approver):
	if frappe.session.user == approver:
		return True
	return bool(APPROVER_ROLES.intersection(set(frappe.get_roles())))
