-- Activities (interventions) per municipality, shown on the public activities page next to the vulnerable areas of
-- the ENVI and the other maps. Entered by staff by hand or imported from Excel.

create table if not exists activities (
  id uuid primary key default gen_random_uuid(),
  area_key text not null references gazetteer (area_key),
  title text not null,
  category text,
  status text not null default 'to_conduct'
    check (status in ('to_conduct', 'ongoing', 'completed', 'postponed')),
  hazard text not null default 'general'                -- the map it responds to; 'general' = every map
    check (hazard in ('general', 'envi', 'drought', 'rainfall_dekad', 'rainfall_seasonal')),
  start_date date,
  end_date date,
  beneficiaries integer check (beneficiaries >= 0),     -- farmers reached
  budget numeric check (budget >= 0),                   -- PHP
  office text,                                          -- implementing office / unit
  remarks text,
  source text,                                          -- 'manual' or the imported file name
  created_by uuid references profiles on delete set null,
  created_by_email text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (end_date is null or start_date is null or end_date >= start_date)
);
create index if not exists activities_area_idx on activities (area_key);

alter table activities enable row level security;
drop policy if exists "public read" on activities;
create policy "public read" on activities for select using (true);
drop policy if exists "staff write" on activities;
create policy "staff write" on activities for all using (current_role_is('editor')) with check (current_role_is('editor'));
