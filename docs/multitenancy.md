# Multi-Tenant Architecture

This project supports multiple Sekolah Rakyat tenants. Every operational record belongs to a school through `school_id`.

## Tenant Source

The authenticated user is the source of tenant ownership.

- JWT stores `user_id`, `username`, `role`, and `school_id`.
- API handlers must not accept `school_id` from regular client requests.
- `super_admin` bypasses tenant filtering for national-level access.

## Roles

- `super_admin`: all schools, school management, national data, all users.
- `admin` / `perawat`: full access within their own school, including user management.
- `kepala_sekolah`: dashboard, students, visits, reports, and CKG visibility.
- `tim_uksr`: dashboard, students, visits, and station workflows.
- `wali_asuh`: limited student/profile visibility and settings.

## Tenant Helpers

Reusable tenant helpers live in `app/auth/tenant.py`.

- `tenant_query(query, model, user)` filters by `model.school_id == user.school_id`.
- `tenant_get(db, model, object_id, user)` returns an object only if it belongs to the user's school.
- `is_super_admin(user)` bypasses filtering for national access.

## Database Migration

Alembic migration `20260725_0001_multitenant_schools.py` creates:

- `schools`
- `school_id` columns on operational tables
- `school_id` indexes
- foreign keys to `schools` on PostgreSQL
- default school `SR-DEMO / Sekolah Rakyat Demo`
- backfill of existing rows to the default school

The application startup still contains compatibility migration logic for existing deployments.

Recommended production migration:

```powershell
pip install -r requirements.txt
alembic upgrade head
```

## Security Rules

All GET, PUT, DELETE, PDF, Excel, AI, WhatsApp, dashboard, report, and backup/restore operations should use `tenant_query` or `tenant_get` unless the endpoint is explicitly `super_admin` only.

Do not add new operational endpoints that query tables directly without tenant ownership checks.
