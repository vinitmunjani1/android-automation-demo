# LinkedIn ID → MockIn ID migration report

Source workbook: `/root/.openclaw/media/inbound/1429f32e-382d-4156-be92-f306d3a352d8.xlsx`

Generated files:
- `migrations/linkedin_id_migration_mockin_mapping.xlsx`
- `migrations/linkedin_id_migration_mockin_mapping.csv`

## Summary

- Input rows: 301
- Rows with MockIn replacement in `resource_id`: 300
- Rows with no MockIn equivalent: 1
- Confidence counts: {'medium': 72, 'high': 227, 'low': 1, 'none': 1}

## Runtime/code compatibility note

The automation already referenced `com.mockin.app:id/home_button`, but the native MockIn Home nav view did not assign that ID. This branch assigns `R.id.home_button` to the Home nav item in `MainActivity.java`.

## Rows with no MockIn equivalent

- Excel row 73: `tab_jobs` — Bottom navigation: jobs tab — No Jobs equivalent exists in MockIn app.
