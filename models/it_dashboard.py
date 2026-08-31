# -*- coding: utf-8 -*-
from collections import defaultdict
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError


class ITDashboard(models.AbstractModel):
    _name = 'it.dashboard'
    _description = 'KodingYuk IT Dashboard Service'

    @api.model
    def get_dashboard_data(self):
        if not self.env.user.has_group('kodingyuk_helpdesk.group_helpdesk_staff'):
            raise AccessError('Dashboard IT hanya dapat diakses IT Staff.')

        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        ticket_states = self._state_counts('kodingyuk.helpdesk.ticket', [
            ('new', 'New'), ('in_progress', 'In Progress'),
            ('solved', 'Solved'), ('cancelled', 'Cancelled'),
        ])
        arf_states = self._state_counts('it.arf.request', [
            ('draft', 'Draft'), ('dept_review', 'Dept Review'), ('it_review', 'IT Review'),
            ('approved', 'Approved'), ('implemented', 'Implemented'),
            ('rejected', 'Rejected'), ('withdrawn', 'Withdrawn'),
        ])
        jrf_states = self._state_counts('it.jrf.request', [
            ('draft', 'Draft'), ('submitted', 'Submitted'), ('in_progress', 'IT Preparation'),
            ('ready', 'Ready'), ('completed', 'Completed'), ('cancelled', 'Cancelled'),
        ])

        Cost = self.env['it.cloud.cost']
        mtd = self._cost_totals(Cost, [('usage_date', '>=', month_start)])
        ytd = self._cost_totals(Cost, [('usage_date', '>=', year_start)])
        provider_totals = self._provider_totals(Cost, month_start)
        primary_currency = next(iter(mtd), next(iter(ytd), 'USD'))
        top_services = self._top_services(Cost, month_start, primary_currency)
        cost_trend = self._cost_trend(Cost, today, primary_currency)

        return {
            'generated_at': fields.Datetime.now(),
            'headline': {
                'open_tickets': self.env['kodingyuk.helpdesk.ticket'].search_count([
                    ('state', 'in', ('new', 'in_progress'))
                ]),
                'pending_arf': self.env['it.arf.request'].search_count([
                    ('state', 'in', ('dept_review', 'it_review', 'approved'))
                ]),
                'active_jrf': self.env['it.jrf.request'].search_count([
                    ('state', 'in', ('submitted', 'in_progress', 'ready'))
                ]),
                'cloud_accounts': self.env['it.cloud.account'].search_count([('active', '=', True)]),
            },
            'ticket_states': ticket_states,
            'arf_states': arf_states,
            'jrf_states': jrf_states,
            'cost': {
                'mtd': mtd,
                'ytd': ytd,
                'primary_currency': primary_currency,
                'provider_mtd': provider_totals,
                'top_services_mtd': top_services,
                'trend': cost_trend,
            },
        }

    def _state_counts(self, model_name, states):
        Model = self.env[model_name]
        rows = []
        total = Model.search_count([])
        for value, label in states:
            count = Model.search_count([('state', '=', value)])
            rows.append({
                'key': value,
                'label': label,
                'count': count,
                'percent': round((count / total) * 100, 1) if total else 0,
            })
        return {'total': total, 'items': rows}

    def _cost_totals(self, Cost, domain):
        rows = Cost.read_group(domain, ['cost:sum', 'currency'], ['currency'], lazy=False)
        return {row['currency']: round(row['cost'], 2) for row in rows}

    def _provider_totals(self, Cost, start_date):
        rows = Cost.read_group(
            [('usage_date', '>=', start_date)],
            ['cost:sum', 'provider', 'currency'], ['provider', 'currency'], lazy=False,
        )
        return [{
            'provider': (row.get('provider') or '').upper(),
            'currency': row.get('currency') or 'USD',
            'amount': round(row['cost'], 2),
        } for row in rows]

    def _top_services(self, Cost, start_date, currency):
        rows = Cost.read_group(
            [('usage_date', '>=', start_date), ('currency', '=', currency)],
            ['cost:sum', 'service'], ['service'], lazy=False,
        )
        rows = sorted(rows, key=lambda row: row['cost'], reverse=True)[:6]
        maximum = rows[0]['cost'] if rows else 0
        return [{
            'service': row.get('service') or 'Unknown',
            'amount': round(row['cost'], 2),
            'currency': currency,
            'percent': round((row['cost'] / maximum) * 100, 1) if maximum else 0,
        } for row in rows]

    def _cost_trend(self, Cost, today, currency):
        first_month = today.replace(day=1) - relativedelta(months=5)
        totals = defaultdict(float)
        for row in Cost.search([
            ('usage_date', '>=', first_month), ('currency', '=', currency),
        ]):
            key = row.usage_date.strftime('%Y-%m')
            totals[key] += row.cost
        items = []
        for offset in range(6):
            current = first_month + relativedelta(months=offset)
            key = current.strftime('%Y-%m')
            items.append({
                'key': key,
                'label': current.strftime('%b'),
                'amount': round(totals[key], 2),
            })
        maximum = max((item['amount'] for item in items), default=0)
        for item in items:
            item['percent'] = round((item['amount'] / maximum) * 100, 1) if maximum else 0
        return items
