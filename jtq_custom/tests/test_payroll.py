from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

import frappe

from jtq_custom.overrides.salary_slip import JTQSalarySlip, SalarySlip
from jtq_custom.payroll import (
	create_employee_salary_structure_assignment,
	get_employee_salary_structure_components,
	is_earning_eligible,
	normalize_employee_names,
	process_bulk_salary_assignments,
	unlink_cancelled_salary_structure_assignment,
)


class TestEarningEligibility(TestCase):
	def test_zero_days_is_immediately_eligible(self):
		self.assertTrue(is_earning_eligible(None, None, 0))

	def test_component_is_not_eligible_before_threshold(self):
		self.assertFalse(is_earning_eligible("2026-01-01", "2026-01-30", 30))

	def test_component_is_eligible_on_threshold(self):
		self.assertTrue(is_earning_eligible("2026-01-01", "2026-01-31", 30))

	def test_component_is_eligible_after_threshold(self):
		self.assertTrue(is_earning_eligible(date(2026, 1, 1), date(2026, 7, 1), 180))

	def test_positive_days_require_both_dates(self):
		self.assertFalse(is_earning_eligible(None, "2026-07-01", 180))
		self.assertFalse(is_earning_eligible("2026-01-01", None, 180))

	def test_negative_days_are_treated_as_immediate(self):
		self.assertTrue(is_earning_eligible(None, None, -1))

	@patch.object(JTQSalarySlip, "apply_advance_recovery_controls")
	@patch.object(SalarySlip, "add_additional_salary_components")
	def test_additional_salary_earnings_bypass_eligibility(self, add_additional, advance_controls):
		salary_slip = object.__new__(JTQSalarySlip)

		salary_slip.add_additional_salary_components("earnings")

		add_additional.assert_called_once_with("earnings")
		advance_controls.assert_not_called()

	@patch.object(JTQSalarySlip, "apply_advance_recovery_controls")
	@patch.object(SalarySlip, "add_additional_salary_components")
	def test_additional_salary_deductions_keep_existing_controls(
		self,
		add_additional,
		advance_controls,
	):
		salary_slip = object.__new__(JTQSalarySlip)

		salary_slip.add_additional_salary_components("deductions")

		add_additional.assert_called_once_with("deductions")
		advance_controls.assert_called_once_with()


class TestBulkSalaryAssignmentInput(TestCase):
	def test_employee_names_are_deduplicated_in_selection_order(self):
		self.assertEqual(
			normalize_employee_names(
				[
					"HR-EMP-00001",
					{"name": "HR-EMP-00002"},
					{"employee": "HR-EMP-00001"},
					" ",
				]
			),
			["HR-EMP-00001", "HR-EMP-00002"],
		)

	def test_json_employee_selection_is_supported(self):
		self.assertEqual(
			normalize_employee_names('["HR-EMP-00001", "HR-EMP-00002"]'),
			["HR-EMP-00001", "HR-EMP-00002"],
		)

	@patch("jtq_custom.payroll.frappe.publish_progress")
	@patch("jtq_custom.payroll.validate_salary_assignment_permissions")
	@patch("jtq_custom.payroll._create_salary_assignment_from_employee")
	@patch("jtq_custom.payroll.frappe.get_doc")
	@patch("jtq_custom.payroll.frappe.db.rollback")
	@patch("jtq_custom.payroll.frappe.db.savepoint")
	def test_bulk_processing_keeps_successes_when_an_employee_fails(
		self,
		savepoint,
		rollback,
		get_doc,
		create_assignment,
		validate_permissions,
		publish_progress,
	):
		employee_one = frappe._dict(name="HR-EMP-00001", employee_name="Employee One")
		employee_two = frappe._dict(name="HR-EMP-00002", employee_name="Employee Two")
		get_doc.side_effect = [employee_one, employee_two]
		create_assignment.side_effect = [
			frappe._dict(
				name="HR-SSA-00001",
				salary_structure="Office Staff",
			),
			frappe.ValidationError("Missing Assignment From Date"),
		]

		result = process_bulk_salary_assignments([employee_one.name, employee_two.name])

		self.assertEqual(len(result["success"]), 1)
		self.assertEqual(result["success"][0]["employee"], employee_one.name)
		self.assertEqual(result["failed"][0]["employee"], employee_two.name)
		self.assertIn("Missing Assignment From Date", result["failed"][0]["message"])
		savepoint.assert_has_calls(
			[call("jtq_salary_assignment_1"), call("jtq_salary_assignment_2")]
		)
		rollback.assert_called_once_with(save_point="jtq_salary_assignment_2")
		self.assertEqual(validate_permissions.call_count, 2)
		self.assertEqual(publish_progress.call_count, 2)


class TestEmployeeSalaryStructureComponents(TestCase):
	@patch("jtq_custom.payroll.frappe.get_doc")
	def test_selected_structure_copies_earning_and_deduction_values(self, get_doc):
		earning = frappe._dict(
			salary_component="Basic",
			abbr="B",
			amount=50000,
			year_to_date=120000,
			depends_on_payment_days=1,
			is_tax_applicable=1,
			condition="base > 0",
			formula="base * 0.1",
			amount_based_on_formula=1,
			statistical_component=0,
			is_flexible_benefit=0,
			variable_based_on_taxable_salary=0,
			exempted_from_income_tax=0,
			do_not_include_in_total=0,
			do_not_include_in_accounts=0,
			deduct_full_tax_on_selected_payroll_date=0,
			default_amount=45000,
			additional_amount=1000,
			tax_on_flexible_benefit=200,
			tax_on_additional_salary=100,
		)
		deduction = frappe._dict(
			salary_component="Tax",
			abbr="T",
			amount=2500,
			year_to_date=0,
			depends_on_payment_days=0,
			is_tax_applicable=1,
			condition="",
			formula="",
			amount_based_on_formula=0,
			statistical_component=0,
			is_flexible_benefit=0,
			variable_based_on_taxable_salary=1,
			exempted_from_income_tax=0,
			do_not_include_in_total=0,
			do_not_include_in_accounts=0,
			deduct_full_tax_on_selected_payroll_date=1,
			default_amount=2500,
			additional_amount=0,
			tax_on_flexible_benefit=0,
			tax_on_additional_salary=0,
		)
		get_doc.return_value = frappe._dict(
			name="Office Staff",
			company="JTQ",
			currency="PKR",
			docstatus=1,
			is_active="Yes",
			earnings=[earning],
			deductions=[deduction],
		)

		components = get_employee_salary_structure_components("Office Staff")

		self.assertEqual(components["earnings"][0]["amount"], 50000)
		self.assertEqual(components["earnings"][0]["default_amount"], 45000)
		self.assertEqual(components["earnings"][0]["formula"], "base * 0.1")
		self.assertEqual(components["deductions"][0]["amount"], 2500)
		self.assertEqual(components["deductions"][0]["deduct_full_tax_on_selected_payroll_date"], 1)

	@patch("jtq_custom.payroll.frappe.new_doc")
	def test_assignment_does_not_copy_component_totals_to_base_or_variable(self, new_doc):
		assignment = SimpleNamespace(
			flags=SimpleNamespace(),
			insert=MagicMock(),
			submit=MagicMock(),
		)
		new_doc.return_value = assignment
		employee = frappe._dict(
			name="HR-EMP-00001",
			company="JTQ",
			custom_income_tax_slab="Tax Slab 2026",
		)
		salary_structure = frappe._dict(
			name="Office Staff",
			currency="PKR",
			earnings=[frappe._dict(amount=50000)],
			deductions=[frappe._dict(amount=2500)],
		)

		create_employee_salary_structure_assignment(employee, salary_structure, "2026-10-01")

		self.assertEqual(assignment.employee, "HR-EMP-00001")
		self.assertEqual(assignment.salary_structure, "Office Staff")
		self.assertEqual(assignment.income_tax_slab, "Tax Slab 2026")
		self.assertFalse(hasattr(assignment, "base"))
		self.assertFalse(hasattr(assignment, "variable"))
		self.assertFalse(hasattr(assignment, "leave_encashment_amount_per_day"))
		assignment.insert.assert_called_once_with()
		assignment.submit.assert_called_once_with()


class TestSalaryAssignmentCancellation(TestCase):
	def setUp(self):
		self.assignment = "HR-SSA-00001"
		self.assignment_data = frappe._dict(
			employee="HR-EMP-00001",
			salary_structure="Office Staff",
			income_tax_slab="Tax Slab 2026",
			docstatus=2,
		)

	@patch("jtq_custom.payroll.clear_employee_salary_component_rows")
	@patch("jtq_custom.payroll.frappe.db.set_value")
	@patch("jtq_custom.payroll.frappe.db.get_value")
	def test_manual_current_assignment_cancel_clears_salary_tab_and_both_links(
		self,
		get_value,
		set_value,
		clear_rows,
	):
		get_value.side_effect = [
			self.assignment_data,
			frappe._dict(
				custom_salary_structure="Office Staff",
				custom_salary_assignment_from_date="2026-01-01",
				custom_current_salary_structure_assignment=self.assignment,
				custom_income_tax_slab="Tax Slab 2026",
			),
			None,
		]

		unlink_cancelled_salary_structure_assignment(self.assignment)

		set_value.assert_has_calls(
			[
				call(
					"Employee",
					"HR-EMP-00001",
					{
						"custom_current_salary_structure_assignment": None,
						"custom_salary_structure": None,
						"custom_salary_assignment_from_date": None,
						"custom_income_tax_slab": None,
					},
					update_modified=False,
				),
				call(
					"Salary Structure Assignment",
					self.assignment,
					{"salary_structure": None, "income_tax_slab": None},
					update_modified=False,
				),
			]
		)
		clear_rows.assert_called_once_with("HR-EMP-00001")

	@patch("jtq_custom.payroll.clear_employee_salary_component_rows")
	@patch("jtq_custom.payroll.frappe.db.set_value")
	@patch("jtq_custom.payroll.frappe.db.get_value")
	def test_replacement_cancel_preserves_salary_configuration(
		self,
		get_value,
		set_value,
		clear_rows,
	):
		get_value.side_effect = [
			self.assignment_data,
			frappe._dict(
				custom_salary_structure="Office Staff",
				custom_salary_assignment_from_date="2026-01-01",
				custom_current_salary_structure_assignment=self.assignment,
				custom_income_tax_slab="Tax Slab 2026",
			),
			None,
		]

		unlink_cancelled_salary_structure_assignment(self.assignment, clear_salary_tab=False)

		set_value.assert_has_calls(
			[
				call(
					"Employee",
					"HR-EMP-00001",
					{"custom_current_salary_structure_assignment": None},
					update_modified=False,
				),
				call(
					"Salary Structure Assignment",
					self.assignment,
					{"salary_structure": None, "income_tax_slab": None},
					update_modified=False,
				),
			]
		)
		clear_rows.assert_not_called()

	@patch("jtq_custom.payroll.clear_employee_salary_component_rows")
	@patch("jtq_custom.payroll.frappe.db.set_value")
	@patch("jtq_custom.payroll.frappe.db.get_value")
	def test_historical_cancel_does_not_clear_current_employee_configuration(
		self,
		get_value,
		set_value,
		clear_rows,
	):
		get_value.side_effect = [
			self.assignment_data,
			frappe._dict(
				custom_salary_structure="Management Staff",
				custom_salary_assignment_from_date="2026-07-01",
				custom_current_salary_structure_assignment="HR-SSA-00002",
				custom_income_tax_slab="Tax Slab 2026",
			),
			"HR-SSA-00002",
		]

		unlink_cancelled_salary_structure_assignment(self.assignment)

		set_value.assert_called_once_with(
			"Salary Structure Assignment",
			self.assignment,
			{"salary_structure": None, "income_tax_slab": None},
			update_modified=False,
		)
		clear_rows.assert_not_called()
