from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from jtq_custom.jtq_custom.doctype.jtq_bulk_attendance.jtq_bulk_attendance import (
	get_employee_fetch_message,
	get_inclusive_dates,
)


class TestJTQBulkAttendance(FrappeTestCase):
	def test_inclusive_dates_include_to_date(self):
		dates = get_inclusive_dates("2026-07-25", "2026-08-26")

		self.assertEqual(dates[0], getdate("2026-07-25"))
		self.assertEqual(dates[-1], getdate("2026-08-26"))
		self.assertEqual(len(dates), 33)

	def test_fetch_message_reports_joined_after_to_date(self):
		message = get_employee_fetch_message(
			{
				"matched_filters": 2,
				"joined_after_to_date": 2,
				"without_active_shift": 0,
				"auto_attendance_enabled": 0,
				"qualified": 0,
			}
		)

		self.assertIn("joined after the To Date", message)
