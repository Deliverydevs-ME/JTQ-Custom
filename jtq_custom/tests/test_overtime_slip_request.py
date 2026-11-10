from unittest import TestCase
from unittest.mock import patch

import frappe

from jtq_custom.jtq_custom.doctype.overtime_slip_request.overtime_slip_request import (
	OvertimeSlipRequest,
	get_overtime_rate,
)
from jtq_custom.patches.add_overtime_request_approval_controls import get_custom_fields


class TestOvertimeSlipRequest(TestCase):
	def test_total_overtime_hours_comes_from_detail_rows(self):
		request = object.__new__(OvertimeSlipRequest)
		request.overtime_details = [
			frappe._dict(custom_overtime_hours=1.25),
			frappe._dict(custom_overtime_hours=2.5),
		]

		request.total_overtime_hours = round(
			sum(row.custom_overtime_hours for row in request.overtime_details), 2
		)

		self.assertEqual(request.total_overtime_hours, 3.75)

	@patch(
		"jtq_custom.jtq_custom.doctype.overtime_slip_request.overtime_slip_request.get_overtime_multiplier",
		return_value=1.5,
	)
	def test_fixed_hourly_rate_uses_overtime_type_multiplier(self, get_multiplier):
		overtime_type = frappe._dict(
			custom_overtime_amount_calculation="Fixed Hourly Rate",
			custom_hourly_rate=200,
			name="Weekend Overtime",
		)

		rate = get_overtime_rate(overtime_type, "HR-EMP-00001", "ATT-00001", "2026-11-01")

		self.assertEqual(rate, 300)
		get_multiplier.assert_called_once_with(overtime_type, "HR-EMP-00001", "2026-11-01")

	def test_hr_settings_field_definition_is_present(self):
		field = get_custom_fields()["HR Settings"][0]

		self.assertEqual(field["fieldname"], "custom_prevent_self_overtime_approval")
		self.assertEqual(field["label"], "Prevent Self Approval for Overtime Request")
