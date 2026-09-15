frappe.ui.form.on("Overtime Slip Request", {
	setup(frm) {
		frm.set_query("employee", () => ({
			filters: {
				status: "Active",
			},
		}));

		frm.set_query("overtime_request_approver", () => ({
			filters: {
				enabled: 1,
			},
		}));
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 0 || frm.is_new()) {
			return;
		}

		if (frm.doc.status !== "Approved") {
			frm.add_custom_button(__("Approve"), () => {
				frm.call("approve").then(() => frm.reload_doc());
			});
		}

		if (frm.doc.status !== "Rejected") {
			frm.add_custom_button(__("Reject"), () => {
				frappe.prompt(
					[
						{
							fieldname: "rejection_reason",
							fieldtype: "Small Text",
							label: __("Rejection Reason"),
							reqd: 1,
						},
					],
					(values) => {
						frm.call("reject", {
							rejection_reason: values.rejection_reason,
						}).then(() => frm.reload_doc());
					},
					__("Reject Overtime Slip Request"),
					__("Reject")
				);
			});
		}
	},

	employee(frm) {
		if (!frm.doc.employee) {
			return;
		}

		frappe.db
			.get_value("Employee", frm.doc.employee, [
				"employee_name",
				"company",
				"department",
				"designation",
				"custom_overtime_request_approver",
			])
			.then((response) => {
				const employee = response.message || {};
				frm.set_value("employee_name", employee.employee_name || "");
				frm.set_value("company", employee.company || "");
				frm.set_value("department", employee.department || "");
				frm.set_value("designation", employee.designation || "");
				frm.set_value("overtime_request_approver", employee.custom_overtime_request_approver || "");
			});
	},
});
