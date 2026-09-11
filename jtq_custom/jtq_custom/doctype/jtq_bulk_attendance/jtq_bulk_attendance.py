import re

import frappe
from erpnext.setup.doctype.employee.employee import is_holiday
from frappe.model.document import Document
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate
from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on


LEAVE_TYPE_PRIORITY = ("Annual Leave", "Casual Leave", "Sick Leave")
BATCH_SIZE = 25


class JTQBulkAttendance(Document):
	def validate(self):
		self.validate_dates()
		self.validate_company()
		self.total_employees = len(self.get("employees", []))
		self.total_dates = len(get_inclusive_dates(self.from_date, self.to_date)) if self.from_date and self.to_date else 0

	def on_submit(self):
		if not self.employees:
			frappe.throw(frappe._("Please load employees before submitting Bulk Attendance."))

		queue_attendance_processing(self, enqueue_after_commit=True)

	def validate_company(self):
		if not self.company:
			frappe.throw(frappe._("Please select Company before fetching or processing employees."))

	def validate_dates(self):
		if not self.from_date or not self.to_date:
			frappe.throw(frappe._("From Date and To Date are required."))

		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(frappe._("From Date cannot be after To Date."))

	def load_employees(self):
		self.validate_dates()
		self.validate_company()
		self.set("employees", [])
		fetch_result = get_matching_employees(self, with_summary=True)
		self._employee_fetch_summary = fetch_result.summary
		for employee in fetch_result.employees:
			self.append(
				"employees",
				{
					"employee": employee.name,
					"employee_name": employee.employee_name,
					"region": employee.region,
					"madrasa": employee.custom_madrasa,
					"shift": get_employee_shift(employee.name, self.from_date, self.to_date, self.shift),
					"current_attendance_status": get_attendance_status_summary(
						employee.name,
						self.from_date,
						self.to_date,
						self.shift,
					),
					"available_leave_summary": get_available_leave_summary(employee.name, self.from_date),
					"processing_status": "Pending",
				},
			)

		self.total_employees = len(self.employees)
		self.total_dates = len(get_inclusive_dates(self.from_date, self.to_date))
		self.processed_count = 0
		self.failed_count = 0
		self.processing_status = "Employees Loaded"

	def run_attendance_processing(self):
		self.validate_dates()
		if not self.employees:
			frappe.throw(frappe._("Please load employees before processing attendance."))

		self.processing_status = "In Progress"
		self.save(ignore_permissions=True)
		frappe.db.commit()

		processed = 0
		failed = 0
		for index, row in enumerate(self.employees, start=1):
			row_processed, row_failed, remarks = self.process_employee_row(row)
			processed += row_processed
			failed += row_failed
			row.processing_status = get_row_status(row_processed, row_failed)
			row.remarks = "\n".join(remarks)
			self.processed_count = processed
			self.failed_count = failed

			if index % BATCH_SIZE == 0:
				self.save(ignore_permissions=True)
				frappe.db.commit()

		self.processed_count = processed
		self.failed_count = failed
		if failed and processed:
			self.processing_status = "Partial"
		elif failed:
			self.processing_status = "Failed"
		else:
			self.processing_status = "Processed"

	def process_employee_row(self, row):
		remarks = []
		processed = 0
		failed = 0
		try:
			row._exception_dates = get_row_exception_dates(self, row)
		except Exception as exc:
			message = frappe.get_message_log()[-1].get("message") if frappe.get_message_log() else exc
			frappe.clear_messages()
			return 0, 1, [f"Failed row: {message}"]

		for attendance_date in get_row_dates(self, row):
			try:
				result = process_employee_attendance_date(self, row, attendance_date)
				remarks.append(result)
				if result.startswith("Failed"):
					failed += 1
				else:
					processed += 1
			except Exception as exc:
				failed += 1
				remarks.append(f"Failed {attendance_date}: {frappe.get_message_log()[-1].get('message') if frappe.get_message_log() else exc}")
				frappe.clear_messages()

		return processed, failed, remarks


def get_matching_employees(doc, with_summary=False):
	filters = {
		"status": "Active",
	}
	for fieldname, value in {
		"company": doc.company,
		"branch": doc.branch,
		"employment_type": doc.employment_type,
		"designation": doc.designation,
		"grade": doc.employee_grade,
	}.items():
		if value:
			filters[fieldname] = value

	departments = get_department_with_children(doc.department)
	if doc.department:
		if not departments:
			return get_empty_employee_fetch_result(with_summary)
		filters["department"] = ["in", departments]

	group_employees = get_employee_group_members(doc.employee_group)
	if doc.employee_group:
		if not group_employees:
			return get_empty_employee_fetch_result(with_summary)
		filters["name"] = ["in", group_employees]

	employees = frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "date_of_joining", "region", "custom_madrasa"],
		order_by="employee_name",
	)
	matched_filters = len(employees)
	employees = filter_employees_by_joining_date(employees, doc.to_date)
	joined_after_to_date = matched_filters - len(employees)
	fetch_result = filter_employees_by_manual_attendance_shift(employees, doc)
	fetch_result.summary["matched_filters"] = matched_filters
	fetch_result.summary["joined_after_to_date"] = joined_after_to_date
	if with_summary:
		return fetch_result
	return fetch_result.employees


def get_empty_employee_fetch_result(with_summary=False):
	result = frappe._dict(
		{
			"employees": [],
			"summary": {
				"matched_filters": 0,
				"joined_after_to_date": 0,
				"without_active_shift": 0,
				"auto_attendance_enabled": 0,
				"qualified": 0,
			},
		}
	)
	return result if with_summary else result.employees


def filter_employees_by_joining_date(employees, to_date):
	return [
		employee
		for employee in employees
		if not employee.date_of_joining or getdate(employee.date_of_joining) <= getdate(to_date)
	]


def get_employee_group_members(employee_group):
	if not employee_group:
		return []

	return frappe.get_all(
		"Employee Group Table",
		filters={
			"parent": employee_group,
			"parenttype": "Employee Group",
			"parentfield": "employee_list",
		},
		pluck="employee",
	)


def get_department_with_children(department):
	if not department:
		return []

	department_bounds = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
	if not department_bounds:
		return []

	return frappe.get_all(
		"Department",
		filters={
			"lft": [">=", department_bounds.lft],
			"rgt": ["<=", department_bounds.rgt],
		},
		pluck="name",
	)


def get_employee_shift(employee, from_date, to_date, selected_shift=None):
	assignment = get_active_shift_assignment(employee, from_date, to_date, selected_shift)
	if assignment:
		return assignment.shift_type

	default_shift = frappe.db.get_value("Employee", employee, "default_shift")
	if default_shift and (not selected_shift or default_shift == selected_shift):
		return default_shift
	return None


def filter_employees_by_manual_attendance_shift(employees, doc):
	filtered_employees = []
	summary = {
		"matched_filters": len(employees),
		"without_active_shift": 0,
		"auto_attendance_enabled": 0,
		"qualified": 0,
	}
	for employee in employees:
		shift = get_employee_shift(employee.name, doc.from_date, doc.to_date, doc.shift)
		if not shift:
			summary["without_active_shift"] += 1
			continue
		if doc.shift and shift != doc.shift:
			summary["without_active_shift"] += 1
			continue
		if not is_shift_auto_attendance_disabled(shift):
			summary["auto_attendance_enabled"] += 1
			continue
		filtered_employees.append(employee)

	summary["qualified"] = len(filtered_employees)
	return frappe._dict({"employees": filtered_employees, "summary": summary})


def get_active_shift_assignment(employee, from_date, to_date, selected_shift=None):
	conditions = [
		"docstatus = 1",
		"status = 'Active'",
		"employee = %(employee)s",
		"start_date <= %(to_date)s",
		"(end_date is null or end_date >= %(from_date)s)",
	]
	params = {
		"employee": employee,
		"from_date": from_date,
		"to_date": to_date,
	}
	if selected_shift:
		conditions.append("shift_type = %(selected_shift)s")
		params["selected_shift"] = selected_shift

	assignments = frappe.db.sql(
		f"""
		select shift_type
		from `tabShift Assignment`
		where {" and ".join(conditions)}
		order by start_date desc
		limit 1
		""",
		params,
		as_dict=True,
	)
	return assignments[0] if assignments else None


def is_shift_auto_attendance_disabled(shift):
	if not shift:
		return False
	return not cint(frappe.db.get_value("Shift Type", shift, "enable_auto_attendance"))


def get_attendance_status_summary(employee, from_date, to_date, shift=None):
	filters = {
		"employee": employee,
		"attendance_date": ["between", [from_date, to_date]],
		"docstatus": 1,
	}
	if shift:
		filters["shift"] = shift

	rows = frappe.get_all("Attendance", filters=filters, fields=["status"])
	if not rows:
		return "Unmarked"

	counts = {}
	for row in rows:
		counts[row.status] = counts.get(row.status, 0) + 1
	return ", ".join(f"{status}: {count}" for status, count in sorted(counts.items()))


def get_inclusive_dates(from_date, to_date):
	if not from_date or not to_date:
		return []
	return [getdate(add_days(from_date, day)) for day in range(date_diff(to_date, from_date) + 1)]


def get_row_dates(doc, row):
	return get_inclusive_dates(doc.from_date, doc.to_date)


def get_row_exception_dates(doc, row):
	if not row.dates:
		return set()

	dates = set()
	for value in re.split(r"[,\n]+", row.dates):
		value = value.strip()
		if not value:
			continue
		parsed_date = parse_row_date(doc, row, value)
		if parsed_date < getdate(doc.from_date) or parsed_date > getdate(doc.to_date):
			frappe.throw(
				frappe._("Date {0} in row {1} is outside the parent date range.").format(
					value,
					row.idx,
				)
			)
		dates.add(parsed_date)
	return dates


def parse_row_date(doc, row, value):
	if value.isdigit():
		parsed_date = parse_day_number_date(doc, row, value)
		if parsed_date:
			return parsed_date

		if getdate(doc.from_date).strftime("%Y-%m") != getdate(doc.to_date).strftime("%Y-%m"):
			frappe.throw(
				frappe._(
					"Day number {0} in row {1} is ambiguous for this date range. Please enter a full date."
				).format(value, row.idx)
			)

		return getdate(f"{getdate(doc.from_date).strftime('%Y-%m')}-{int(value):02d}")

	try:
		return getdate(value)
	except Exception:
		frappe.throw(frappe._("Invalid date {0} in row {1}.").format(value, row.idx))


def parse_day_number_date(doc, row, value):
	day = cint(value)
	if day < 1 or day > 31:
		frappe.throw(frappe._("Invalid day number {0} in row {1}.").format(value, row.idx))

	from_date = getdate(doc.from_date)
	to_date = getdate(doc.to_date)
	month_start = getdate(f"{from_date.strftime('%Y-%m')}-01")
	candidates = []

	current = month_start
	while current <= to_date:
		try:
			candidate = getdate(f"{current.strftime('%Y-%m')}-{day:02d}")
		except Exception:
			candidate = None

		if candidate and from_date <= candidate <= to_date:
			candidates.append(candidate)

		current = add_days(getdate(f"{current.strftime('%Y-%m')}-01"), 32)
		current = getdate(f"{current.strftime('%Y-%m')}-01")

	if len(candidates) == 1:
		return candidates[0]

	return None


def process_employee_attendance_date(doc, row, attendance_date):
	if cint(doc.include_holidays) and is_employee_holiday(row.employee, attendance_date):
		return f"Skipped {attendance_date}: Holiday"

	exception_dates = getattr(row, "_exception_dates", set())
	action = row.action if attendance_date in exception_dates else "Present"
	if not action:
		action = "On Leave" if attendance_date in exception_dates else "Present"

	existing_attendance = get_existing_attendance(row.employee, attendance_date, row.shift)

	if action == "On Leave":
		if existing_attendance and existing_attendance_matches_status(existing_attendance, "On Leave"):
			set_bulk_attendance_reference(existing_attendance, doc, row)
			return f"Updated {existing_attendance} for {attendance_date}: On Leave already exists"

		leave_type = get_available_leave_type(row.employee, attendance_date)
		if not leave_type:
			return update_existing_attendance(
				doc,
				row,
				existing_attendance,
				attendance_date,
				"Absent",
				remark="Leave unavailable; marked Absent",
			)

		if existing_attendance:
			attendance = frappe.get_doc("Attendance", existing_attendance)
			if not can_replace_existing_attendance(attendance):
				return f"Skipped {attendance_date}: Existing attendance {attendance.name} has status {attendance.status}; not replaced"
			replace_existing_attendance(existing_attendance)

		leave_application = create_leave_application(doc, row, attendance_date, leave_type)
		if leave_application:
			leave_attendance = get_existing_attendance(row.employee, attendance_date)
			if leave_attendance:
				set_bulk_attendance_reference(leave_attendance, doc, row)
				return f"Created {leave_attendance} for {attendance_date}: On Leave"
			return mark_attendance(
				doc,
				row,
				attendance_date,
				"On Leave",
				leave_type=leave_type,
				leave_application=leave_application,
			)
		return mark_attendance(
			doc,
			row,
			attendance_date,
			"Absent",
			remark="Leave unavailable; kept Absent",
		)

	if action == "Half Day":
		return update_existing_attendance(doc, row, existing_attendance, attendance_date, "Half Day")

	if action == "Absent":
		return update_existing_attendance(doc, row, existing_attendance, attendance_date, "Absent")

	return update_existing_attendance(doc, row, existing_attendance, attendance_date, "Present")


def existing_attendance_matches_status(attendance_name, status, leave_type=None):
	attendance = frappe.get_doc("Attendance", attendance_name)
	if attendance.docstatus != 1:
		return False

	if status == "On Leave":
		if leave_type:
			return attendance.status == "On Leave" and attendance.leave_type == leave_type
		return attendance.status == "On Leave"

	return attendance.status == status


def set_bulk_attendance_reference(attendance_name, doc, row):
	frappe.db.set_value(
		"Attendance",
		attendance_name,
		{
			"custom_jtq_bulk_attendance": doc.name,
			"custom_jtq_bulk_attendance_row": row.name,
		},
		update_modified=False,
	)


def replace_existing_attendance(attendance_name):
	attendance = frappe.get_doc("Attendance", attendance_name)
	attendance.flags.ignore_permissions = True
	if attendance.docstatus == 1:
		attendance.cancel()
	elif attendance.docstatus == 0:
		frappe.delete_doc("Attendance", attendance.name, force=1, ignore_permissions=True)


def update_existing_attendance(doc, row, attendance_name, attendance_date, status, leave_type=None, leave_application=None, remark=None):
	if not attendance_name:
		return mark_attendance(
			doc,
			row,
			attendance_date,
			status,
			leave_type=leave_type,
			leave_application=leave_application,
			remark=remark,
		)

	if existing_attendance_matches_status(attendance_name, status, leave_type):
		set_bulk_attendance_reference(attendance_name, doc, row)
		return f"Updated {attendance_name} for {attendance_date}: {remark or status}"

	attendance = frappe.get_doc("Attendance", attendance_name)
	if status == "Present" and attendance.status in ("Present", "On Leave"):
		set_bulk_attendance_reference(attendance.name, doc, row)
		return f"Skipped {attendance_date}: Existing attendance {attendance.name} is already {attendance.status}"

	if not can_replace_existing_attendance(attendance):
		return f"Skipped {attendance_date}: Existing attendance {attendance.name} has status {attendance.status}; not replaced"

	return replace_with_attendance(
		doc,
		row,
		attendance_name,
		attendance_date,
		status,
		leave_type=leave_type,
		leave_application=leave_application,
		remark=remark,
	)


def can_replace_existing_attendance(attendance):
	return attendance.status == "Absent" or bool(attendance.get("custom_jtq_bulk_attendance"))


def replace_with_attendance(doc, row, attendance_name, attendance_date, status, leave_type=None, leave_application=None, remark=None):
	replace_existing_attendance(attendance_name)
	return mark_attendance(
		doc,
		row,
		attendance_date,
		status,
		leave_type=leave_type,
		leave_application=leave_application,
		remark=remark,
	)


def is_employee_holiday(employee, attendance_date):
	try:
		return is_holiday(employee, attendance_date)
	except Exception as exc:
		message = str(exc)
		if "default Holiday List" in message:
			frappe.clear_messages()
			return False
		raise


def get_available_leave_type(employee, attendance_date):
	for leave_type in LEAVE_TYPE_PRIORITY:
		if get_leave_balance(employee, leave_type, attendance_date) > 0:
			return leave_type
	return None


def get_available_leave_summary(employee, attendance_date):
	parts = []
	for leave_type in LEAVE_TYPE_PRIORITY:
		parts.append(f"{leave_type}: {get_leave_balance(employee, leave_type, attendance_date):g}")
	return ", ".join(parts)


def get_leave_balance(employee, leave_type, attendance_date):
	if not leave_type:
		return 0
	try:
		balance = get_leave_balance_on(employee, leave_type, attendance_date, for_consumption=True) or {}
	except Exception:
		frappe.clear_messages()
		return 0

	if isinstance(balance, dict):
		return flt(balance.get("leave_balance_for_consumption") or balance.get("leave_balance"))
	return flt(balance)


def create_leave_application(doc, row, attendance_date, leave_type):
	try:
		leave_application = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": row.employee,
				"leave_type": leave_type,
				"from_date": attendance_date,
				"to_date": attendance_date,
				"company": doc.company or frappe.db.get_value("Employee", row.employee, "company"),
				"posting_date": nowdate(),
				"status": "Approved",
				"description": f"Created from JTQ Bulk Attendance {doc.name}",
				"custom_jtq_bulk_attendance": doc.name,
				"custom_jtq_bulk_attendance_row": row.name,
			}
		)
		leave_application.insert(ignore_permissions=True)
		leave_application.submit()
		return leave_application.name
	except Exception:
		frappe.log_error(frappe.get_traceback(), "JTQ Bulk Attendance Leave Application Failed")
		frappe.clear_messages()
		return None


def mark_attendance(doc, row, attendance_date, status, leave_type=None, leave_application=None, remark=None):
	attendance = frappe.get_doc(
		{
			"doctype": "Attendance",
			"employee": row.employee,
			"attendance_date": attendance_date,
			"status": status,
			"company": doc.company or frappe.db.get_value("Employee", row.employee, "company"),
			"shift": row.shift,
			"leave_type": leave_type,
			"leave_application": leave_application,
			"half_day_status": "Absent" if status == "Half Day" else None,
			"custom_jtq_bulk_attendance": doc.name,
			"custom_jtq_bulk_attendance_row": row.name,
		}
	)
	attendance.insert(ignore_permissions=True)
	attendance.submit()
	if remark:
		return f"Created {attendance.name} for {attendance_date}: {remark}"
	return f"Created {attendance.name} for {attendance_date}: {status}"


def get_existing_attendance(employee, attendance_date, shift=None):
	filters = {
		"employee": employee,
		"attendance_date": attendance_date,
		"docstatus": ["!=", 2],
	}
	return frappe.db.exists("Attendance", filters)


def get_row_status(processed, failed):
	if processed and failed:
		return "Partial"
	if failed:
		return "Failed"
	return "Processed"


@frappe.whitelist()
def get_employees(docname=None, doc=None):
	doc = get_bulk_attendance_doc(docname, doc)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(frappe._("Employees can only be fetched for Draft Bulk Attendance records."))
	doc.load_employees()
	fetch_summary = getattr(doc, "_employee_fetch_summary", {})
	doc.save(ignore_permissions=True)
	return {
		"total_employees": doc.total_employees,
		"total_dates": doc.total_dates,
		"message": get_employee_fetch_message(fetch_summary),
		"summary": fetch_summary,
	}


def get_employee_fetch_message(summary):
	if not summary:
		return ""

	if summary.get("qualified"):
		return frappe._("{0} employees loaded.").format(summary.get("qualified"))

	if not summary.get("matched_filters"):
		return frappe._("No active employees matched the selected filters.")

	if summary.get("joined_after_to_date") and not (
		summary.get("without_active_shift") or summary.get("auto_attendance_enabled")
	):
		return frappe._("No employees were loaded because matched employees joined after the To Date.")

	if summary.get("without_active_shift") and not summary.get("auto_attendance_enabled"):
		return frappe._(
			"No employees were loaded because the matched employees do not have an active Shift Assignment for the selected date range."
		)

	if summary.get("auto_attendance_enabled") and not summary.get("without_active_shift"):
		return frappe._(
			"No employees were loaded because the matched employees have Auto Attendance enabled on their assigned Shift Type."
		)

	return frappe._(
		"No employees were loaded. {0} matched the filters, {1} joined after the To Date, {2} had no active manual-attendance shift, and {3} had Auto Attendance enabled."
	).format(
		summary.get("matched_filters", 0),
		summary.get("joined_after_to_date", 0),
		summary.get("without_active_shift", 0),
		summary.get("auto_attendance_enabled", 0),
	)


def get_bulk_attendance_doc(docname=None, doc=None):
	if doc:
		parsed_doc = frappe.parse_json(doc)
		return frappe.get_doc(parsed_doc)

	if not docname:
		frappe.throw(frappe._("Bulk Attendance document is required."))

	return frappe.get_doc("JTQ Bulk Attendance", docname)


@frappe.whitelist()
def get_employee_bulk_attendance_defaults(employee, from_date=None, to_date=None, selected_shift=None):
	if not employee:
		return {}

	employee_details = frappe.db.get_value(
		"Employee",
		employee,
		["employee_name", "region", "custom_madrasa"],
		as_dict=True,
	)
	if not employee_details:
		return {}

	return {
		"employee_name": employee_details.employee_name,
		"region": employee_details.region,
		"madrasa": employee_details.custom_madrasa,
		"shift": get_employee_shift(employee, from_date, to_date, selected_shift) if from_date and to_date else None,
	}


@frappe.whitelist()
def process_attendance(docname):
	if not docname:
		frappe.throw(frappe._("Bulk Attendance document is required."))

	doc = frappe.get_doc("JTQ Bulk Attendance", docname)
	doc.check_permission("write")

	if doc.docstatus != 1:
		frappe.throw(frappe._("Please submit Bulk Attendance before processing attendance."))

	if not doc.get("employees"):
		frappe.throw(frappe._("Please load employees before processing attendance."))

	return queue_attendance_processing(doc)


def queue_attendance_processing(doc, enqueue_after_commit=False):
	if doc.processing_status in ("Queued", "In Progress"):
		return {
			"processed_count": doc.processed_count,
			"failed_count": doc.failed_count,
			"processing_status": doc.processing_status,
		}

	if enqueue_after_commit:
		doc.processing_status = "Queued"
	else:
		doc.db_set("processing_status", "Queued", update_modified=True)
		frappe.db.commit()

	frappe.enqueue(
		"jtq_custom.jtq_custom.doctype.jtq_bulk_attendance.jtq_bulk_attendance.process_attendance_job",
		docname=doc.name,
		queue="long",
		timeout=7200,
		enqueue_after_commit=enqueue_after_commit,
	)
	return {
		"processed_count": doc.processed_count,
		"failed_count": doc.failed_count,
		"processing_status": "Queued",
	}


def process_attendance_job(docname):
	doc = frappe.get_doc("JTQ Bulk Attendance", docname)
	try:
		doc.run_attendance_processing()
		doc.save(ignore_permissions=True)
	except Exception:
		doc.db_set("processing_status", "Failed", update_modified=True)
		frappe.log_error(frappe.get_traceback(), "JTQ Bulk Attendance Background Processing Failed")
		raise
