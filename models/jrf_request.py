# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class ITJoinerRequest(models.Model):
    _name = 'it.jrf.request'
    _description = 'IT Joiner Request Form (JRF)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    name = fields.Char(
        string='Nomor JRF', required=True, copy=False, readonly=True,
        default=lambda self: _('New'), tracking=True,
    )
    requester_id = fields.Many2one(
        'res.users', string='Diajukan Oleh', required=True,
        default=lambda self: self.env.user, tracking=True,
    )
    employee_name = fields.Char(string='Nama Joiner', required=True, tracking=True)
    personal_email = fields.Char(string='Email Personal')
    department_id = fields.Many2one('hr.department', string='Departemen', required=True, tracking=True)
    manager_id = fields.Many2one('hr.employee', string='Manager', tracking=True)
    job_title = fields.Char(string='Jabatan', required=True, tracking=True)
    employment_type = fields.Selection([
        ('permanent', 'Permanent'),
        ('contract', 'Contract'),
        ('intern', 'Intern'),
        ('freelance', 'Freelance'),
    ], string='Tipe Kepegawaian', required=True, default='permanent')
    start_date = fields.Date(string='Tanggal Mulai', required=True, tracking=True)
    needs_odoo = fields.Boolean(string='Akun Odoo', default=True)
    needs_google = fields.Boolean(string='Google Workspace', default=True)
    needs_vpn = fields.Boolean(string='VPN')
    needs_laptop = fields.Boolean(string='Laptop / Perangkat')
    requested_systems = fields.Text(string='Aplikasi / Akses Tambahan')
    notes = fields.Text(string='Catatan')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('in_progress', 'IT Preparation'),
        ('ready', 'Ready'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)
    assigned_to = fields.Many2one('hr.employee', string='IT PIC', tracking=True)
    completed_date = fields.Date(string='Tanggal Selesai', readonly=True, copy=False)
    completion_notes = fields.Text(string='Catatan Penyelesaian')

    @api.onchange('department_id')
    def _onchange_department_id(self):
        for record in self:
            record.manager_id = record.department_id.manager_id

    @api.constrains('start_date')
    def _check_start_date(self):
        for record in self:
            if record.start_date and record.start_date < fields.Date.context_today(record) and record.state == 'draft':
                raise ValidationError(_('Tanggal mulai tidak boleh berada di masa lalu saat membuat JRF.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.user.has_group('kodingyuk_helpdesk.group_helpdesk_staff'):
                vals['requester_id'] = self.env.user.id
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('it.jrf.request') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if 'state' in vals and not self.env.context.get('it_workflow_action'):
            raise AccessError(_('Status JRF hanya dapat diubah melalui tombol workflow.'))
        protected = {
            'employee_name', 'personal_email', 'department_id', 'manager_id',
            'job_title', 'employment_type', 'start_date', 'needs_odoo',
            'needs_google', 'needs_vpn', 'needs_laptop', 'requested_systems', 'notes',
        }
        if protected.intersection(vals) and any(record.state != 'draft' for record in self):
            if not self.env.user.has_group('kodingyuk_helpdesk.group_helpdesk_staff'):
                raise AccessError(_('Detail joiner tidak dapat diubah setelah JRF diajukan.'))
        if 'requester_id' in vals and not self.env.user.has_group('kodingyuk_helpdesk.group_helpdesk_staff'):
            vals['requester_id'] = self.env.user.id
        return super().write(vals)

    def unlink(self):
        if any(record.state != 'draft' for record in self):
            raise UserError(_('Hanya JRF berstatus Draft yang dapat dihapus.'))
        return super().unlink()

    def _require_it_staff(self):
        if not self.env.user.has_group('kodingyuk_helpdesk.group_helpdesk_staff'):
            raise AccessError(_('Aksi ini hanya dapat dilakukan IT Staff.'))

    def action_submit(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Hanya JRF Draft yang dapat diajukan.'))
            record.with_context(it_workflow_action=True).write({'state': 'submitted'})
        return True

    def action_start(self):
        self._require_it_staff()
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)
        for record in self:
            if record.state != 'submitted':
                raise UserError(_('JRF harus Submitted sebelum mulai diproses.'))
            record.with_context(it_workflow_action=True).write({
                'state': 'in_progress', 'assigned_to': record.assigned_to.id or employee.id,
            })
        return True

    def action_ready(self):
        self._require_it_staff()
        for record in self:
            if record.state != 'in_progress':
                raise UserError(_('JRF harus dalam IT Preparation.'))
            record.with_context(it_workflow_action=True).write({'state': 'ready'})
        return True

    def action_complete(self):
        self._require_it_staff()
        for record in self:
            if record.state != 'ready':
                raise UserError(_('JRF harus Ready sebelum diselesaikan.'))
            record.with_context(it_workflow_action=True).write({
                'state': 'completed',
                'completed_date': fields.Date.context_today(record),
            })
        return True

    def action_cancel(self):
        for record in self:
            if record.requester_id != self.env.user and not self.env.user.has_group(
                'kodingyuk_helpdesk.group_helpdesk_manager'
            ):
                raise AccessError(_('Hanya pengaju atau IT Manager yang dapat membatalkan JRF.'))
            if record.state == 'completed':
                raise UserError(_('JRF yang sudah Completed tidak dapat dibatalkan.'))
            record.with_context(it_workflow_action=True).write({'state': 'cancelled'})
        return True
