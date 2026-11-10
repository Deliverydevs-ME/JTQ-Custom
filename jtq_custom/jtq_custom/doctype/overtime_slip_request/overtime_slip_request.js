frappe.ui.form.on("Overtime Slip Request", {
	setup(frm) {
		frm.set_query("employee", () => ({ filters: { status: "Active" } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Fetch Overtime Details"), () => fetch_overtime_details(frm));
		}
	},

	employee(frm) {
		frm.trigger("clear_overtime_details");
	},

	from_date(frm) {
		frm.trigger("clear_overtime_details");
	},

	to_date(frm) {
		frm.trigger("clear_overtime_details");
	},

	clear_overtime_details(frm) {
		if (!frm.doc.overtime_details?.length) {
			return;
		}
		frm.clear_table("overtime_details");
		frm.set_value("total_overtime_hours", 0);
		frm.refresh_field("overtime_details");
	},
});

function fetch_overtime_details(frm) {
	if (!frm.doc.employee || !frm.doc.from_date || !frm.doc.to_date) {
		frappe.msgprint(__("Select Employee, From Date, and To Date before fetching overtime details."));
		return;
	}

	frappe.call({
		method:
			"jtq_custom.jtq_custom.doctype.overtime_slip_request.overtime_slip_request.get_attendance_overtime_details",
		args: {
			employee: frm.doc.employee,
			from_date: frm.doc.from_date,
			to_date: frm.doc.to_date,
			request_name: frm.doc.name,
		},
		freeze: true,
		freeze_message: __("Fetching Overtime Details"),
		callback: ({ message = [] }) => {
			frm.clear_table("overtime_details");
			message.forEach((detail) => frm.add_child("overtime_details", detail));
			frm.set_value(
				"total_overtime_hours",
				message.reduce((total, detail) => total + flt(detail.custom_overtime_hours), 0)
			);
			frm.refresh_field("overtime_details");
			if (!message.length) {
				frappe.show_alert({ message: __("No eligible Attendance records found."), indicator: "orange" });
			}
		},
	});
}
