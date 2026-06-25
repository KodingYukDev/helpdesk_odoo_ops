# Helpdesk System — Odoo Module

> Sistem ticketing internal KodingYuk dengan dukungan lampiran Firebase Storage dan REST API.

**Platform:** Odoo 17  
**Departemen:** Ops  
**Repo:** `helpdesk_odoo_ops`  
**Status:** ![Status](https://img.shields.io/badge/status-active-brightgreen)

---

## Deskripsi

Modul helpdesk internal untuk pengelolaan tiket dukungan antar staff. User submit tiket via portal atau form, tim IT/Ops merespons dan mengelola status tiket. Lampiran file disimpan di Firebase Storage. Terdapat REST API untuk integrasi dengan frontend eksternal (helpdesk-dashboard).

**User utama:** Staff internal, Admin, Tim IT/Ops

---

## Model Odoo

| Model | Label | Keterangan |
|---|---|---|
| `ky.ticket` | KY Ticket | Tiket utama helpdesk |
| `kodingyuk.helpdesk.ticket` | Helpdesk Ticket | Alias/inherit tiket |

---

## Fitur Utama

- **Ticketing:** Buat, track, dan kelola tiket helpdesk
- **Firebase Attachment:** Upload lampiran langsung ke Firebase Storage
- **Mail Templates:** Notifikasi email otomatis saat status tiket berubah
- **REST API:** Endpoint `/api/helpdesk/*` untuk integrasi frontend
- **Password Generator:** Wizard bantu generate password untuk user baru

---

## Struktur Folder

```
kodingyuk_helpdesk/
├── __manifest__.py
├── __init__.py
├── controllers/
│   ├── __init__.py
│   └── api.py              # REST API endpoints
├── models/
│   └── helpdesk_ticket.py
├── views/
│   └── helpdesk_ticket_views.xml
├── wizard/
│   ├── upload_wizard_view.xml
│   └── password_generator_wizard_view.xml
├── security/
│   ├── security_groups.xml
│   └── ir.model.access.csv
├── data/
│   ├── helpdesk_data.xml
│   └── mail_template_data.xml
└── reset_template_noupdate.sql
```

---

## Instalasi

1. Clone ke folder `addons` Odoo:
   ```bash
   git clone https://github.com/kodingyuk/helpdesk_odoo_ops.git
   ```

2. Tambahkan path ke `odoo.conf`, restart Odoo, install dari **Apps > KodingYuk Helpdesk**

---

## Dependencies

- `base`, `mail`, `hr`
- Firebase Storage (konfigurasi via Settings)

---

## Changelog

| Versi | Tanggal | Perubahan |
|---|---|---|
| 17.0.1.1.0 | 2026-06 | Tambah REST API controller, update mail templates |
| 17.0.1.0.0 | — | Initial release |

---

## Maintainer

**Tim:** Technology & RnD — KodingYuk  
**Kontak:** support@kodingyuk.id
