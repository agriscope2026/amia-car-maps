-- Small app-wide settings, e.g. the automatic Special Farm Weather Outlook and Advisory (tc_auto): on/off and the
-- result of its last run. Read and written by the server only (service role) – no public policies.

create table if not exists app_settings (
  key text primary key,
  value jsonb not null default '{}',
  updated_at timestamptz not null default now()
);

alter table app_settings enable row level security;
