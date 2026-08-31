/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class KodingYukITDashboard extends Component {
    static template = "kodingyuk_helpdesk.ITDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ loading: true, data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("it.dashboard", "get_dashboard_data", []);
        } catch (error) {
            this.notification.add(error.message || "Dashboard IT gagal dimuat.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    formatMoney(amount, currency) {
        try {
            return new Intl.NumberFormat("id-ID", {
                style: "currency",
                currency: currency || "USD",
                maximumFractionDigits: 2,
            }).format(amount || 0);
        } catch {
            return `${currency || ""} ${Number(amount || 0).toLocaleString("id-ID")}`.trim();
        }
    }

    formatCostMap(values) {
        const entries = Object.entries(values || {});
        return entries.length
            ? entries.map(([currency, amount]) => this.formatMoney(amount, currency)).join(" · ")
            : this.formatMoney(0, "USD");
    }

    openHelpdesk() {
        this.action.doAction("kodingyuk_helpdesk.action_helpdesk_ticket");
    }

    openARF() {
        this.action.doAction("kodingyuk_helpdesk.action_it_arf_request");
    }

    openJRF() {
        this.action.doAction("kodingyuk_helpdesk.action_it_jrf_request");
    }

    openCosts() {
        this.action.doAction("kodingyuk_helpdesk.action_it_cloud_cost");
    }
}

registry.category("actions").add("kodingyuk_it.dashboard", KodingYukITDashboard);
