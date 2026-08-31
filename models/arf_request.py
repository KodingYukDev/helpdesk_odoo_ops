# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class ITAccessRequest(models.Model):
    _name = 'it.arf.request'
    _description = 'IT Access Request Form (ARF)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'

    name = fields.Char(
        string='Nomor ARF', required=True, copy=False, readonly=True,
        default=lambda self: _('New'), tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Pemohon', required=True, tracking=True,
        default=lambda self: self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)], limit=1
        ),
    )
    department_id = fields.Many2one(
        'hr.department', string='Departemen', required=True, tracking=True,
    )
    dept_manager_id = fields.Many2one(
        'hr.employee', string='Department Manager', tracking=True,
    )
    it_manager_id = fields.Many2one(
        'hr.employee', string='IT Manager', tracking=True,
    )
    request_date = fields.Date(
        string='Tanggal Pengajuan', required=True,
        default=fields.Date.context_today, tracking=True,
    )
    access_category = fields.Selection([
        ('application', 'System / Application'),
        ('cloud', 'Cloud Service'),
        ('network', 'Network / VPN'),
        ('database', 'Database'),
        ('physical', 'Physical Access'),
        ('other', 'Lainnya'),
    ], string='Kategori Akses', required=True, tracking=True)
    system_requested = fields.Char(
        string='Sistem / Aplikasi', required=True, tracking=True,
    )
    access_level = fields.Selection([
        ('read', 'Read Only'),
        ('write', 'Read / Write'),
        ('admin', 'Administrator'),
        ('custom', 'Custom'),
    ], string='Level Akses', required=True, default='read', tracking=True)
    access_duration = fields.Selection([
        ('permanent', 'Permanent'),
        ('temporary', 'Temporary'),
    ], string='Durasi', required=True, default='permanent', tracking=True)
    access_end_date = fields.Date(string='Berlaku Sampai', tracking=True)
    justification = fields.Text(string='Justifikasi Bisnis', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('dept_review', 'Department Review'),
        ('it_review', 'IT Review'),
        ('approved', 'Approved'),
        ('implemented', 'Implemented'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)
    dept_approval_date = fields.Datetime(string='Dept Approval Date', readonly=True, copy=False)
    it_approval_date = fields.Datetime(string='IT Approval Date', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Alasan Penolakan', copy=False, tracking=True)
    implemented_by = fields.Many2one('hr.employee', string='Diimplementasikan Oleh', tracking=True)
    implemented_date = fields.Date(string='Tanggal Implementasi', readonly=True, copy=False)
    implementation_notes = fields.Text(string='Catatan Implementasi')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for record in self:
            record.department_id = record.employee_id.department_id
            record.dept_manager_id = record.employee_id.department_id.manager_id

    @api.constrains('access_duration', 'access_end_date', 'request_date')
    def _check_temporary_end_date(self):
        for record in self:
            if record.access_duration == 'temporary' and not record.access_end_date:
                raise ValidationError(_('Tanggal berakhir wajib diisi untuk akses temporary.'))
            if record.access_end_date and record.access_end_date < record.request_date:
                raise ValidationError(_('Tanggal berakhir tidak boleh sebelum tanggal pengajuan.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            employee = self.env['hr.employee'].browse(vals.get('employee_id')) if vals.get('employee_id') else self.env['hr.employee'].search(
                [('user_id', '=', self.env.user.id)], limit=1
            )
            if not employee:
                raise UserError(_('User Anda belum terhubung ke data karyawan.'))
            if not employee.department_id:
                raise UserError(_('Karyawan %s belum memiliki departemen.') % employee.display_name)
            if not self._is_it_staff() and employee.user_id != self.env.user:
                raise AccessError(_('Anda hanya dapat membuat ARF untuk diri sendiri.'))
            vals.update({
                'employee_id': employee.id,
                'department_id': employee.department_id.id,
                'dept_manager_id': employee.department_id.manager_id.id,
            })
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('it.arf.request') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if 'state' in vals and not self.env.context.get('it_workflow_action'):
            raise AccessError(_('Status ARF hanya dapat diubah melalui tombol workflow.'))
        protected = {
            'employee_id', 'department_id', 'dept_manager_id', 'request_date',
            'access_category', 'system_requested', 'access_level',
            'access_duration', 'access_end_date', 'justification',
        }
        if protected.intersection(vals) and any(record.state != 'draft' for record in self) and not self._is_it_staff():
            raise AccessError(_('Detail permintaan tidak dapat diubah setelah ARF diajukan.'))
        if 'employee_id' in vals:
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            if not self._is_it_staff() and employee.user_id != self.env.user:
                raise AccessError(_('Anda hanya dapat mengubah ARF milik sendiri.'))
            vals.update({
                'department_id': employee.department_id.id,
                'dept_manager_id': employee.department_id.manager_id.id,
            })
        elif not self._is_it_staff():
            # Department and approver always follow the employee master data.
            vals.pop('department_id', None)
            vals.pop('dept_manager_id', None)
        return super().write(vals)

    def unlink(self):
        if any(record.state != 'draft' for record in self):
            raise UserError(_('Hanya ARF berstatus Draft yang dapat dihapus.'))
        return super().unlink()

    def _is_it_manager(self):
        return self.env.user.has_group('kodingyuk_helpdesk.group_helpdesk_manager')

    def _is_it_staff(self):
        return self.env.user.has_group('kodingyuk_helpdesk.group_helpdesk_staff')

    def _is_department_manager(self):
        self.ensure_one()
        return bool(self.dept_manager_id.user_id == self.env.user or self._is_it_manager())

    def _schedule_for_user(self, user, summary):
        if user:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=summary)

    def action_submit(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Hanya ARF Draft yang dapat diajukan.'))
            if not record.dept_manager_id or not record.dept_manager_id.user_id:
                raise UserError(_('Department Manager belum memiliki akun Odoo.'))
            record.with_context(it_workflow_action=True).write({'state': 'dept_review', 'rejection_reason': False})
            record._schedule_for_user(record.dept_manager_id.user_id, _('Review ARF %s') % record.name)
        return True

    def action_dept_approve(self):
        for record in self:
            if record.state != 'dept_review':
                raise UserError(_('ARF tidak sedang menunggu review departemen.'))
            if not record._is_department_manager():
                raise AccessError(_('Hanya Department Manager terkait yang dapat menyetujui ARF ini.'))
            if not record.it_manager_id or not record.it_manager_id.user_id:
                raise UserError(_('Pilih IT Manager yang memiliki akun Odoo.'))
            record.with_context(it_workflow_action=True).write({'state': 'it_review', 'dept_approval_date': fields.Datetime.now()})
            record.activity_ids.filtered(lambda a: a.user_id == self.env.user).action_done()
            record._schedule_for_user(record.it_manager_id.user_id, _('Review IT untuk ARF %s') % record.name)
        return True

    def action_it_approve(self):
        if not self._is_it_manager():
            raise AccessError(_('Hanya IT Manager yang dapat memberikan persetujuan IT.'))
        for record in self:
            if record.state != 'it_review':
                raise UserError(_('ARF tidak sedang menunggu review IT.'))
            record.with_context(it_workflow_action=True).write({'state': 'approved', 'it_approval_date': fields.Datetime.now()})
            record.activity_ids.filtered(lambda a: a.user_id == self.env.user).action_done()
        return True

    def action_reject(self):
        for record in self:
            allowed = (
                record.state == 'dept_review' and record._is_department_manager()
            ) or (record.state == 'it_review' and record._is_it_manager())
            if not allowed:
                raise AccessError(_('Anda tidak berhak menolak ARF pada tahap ini.'))
            if not record.rejection_reason:
                raise UserError(_('Isi alasan penolakan terlebih dahulu.'))
            record.with_context(it_workflow_action=True).write({'state': 'rejected'})
            record.activity_ids.filtered(lambda a: a.user_id == self.env.user).action_done()
        return True

    def action_implement(self):
        if not self._is_it_staff():
            raise AccessError(_('Hanya IT Staff yang dapat menyelesaikan implementasi.'))
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)
        for record in self:
            if record.state != 'approved':
                raise UserError(_('ARF harus Approved sebelum diimplementasikan.'))
            record.with_context(it_workflow_action=True).write({
                'state': 'implemented',
                'implemented_by': record.implemented_by.id or employee.id,
                'implemented_date': fields.Date.context_today(record),
            })
        return True

    def action_withdraw(self):
        for record in self:
            if record.state not in ('draft', 'dept_review'):
                raise UserError(_('ARF hanya dapat ditarik saat Draft atau Department Review.'))
            if record.employee_id.user_id != self.env.user and not record._is_it_manager():
                raise AccessError(_('Hanya pemohon yang dapat menarik ARF ini.'))
            record.with_context(it_workflow_action=True).write({'state': 'withdrawn'})
        return True

    @api.model
    def _cron_remind_pending_approvals(self):
        deadline = fields.Datetime.subtract(fields.Datetime.now(), days=3)
        pending = self.search([
            ('state', 'in', ('dept_review', 'it_review')),
            ('write_date', '<=', deadline),
        ])
        for record in pending:
            user = record.dept_manager_id.user_id if record.state == 'dept_review' else record.it_manager_id.user_id
            existing = record.activity_ids.filtered(
                lambda activity: activity.user_id == user and not activity.date_done
            )
            if user and not existing:
                record._schedule_for_user(user, _('Reminder approval ARF %s') % record.name)
