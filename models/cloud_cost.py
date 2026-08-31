# -*- coding: utf-8 -*-
import hashlib
import json
import logging
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

_BIGQUERY_TABLE_RE = re.compile(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_$*-]+$')


class ITCloudAccount(models.Model):
    _name = 'it.cloud.account'
    _description = 'IT Cloud Billing Account'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'provider, name'

    name = fields.Char(required=True, tracking=True)
    provider = fields.Selection([
        ('aws', 'Amazon Web Services'),
        ('gcp', 'Google Cloud Platform'),
    ], required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    sync_days = fields.Integer(
        string='Hari yang Disinkronkan', default=14, required=True,
        help='Data beberapa hari terakhir diambil ulang agar credit dan adjustment ikut diperbarui.',
    )
    initial_sync_days = fields.Integer(
        string='Hari Initial Sync', default=366, required=True,
        help='Rentang histori yang diambil pada sinkronisasi pertama agar angka YTD tersedia.',
    )
    last_sync_at = fields.Datetime(string='Sinkronisasi Terakhir', readonly=True, copy=False)
    last_sync_status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
    ], string='Status Sync', readonly=True, copy=False)
    last_sync_message = fields.Text(string='Pesan Sync', readonly=True, copy=False)

    # AWS uses boto3's default credential chain. No secret is stored in Odoo.
    aws_region = fields.Char(default='us-east-1')
    aws_profile = fields.Char(
        string='AWS Profile',
        help='Opsional. Kosongkan untuk memakai IAM role / environment credential server Odoo.',
    )
    aws_role_arn = fields.Char(
        string='Role ARN',
        help='Opsional. Role read-only yang akan di-assume sebelum membaca Cost Explorer.',
    )
    aws_external_id = fields.Char(string='External ID', groups='kodingyuk_helpdesk.group_helpdesk_manager')

    # GCP uses Application Default Credentials or a server-side JSON path.
    gcp_billing_table = fields.Char(
        string='BigQuery Billing Table',
        help='Format: project_id.dataset_id.gcp_billing_export_v1_xxxxxx',
    )
    gcp_credentials_path = fields.Char(
        string='Service Account JSON Path',
        help='Opsional. Path di server Odoo; kosongkan untuk Application Default Credentials.',
        groups='kodingyuk_helpdesk.group_helpdesk_manager',
    )

    cost_line_ids = fields.One2many('it.cloud.cost', 'account_id', string='Cost Lines')
    cost_line_count = fields.Integer(compute='_compute_cost_line_count')

    @api.depends('cost_line_ids')
    def _compute_cost_line_count(self):
        grouped = self.env['it.cloud.cost'].read_group(
            [('account_id', 'in', self.ids)], ['account_id'], ['account_id']
        ) if self.ids else []
        counts = {row['account_id'][0]: row['account_id_count'] for row in grouped}
        for record in self:
            record.cost_line_count = counts.get(record.id, 0)

    @api.constrains('sync_days', 'initial_sync_days')
    def _check_sync_days(self):
        for record in self:
            if not 1 <= record.sync_days <= 366:
                raise ValidationError(_('Hari yang disinkronkan harus antara 1 dan 366.'))
            if not 1 <= record.initial_sync_days <= 1095:
                raise ValidationError(_('Hari initial sync harus antara 1 dan 1095.'))

    @api.constrains('provider', 'gcp_billing_table')
    def _check_provider_config(self):
        for record in self:
            if record.provider == 'gcp':
                if not record.gcp_billing_table:
                    raise ValidationError(_('BigQuery Billing Table wajib diisi untuk GCP.'))
                if not _BIGQUERY_TABLE_RE.match(record.gcp_billing_table):
                    raise ValidationError(_('Format BigQuery Billing Table tidak valid.'))

    def action_open_cost_lines(self):
        self.ensure_one()
        action = self.env.ref('kodingyuk_helpdesk.action_it_cloud_cost').read()[0]
        action['domain'] = [('account_id', '=', self.id)]
        action['context'] = {'default_account_id': self.id}
        return action

    def action_sync_costs(self):
        for record in self:
            try:
                count = record._sync_costs()
                record.write({
                    'last_sync_at': fields.Datetime.now(),
                    'last_sync_status': 'success',
                    'last_sync_message': _('%s baris biaya diperbarui.') % count,
                })
            except Exception as error:
                _logger.exception('Cloud cost sync failed for account %s', record.display_name)
                record.write({
                    'last_sync_at': fields.Datetime.now(),
                    'last_sync_status': 'error',
                    'last_sync_message': str(error),
                })
                if len(self) == 1:
                    raise UserError(_('Sinkronisasi gagal: %s') % error) from error
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cloud cost'),
                'message': _('Sinkronisasi selesai.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def _sync_costs(self):
        self.ensure_one()
        end_date = fields.Date.context_today(self) + timedelta(days=1)
        lookback_days = self.sync_days if self.last_sync_at else self.initial_sync_days
        start_date = end_date - timedelta(days=lookback_days)
        if self.provider == 'aws':
            rows = self._fetch_aws_costs(start_date, end_date)
        else:
            rows = self._fetch_gcp_costs(start_date, end_date)
        return self._upsert_cost_rows(rows)

    def _fetch_aws_costs(self, start_date, end_date):
        try:
            import boto3
        except ImportError as error:
            raise UserError(_('Python package boto3 belum terpasang di server Odoo.')) from error

        session_kwargs = {}
        if self.aws_profile:
            session_kwargs['profile_name'] = self.aws_profile
        session = boto3.Session(**session_kwargs)
        client_kwargs = {'region_name': self.aws_region or 'us-east-1'}

        if self.aws_role_arn:
            sts = session.client('sts', **client_kwargs)
            assume_kwargs = {
                'RoleArn': self.aws_role_arn,
                'RoleSessionName': 'odoo-it-cloud-cost',
            }
            if self.aws_external_id:
                assume_kwargs['ExternalId'] = self.aws_external_id
            credentials = sts.assume_role(**assume_kwargs)['Credentials']
            client_kwargs.update({
                'aws_access_key_id': credentials['AccessKeyId'],
                'aws_secret_access_key': credentials['SecretAccessKey'],
                'aws_session_token': credentials['SessionToken'],
            })

        client = session.client('ce', **client_kwargs)
        request = {
            'TimePeriod': {'Start': str(start_date), 'End': str(end_date)},
            'Granularity': 'DAILY',
            'Metrics': ['UnblendedCost'],
            'GroupBy': [
                {'Type': 'DIMENSION', 'Key': 'SERVICE'},
                {'Type': 'DIMENSION', 'Key': 'LINKED_ACCOUNT'},
            ],
        }
        rows = []
        while True:
            response = client.get_cost_and_usage(**request)
            for period in response.get('ResultsByTime', []):
                usage_date = period['TimePeriod']['Start']
                for group in period.get('Groups', []):
                    keys = group.get('Keys', [])
                    amount = group.get('Metrics', {}).get('UnblendedCost', {})
                    rows.append({
                        'usage_date': usage_date,
                        'service': keys[0] if keys else _('Unknown'),
                        'cloud_project': keys[1] if len(keys) > 1 else '',
                        'region': '',
                        'cost': float(amount.get('Amount', 0.0)),
                        'currency': amount.get('Unit') or 'USD',
                    })
            token = response.get('NextPageToken')
            if not token:
                break
            request['NextPageToken'] = token
        return rows

    def _fetch_gcp_costs(self, start_date, end_date):
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account
        except ImportError as error:
            raise UserError(
                _('Python package google-cloud-bigquery dan google-auth belum terpasang di server Odoo.')
            ) from error

        credentials = None
        if self.gcp_credentials_path:
            credentials = service_account.Credentials.from_service_account_file(
                self.gcp_credentials_path,
                scopes=['https://www.googleapis.com/auth/bigquery'],
            )
        project_id = self.gcp_billing_table.split('.', 1)[0]
        client = bigquery.Client(project=project_id, credentials=credentials)
        query = f'''
            SELECT
                DATE(usage_start_time) AS usage_date,
                service.description AS service,
                COALESCE(project.id, '') AS cloud_project,
                COALESCE(location.region, location.location, '') AS region,
                SUM(cost + COALESCE((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS cost,
                currency
            FROM `{self.gcp_billing_table}`
            WHERE DATE(usage_start_time) >= @start_date
              AND DATE(usage_start_time) < @end_date
            GROUP BY usage_date, service, cloud_project, region, currency
        '''
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter('start_date', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
        ])
        return [{
            'usage_date': str(row.usage_date),
            'service': row.service or _('Unknown'),
            'cloud_project': row.cloud_project or '',
            'region': row.region or '',
            'cost': float(row.cost or 0.0),
            'currency': row.currency or 'USD',
        } for row in client.query(query, job_config=job_config).result()]

    def _upsert_cost_rows(self, rows):
        Cost = self.env['it.cloud.cost'].sudo()
        for row in rows:
            key_source = '|'.join([
                str(self.id), str(row['usage_date']), row['service'],
                row.get('cloud_project', ''), row.get('region', ''), row['currency'],
            ])
            unique_key = hashlib.sha256(key_source.encode('utf-8')).hexdigest()
            values = dict(row, account_id=self.id, provider=self.provider, unique_key=unique_key)
            existing = Cost.search([('unique_key', '=', unique_key)], limit=1)
            if existing:
                existing.write(values)
            else:
                Cost.create(values)
        return len(rows)

    @api.model
    def _cron_sync_cloud_costs(self):
        for account in self.search([('active', '=', True)]):
            try:
                account.action_sync_costs()
            except Exception:
                # action_sync_costs records the error; one broken account must not block others.
                _logger.exception('Scheduled cloud cost sync failed for %s', account.display_name)


class ITCloudCost(models.Model):
    _name = 'it.cloud.cost'
    _description = 'IT Cloud Cost'
    _order = 'usage_date desc, cost desc, id desc'

    account_id = fields.Many2one('it.cloud.account', required=True, ondelete='cascade', index=True)
    provider = fields.Selection([
        ('aws', 'AWS'),
        ('gcp', 'GCP'),
    ], required=True, index=True)
    usage_date = fields.Date(required=True, index=True)
    service = fields.Char(required=True, index=True)
    cloud_project = fields.Char(string='Account / Project', index=True)
    region = fields.Char(index=True)
    cost = fields.Float(digits=(16, 6), required=True)
    currency = fields.Char(required=True, default='USD', index=True)
    unique_key = fields.Char(required=True, copy=False, index=True)
    metadata_json = fields.Text(string='Metadata JSON')

    _sql_constraints = [
        ('it_cloud_cost_unique_key', 'unique(unique_key)', 'Cloud cost line already exists.'),
    ]

    @api.constrains('metadata_json')
    def _check_metadata_json(self):
        for record in self.filtered('metadata_json'):
            try:
                json.loads(record.metadata_json)
            except (TypeError, ValueError) as error:
                raise ValidationError(_('Metadata harus berupa JSON yang valid.')) from error
