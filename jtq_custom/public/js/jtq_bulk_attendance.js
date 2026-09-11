frappe.ui.form.on("JTQ Bulk Attendance", {
	refresh(frm) {
		setup_employee_grid_query(frm);

		if (!frm.is_new() && frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Employees"), () => {
				fetch_employees(frm, true);
			});
		}

		if (frm.doc.docstatus === 1 && ["Failed", "Partial"].includes(frm.doc.processing_status)) {
			frm.add_custom_button(__("Retry Processing"), () => {
				queue_attendance_processing(frm);
			});
		}
	},
	from_date: refetch_on_filter_change,
	to_date: refetch_on_filter_change,
	shift: refetch_on_filter_change,
	company: refetch_on_filter_change,
	branch: refetch_on_filter_change,
	employee_group: refetch_on_filter_change,
	department: refetch_on_filter_change,
	employment_type: refetch_on_filter_change,
	designation: refetch_on_filter_change,
	employee_grade: refetch_on_filter_change,
});

frappe.ui.form.on("JTQ Bulk Attendance Employee", {
	employee(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.employee) {
			frappe.model.set_value(cdt, cdn, {
				employee_name: "",
				region: "",
				madrasa: "",
				shift: "",
			});
			return;
		}

		frappe.call({
			method: "jtq_custom.jtq_custom.doctype.jtq_bulk_attendance.jtq_bulk_attendance.get_employee_bulk_attendance_defaults",
			args: {
				employee: row.employee,
				from_date: frm.doc.from_date,
				to_date: frm.doc.to_date,
				selected_shift: frm.doc.shift,
			},
			callback(response) {
				const employee = response.message || {};
				frappe.model.set_value(cdt, cdn, {
					employee_name: employee.employee_name || "",
					region: employee.region || "",
					madrasa: employee.madrasa || "",
					shift: employee.shift || "",
				});
			},
		});
	},
});

function setup_employee_grid_query(frm) {
	const employee_field = frm.fields_dict.employees?.grid?.get_field("employee");
	if (!employee_field) {
		return;
	}

	employee_field.get_query = () => {
		const filters = {
			status: "Active",
		};
		if (frm.doc.company) {
			filters.company = frm.doc.company;
		}
		return {
			filters,
			searchfield: "employee_name",
		};
	};
}

function process_attendance(frm) {
	if (frm.is_new()) {
		frappe.msgprint(__("Please save the document before processing attendance."));
		return;
	}

	if (frm.is_dirty()) {
		frm.save().then(() => queue_attendance_processing(frm));
		return;
	}

	queue_attendance_processing(frm);
}

function queue_attendance_processing(frm) {
	frappe.call({
		method: "jtq_custom.jtq_custom.doctype.jtq_bulk_attendance.jtq_bulk_attendance.process_attendance",
		args: {
			docname: frm.doc.name,
		},
		freeze: true,
		freeze_message: __("Queuing Attendance Processing..."),
		callback(response) {
			const result = response.message || {};
			frappe.msgprint(
				__("Attendance processing has been queued. Current status: {0}", [
					result.processing_status || __("Queued"),
				])
			);
			frm.reload_doc();
		},
	});
}

function refetch_on_filter_change(frm) {
	if (frm.__bulk_attendance_fetching) {
		return;
	}

	clear_employee_rows(frm);
}

function clear_employee_rows(frm) {
	frm.clear_table("employees");
	frm.set_value("total_employees", 0);
	frm.set_value("processed_count", 0);
	frm.set_value("failed_count", 0);
	frm.set_value("processing_status", "Draft");
	frm.refresh_field("employees");
}

function fetch_employees(frm, show_message) {
	if (frm.is_new()) {
		frappe.msgprint(__("Please save the document before fetching employees."));
		return;
	}

	if (!frm.doc.company) {
		frappe.msgprint(__("Please select Company before fetching employees."));
		return;
	}

	if (!frm.doc.from_date || !frm.doc.to_date) {
		frappe.msgprint(__("Please select From Date and To Date before fetching employees."));
		return;
	}

	if (frm.is_dirty()) {
		frm.save().then(() => fetch_employees(frm, show_message));
		return;
	}

	frm.__bulk_attendance_fetching = true;
	frappe.call({
		method: "jtq_custom.jtq_custom.doctype.jtq_bulk_attendance.jtq_bulk_attendance.get_employees",
		args: {
			docname: frm.doc.name,
		},
		freeze: true,
		freeze_message: __("Fetching Employees..."),
	})
		.then(async (response) => {
			const result = response.message || {};
			if (show_message) {
				frappe.msgprint(result.message || __("{0} employees loaded.", [result.total_employees || 0]));
			}
			await frm.reload_doc();
			frm.refresh_field("employees");
		})
		.finally(() => {
			frm.__bulk_attendance_fetching = false;
		});
}
