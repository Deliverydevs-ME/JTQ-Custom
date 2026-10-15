from unittest import TestCase
from unittest.mock import patch

import frappe

from jtq_custom.jtq_custom.doctype.overtime_slip_request.overtime_slip_request import (
	STATUS_MANAGER_ROLE,
	OvertimeSlipRequest,
)
from jtq_custom.patches.add_overtime_request_approval_controls import get_custom_fields


class TestOvertimeSlipRequestApprovalControls(TestCase):
	def make_request(self, status="Approved"):
		request = object.__new__(OvertimeSlipRequest)
		request.status = status
		request.employee = "HR-EMP-00001"
		request.flags = frappe._dict()
		request.is_new = lambda: False
		request.has_value_changed = lambda fieldname: fieldname == "status"
		request.approved_by = None
		request.approved_on = None
		request.rejection_reason = None
		return request

	@patch.object(OvertimeSlipRequest, "is_self_approval", return_value=True)
	def test_self_approval_is_rejected_before_approver_permissions_are_checked(self, is_self_approval):
		request = self.make_request()

		with self.assertRaises(frappe.ValidationError):
			request.validate_current_user_can_approve()

		is_self_approval.assert_called_once_with()

	@patch("jtq_custom.jtq_custom.doctype.overtime_slip_request.overtime_slip_request.frappe.get_roles")
	def test_direct_status_change_requires_status_manager_role(self, get_roles):
		request = self.make_request()
		get_roles.return_value = []

		with self.assertRaises(frappe.PermissionError):
			request.validate_status_change_permission()

		get_roles.assert_called_once_with()

	@patch.object(OvertimeSlipRequest, "is_self_approval", return_value=False)
	@patch("jtq_custom.jtq_custom.doctype.overtime_slip_request.overtime_slip_request.now_datetime")
	@patch("jtq_custom.jtq_custom.doctype.overtime_slip_request.overtime_slip_request.frappe.get_roles")
	def test_status_manager_can_approve_by_changing_status(
		self, get_roles, now_datetime, is_self_approval
	):
		request = self.make_request()
		get_roles.return_value = [STATUS_MANAGER_ROLE]
		now_datetime.return_value = "2026-10-15 10:00:00"

		request.validate_status_change_permission()

		self.assertEqual(request.approved_by, frappe.session.user)
		self.assertEqual(request.approved_on, "2026-10-15 10:00:00")
		self.assertIsNone(request.rejection_reason)
		is_self_approval.assert_called_once_with()

	def test_hr_settings_field_definition_is_present(self):
		field = get_custom_fields()["HR Settings"][0]

		self.assertEqual(field["fieldname"], "custom_prevent_self_overtime_approval")
		self.assertEqual(field["label"], "Prevent Self Approval for Overtime Request")
