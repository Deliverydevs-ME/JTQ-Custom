# Repository Changed to Deliverydevs-ME
app_name = "jtq_custom"
app_title = "JTQ Custom"
app_publisher = "JTQ"
app_description = "JTQ Customizations for ERPNext and HRMS"
app_email = "admin@example.com"
app_license = "mit"

fixtures = [
	{
		"dt": "Print Format",
		"filters": [
			[
				"name",
				"in",
				[
					"Appointment letter for Back Office",
					"Appointment Letter For Field Staff",
					"Salary Slip Print Format",
					"Appointment Letter Field Staff (Urdu)",
				],
			]
		],
	},
]

doctype_js = {
	"Attendance": "public/js/attendance.js",
	"Attendance Request": "public/js/attendance_request.js",
	"Compensatory Leave Request": "public/js/compensatory_leave_request.js",
	"Employee": "public/js/employee.js",
	"JTQ Bulk Attendance": "public/js/jtq_bulk_attendance.js",
	"Payroll Entry": "public/js/payroll_entry.js",
	"Salary Slip": "public/js/salary_slip.js",
	"Salary Structure": "public/js/salary_structure.js",
}

doctype_list_js = {
	"Attendance": "public/js/attendance_list.js",
	"Employee": "public/js/employee_list.js",
}

override_doctype_class = {
	"Compensatory Leave Request": "jtq_custom.overrides.compensatory_leave_request.JTQCompensatoryLeaveRequest",
	"Payroll Entry": "jtq_custom.overrides.payroll_entry.JTQPayrollEntry",
	"Salary Slip": "jtq_custom.overrides.salary_slip.JTQSalarySlip",
	"Salary Structure": "jtq_custom.overrides.salary_structure.JTQSalaryStructure",
}

override_whitelisted_methods = {
	"hrms.payroll.doctype.payroll_entry.payroll_entry.employee_query": "jtq_custom.overrides.payroll_entry.employee_query",
}

doc_events = {
	"Attendance": {
		"before_validate": "jtq_custom.attendance.calculate_attendance_time_fields",
		"before_submit": "jtq_custom.attendance.calculate_overtime_and_attendance_details",
	},
	"Attendance Request": {
		"on_submit": "jtq_custom.attendance.update_attendance_times_from_request",
	},
	"City": {
		"validate": "jtq_custom.master_utils.set_master_id",
	},
	"Compensatory Leave Request": {
		"validate": "jtq_custom.compensatory_leave.validate_compensatory_leave_working_hours",
	},
	"Leave Application": {
		"validate": "jtq_custom.leave_application.validate_minimum_consecutive_leaves",
	},
	"Leave Type": {
		"validate": "jtq_custom.leave_application.validate_leave_type_minimum_consecutive_leaves",
	},
	"Province": {
		"validate": "jtq_custom.master_utils.set_master_id",
	},
	"Additional Salary": {
		"before_validate": "jtq_custom.payroll.sync_additional_salary_controls",
		"before_update_after_submit": "jtq_custom.payroll.sync_additional_salary_controls",
	},
	"Employee": {
		"before_validate": "jtq_custom.employee.set_employee_hijri_date",
	},
	"Salary Slip": {
		"on_submit": "jtq_custom.payroll.sync_advance_recovery_from_salary_slip",
		"on_cancel": "jtq_custom.payroll.sync_advance_recovery_from_salary_slip",
	},
	"Salary Structure Assignment": {
		"on_cancel": "jtq_custom.payroll.unlink_salary_structure_on_assignment_cancel",
	},
	"Salary Structure": {
		"before_insert": "jtq_custom.payroll.populate_salary_structure_components",
		"validate": "jtq_custom.payroll.sync_salary_structure_title",
	},
}

after_install = "jtq_custom.patches.add_bulk_attendance_custom_fields.execute"
after_migrate = [
	"jtq_custom.patches.add_bulk_attendance_custom_fields.execute",
	"jtq_custom.patches.add_payroll_entry_location_fields.execute",
	"jtq_custom.patches.add_employee_location_work_mode_fields.execute",
	"jtq_custom.patches.add_advance_salary_recovery_controls.execute",
	"jtq_custom.patches.add_salary_structure_auto_component_fields.execute",
	"jtq_custom.patches.add_attendance_time_calculation_fields.execute",
	"jtq_custom.patches.add_attendance_request_time_fields.execute",
	"jtq_custom.patches.update_custom_master_fields.execute",
	"jtq_custom.patches.add_compensatory_leave_working_hours_field.execute",
	"jtq_custom.patches.add_employee_salary_structure_assignment_fields.execute",
	"jtq_custom.patches.add_compensatory_leave_allocation_reference.execute",
	"jtq_custom.patches.add_minimum_consecutive_leave_field.execute",
	"jtq_custom.patches.add_salary_structure_title_display.execute",
	"jtq_custom.patches.add_employee_appointment_letter_fields.execute",
	"jtq_custom.patches.add_employee_religious_qualification_fields.execute",
	"jtq_custom.patches.remove_employee_salary_empty_column_break.execute",
	"jtq_custom.patches.ensure_employee_location_fields.execute",
	"jtq_custom.patches.rework_employee_joining_location_fields.execute",
	"jtq_custom.patches.add_employee_bank_branch_fields.execute",
	"jtq_custom.patches.add_employee_income_tax_slab_field.execute",
	"jtq_custom.patches.add_salary_component_eligibility_days.execute",
]
