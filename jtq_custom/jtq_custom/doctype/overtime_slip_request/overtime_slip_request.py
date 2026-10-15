# Copyright (c) 2026, Delivery Devs
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate, now_datetime, time_diff_in_hours


APPROVER_ROLES = {"System Manager", "HR Manager"}
STATUS_MANAGER_ROLE = "Overtime Slip Request Status Manager"


class OvertimeSlipRequest(Document):
	def validate(self):
		self.set_employee_details()
		self.validate_dates_and_times()
		self.set_total_overtime_hours()
		self.validate_approver()
		self.validate_status_change_permission()

	def before_submit(self):
		if self.status == "Rejected":
			frappe.throw(frappe._("Rejected Overtime Slip Request cannot be submitted."))

		if self.status != "Approved":
			self.validate_current_user_can_approve()
			self.flags.allow_status_change = True
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

	def prevent_self_approval(self):
		return bool(
			frappe.db.get_single_value("HR Settings", "custom_prevent_self_overtime_approval")
		)

	def is_self_approval(self):
		if not self.employee or not self.prevent_self_approval():
			return False

		employee_user = frappe.db.get_value("Employee", self.employee, "user_id")
		return bool(employee_user and employee_user == frappe.session.user)

	def validate_current_user_can_approve(self):
		if self.is_self_approval():
			frappe.throw(frappe._("Self-approval for Overtime Slip Requests is not allowed."))

		if not self.can_current_user_approve():
			frappe.throw(frappe._("Only the Overtime Request Approver can approve this request."))

	def validate_status_change_permission(self):
		if not self.is_status_change() or self.flags.get("allow_status_change"):
			return

		if self.status == "Cancelled":
			frappe.throw(frappe._("Use Cancel to set an Overtime Slip Request to Cancelled."))

		if not can_current_user_manage_status():
			frappe.throw(
				frappe._("Only users with the {0} role can change Status.").format(
					frappe.bold(STATUS_MANAGER_ROLE)
				),
				frappe.PermissionError,
			)

		if self.status == "Approved" and self.is_self_approval():
			frappe.throw(frappe._("Self-approval for Overtime Slip Requests is not allowed."))

		self.set_status_audit_fields()

	def is_status_change(self):
		if self.is_new():
			return self.status not in (None, "Open")
		return self.has_value_changed("status")

	def set_status_audit_fields(self):
		if self.status == "Approved":
			self.approved_by = frappe.session.user
			self.approved_on = now_datetime()
			self.rejection_reason = None
		elif self.status == "Rejected":
			if not self.rejection_reason:
				frappe.throw(frappe._("Rejection Reason is required."))
			self.approved_by = None
			self.approved_on = None
		elif self.status == "Open":
			self.approved_by = None
			self.approved_on = None
			self.rejection_reason = None

	@frappe.whitelist()
	def approve(self):
		if self.docstatus != 0:
			frappe.throw(frappe._("Only draft Overtime Slip Requests can be approved."))
		self.validate_current_user_can_approve()

		self.flags.allow_status_change = True
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

		self.flags.allow_status_change = True
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


def can_current_user_manage_status():
	return STATUS_MANAGER_ROLE in frappe.get_roles()
