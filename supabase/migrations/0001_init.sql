-- CAR Agri-Climate Portal – initial schema (Supabase Postgres + PostGIS)
-- Times are timestamptz (displayed in Asia/Manila); periods are real dates; every value carries its unit.

create extension if not exists postgis;
create extension if not exists pgcrypto;

-- ------------------------------------------------------------------ roles ---
create type app_role as enum ('editor', 'admin');
create type product_type as enum ('envi', 'rainfall_dekad', 'rainfall_seasonal', 'drought');
create type product_status as enum ('draft', 'published', 'archived');
create type period_kind as enum ('dekad', 'month', 'season');

create table profiles (
  id uuid primary key references auth.users on delete cascade,
  email text not null,
  full_name text,
  role app_role not null default 'editor',
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create or replace function public.current_role_is(r app_role) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from profiles p where p.id = auth.uid() and p.active
                 and (p.role = r or p.role = 'admin'));
$$;

-- -------------------------------------------------------------- reference ---
create table boundary_versions (
  id serial primary key,
  label text not null,                      -- e.g. 'CAR Regional Map 2024'
  source text,
  is_current boolean not null default false,
  created_at timestamptz not null default now(),
  created_by uuid references profiles
);

create table gazetteer (
  area_key text primary key,                -- 'PROVINCE|MUNICIPALITY' (cleaned names)
  psgc text,                                -- PSGC code (9-digit as supplied; verify 10-digit format)
  province text not null,
  municipality text not null,
  gis_name text not null,                   -- Mun_Name in the shapefile, e.g. 'Bangued (Abra)'
  short_name text,                          -- MunName2
  is_city boolean not null default false,
  aliases text[] not null default '{}'      -- confirmed manual matches, e.g. '{City of Baguio}'
);

create table boundaries (
  id serial primary key,
  version_id int not null references boundary_versions on delete cascade,
  level text not null check (level in ('municipality', 'province', 'region')),
  area_key text not null,
  name text not null,
  geom geometry(MultiPolygon, 4326) not null,
  unique (version_id, level, area_key)
);
create index on boundaries using gist (geom);

create table legends (
  id text primary key,                      -- 'rainfall_dekad', 'rainfall_month', 'pct_normal', …
  product_type product_type,
  definition jsonb not null,                -- {kind, title, unit, closed, classes:[{label, lo, hi, color}]}
  updated_at timestamptz not null default now(),
  updated_by uuid references profiles
);

create table print_templates (
  id serial primary key,
  name text not null,
  product_type product_type,
  storage_path text not null,               -- .qgz / .qpt in the 'templates' bucket
  is_default boolean not null default false,
  created_at timestamptz not null default now()
);

create table crops_tables (
  id serial primary key,
  as_of date not null unique,
  source text,
  crops text[] not null,
  file_path text,
  created_at timestamptz not null default now(),
  created_by uuid references profiles
);

create table crop_values (
  table_id int not null references crops_tables on delete cascade,
  area_key text not null references gazetteer,
  crop text not null,
  area_ha numeric(12, 2) not null check (area_ha >= 0),
  primary key (table_id, area_key, crop)
);

create table irrigation_sources (
  id serial primary key,
  name text not null,
  type text not null check (type in ('NIS', 'CIS', 'SWIP', 'SSIP', 'DAM', 'OTHER')),
  river text,
  municipality text,
  province text,
  service_area_ha numeric(12, 2) check (service_area_ha >= 0),
  status text,
  source text,
  geom geometry(Point, 4326) not null,
  service_area geometry(MultiPolygon, 4326),
  batch_id uuid,                            -- upload batch (replaced as a whole)
  updated_at timestamptz not null default now()
);
create index on irrigation_sources using gist (geom);

-- --------------------------------------------------------------- products ---
create table products (
  id uuid primary key default gen_random_uuid(),
  type product_type not null,
  slug text unique not null,                -- e.g. 'rainfall_dekad-2026-10-01'
  period_kind period_kind not null,
  period_start date not null,
  period_end date not null check (period_end >= period_start),
  issue_date date not null,                 -- "as of"
  current_version int,
  published_version int,
  created_at timestamptz not null default now(),
  created_by uuid references profiles
);
create index on products (type, period_start desc);

create table product_versions (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references products on delete cascade,
  version int not null,
  status product_status not null default 'draft',
  title text not null,
  subtitle text,
  notes text,
  disclaimer text,
  sources text,
  recommendations text,
  recommendations_source text check (recommendations_source in ('auto', 'edited')),
  settings jsonb not null default '{}',     -- weights, legends, manual matches, period labels …
  method jsonb not null default '{}',
  summary jsonb not null default '{}',
  payload jsonb,                            -- dashboard payload (layers, legends, values) – cached
  input_files jsonb not null default '[]',  -- [{dataset, path, filename, sha256}]
  validation jsonb not null default '{}',
  exports jsonb not null default '{}',      -- manifest: {maps:[…], files:{…}, labels_ok}
  label_report jsonb,
  author uuid references profiles,
  created_at timestamptz not null default now(),
  published_at timestamptz,
  published_by uuid references profiles,
  unique (product_id, version)
);

-- one row per municipality × layer (period/variable) – queryable values, with unit
create table product_values (
  version_id uuid not null references product_versions on delete cascade,
  layer_id text not null,                   -- 'total', 'm_2026-10', 'season_total', 'pct_normal', 'envi'
  period_start date,
  period_end date,
  area_key text not null references gazetteer,
  variable text not null,                   -- 'rainfall_mm', 'pct_normal', 'drought_category', 'envi_class'
  value numeric,
  value_text text,
  unit text not null,                       -- 'mm' | '%' | 'category' | 'class' | 'ha'
  class_label text not null,
  class_color text not null,
  extra jsonb,
  primary key (version_id, layer_id, area_key)
);

create table submissions (
  id uuid primary key default gen_random_uuid(),
  product_type product_type not null,
  office text not null,
  contact_name text,
  contact_email text,
  period_start date,
  period_end date,
  files jsonb not null default '[]',
  notes text,
  status text not null default 'new' check (status in ('new', 'reviewed', 'converted', 'rejected')),
  product_id uuid references products,
  client_ip inet,
  created_at timestamptz not null default now()
);

create table audit_log (
  id bigserial primary key,
  at timestamptz not null default now(),
  actor uuid references profiles,
  actor_email text,
  action text not null,                     -- login, upload, validate, edit, export, publish, unpublish, …
  entity text,
  entity_id text,
  details jsonb
);
create index on audit_log (at desc);

create table rate_limits (
  key text primary key,
  window_start timestamptz not null,
  count int not null
);

-- ----------------------------------------------------------- public views ---
-- The public side only ever sees published versions.
create view published_products with (security_invoker = false) as
  select p.id, p.type, p.slug, p.period_kind, p.period_start, p.period_end, p.issue_date,
         v.id as version_id, v.version, v.title, v.subtitle, v.notes, v.disclaimer, v.sources,
         v.recommendations, v.summary, v.method, v.exports, v.published_at
  from products p join product_versions v on v.product_id = p.id and v.version = p.published_version
  where v.status = 'published';

-- ----------------------------------------------------------------- RLS ---
alter table profiles enable row level security;
alter table gazetteer enable row level security;
alter table boundary_versions enable row level security;
alter table boundaries enable row level security;
alter table legends enable row level security;
alter table print_templates enable row level security;
alter table crops_tables enable row level security;
alter table crop_values enable row level security;
alter table irrigation_sources enable row level security;
alter table products enable row level security;
alter table product_versions enable row level security;
alter table product_values enable row level security;
alter table submissions enable row level security;
alter table audit_log enable row level security;
alter table rate_limits enable row level security;

-- reference data: public read, admin write
create policy "public read" on gazetteer for select using (true);
create policy "public read" on boundary_versions for select using (true);
create policy "public read" on boundaries for select using (true);
create policy "public read" on legends for select using (true);
create policy "public read" on crops_tables for select using (true);
create policy "public read" on crop_values for select using (true);
create policy "public read" on irrigation_sources for select using (true);
create policy "admin write" on gazetteer for all using (current_role_is('admin')) with check (current_role_is('admin'));
create policy "admin write" on boundary_versions for all using (current_role_is('admin')) with check (current_role_is('admin'));
create policy "admin write" on boundaries for all using (current_role_is('admin')) with check (current_role_is('admin'));
create policy "admin write" on legends for all using (current_role_is('admin')) with check (current_role_is('admin'));
create policy "admin write" on print_templates for all using (current_role_is('admin')) with check (current_role_is('admin'));
create policy "admin write" on crops_tables for all using (current_role_is('admin')) with check (current_role_is('admin'));
create policy "admin write" on crop_values for all using (current_role_is('admin')) with check (current_role_is('admin'));
create policy "admin write" on irrigation_sources for all using (current_role_is('admin')) with check (current_role_is('admin'));
create policy "staff read" on print_templates for select using (current_role_is('editor'));

-- products: public sees published only; editors work on drafts; publishing is admin-only
create policy "public read published" on products for select using (published_version is not null);
create policy "staff read" on products for select using (current_role_is('editor'));
create policy "staff write" on products for insert with check (current_role_is('editor'));
create policy "staff update" on products for update using (current_role_is('editor'));

create policy "public read published" on product_versions for select using (status = 'published');
create policy "staff read" on product_versions for select using (current_role_is('editor'));
create policy "staff create" on product_versions for insert with check (current_role_is('editor') and status = 'draft');
create policy "staff edit drafts" on product_versions for update
  using (current_role_is('editor') and status = 'draft')
  with check (status = 'draft' or current_role_is('admin'));
create policy "admin publish" on product_versions for update using (current_role_is('admin'));

create policy "public read published" on product_values for select using (
  exists (select 1 from product_versions v where v.id = version_id and v.status = 'published'));
create policy "staff all" on product_values for all using (current_role_is('editor')) with check (current_role_is('editor'));

create policy "self read" on profiles for select using (id = auth.uid() or current_role_is('admin'));
create policy "admin manage" on profiles for all using (current_role_is('admin')) with check (current_role_is('admin'));

create policy "staff read" on submissions for select using (current_role_is('editor'));
create policy "staff update" on submissions for update using (current_role_is('editor'));
-- public inserts go through the server (service role) after access-code check + rate limit

create policy "admin read" on audit_log for select using (current_role_is('admin'));
-- audit rows are written by the server with the service role

-- ------------------------------------------------------- publish function ---
create or replace function publish_version(p_version uuid) returns void
language plpgsql security definer set search_path = public as $$
declare v product_versions;
begin
  if not current_role_is('admin') then raise exception 'Only admins can publish'; end if;
  select * into v from product_versions where id = p_version for update;
  if v.id is null then raise exception 'Version not found'; end if;
  if v.exports = '{}'::jsonb then raise exception 'Generate the exports before publishing'; end if;
  update product_versions set status = 'archived'
    where product_id = v.product_id and status = 'published' and id <> v.id;
  update product_versions set status = 'published', published_at = now(), published_by = auth.uid()
    where id = v.id;
  update products set published_version = v.version where id = v.product_id;
  insert into audit_log (actor, action, entity, entity_id, details)
    values (auth.uid(), 'publish', 'product_version', v.id::text, jsonb_build_object('version', v.version));
end $$;

create or replace function unpublish_product(p_product uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not current_role_is('admin') then raise exception 'Only admins can unpublish'; end if;
  update product_versions set status = 'archived' where product_id = p_product and status = 'published';
  update products set published_version = null where id = p_product;
  insert into audit_log (actor, action, entity, entity_id) values (auth.uid(), 'unpublish', 'product', p_product::text);
end $$;

-- ---------------------------------------------------------------- storage ---
-- buckets: 'uploads' (private: raw input files), 'exports' (private drafts; published files are copied to
-- 'public-exports'), 'templates' (private: .qgz/.qpt, logos)
insert into storage.buckets (id, name, public) values
  ('uploads', 'uploads', false), ('exports', 'exports', false), ('public-exports', 'public-exports', true),
  ('templates', 'templates', false)
on conflict (id) do nothing;

create policy "staff uploads" on storage.objects for all
  using (bucket_id in ('uploads', 'exports', 'templates') and current_role_is('editor'))
  with check (bucket_id in ('uploads', 'exports', 'templates') and current_role_is('editor'));

-- --------------------------------------------------- irrigation (public) ---
create view irrigation_public as
  select jsonb_build_object(
    'type', 'Feature',
    'geometry', st_asgeojson(geom)::jsonb,
    'properties', jsonb_build_object('name', name, 'type', type, 'river', river, 'municipality', municipality,
                                     'province', province, 'service_area_ha', service_area_ha, 'status', status,
                                     'source', source, 'has_service_area', service_area is not null)) as feature
  from irrigation_sources;

create or replace function replace_irrigation_sources(p_features jsonb, p_service_areas jsonb default '[]')
returns int language plpgsql security definer set search_path = public as $$
declare n int; batch uuid := gen_random_uuid();
begin
  -- called by the server (service role) after an admin role check
  delete from irrigation_sources;
  insert into irrigation_sources (name, type, river, municipality, province, service_area_ha, status, source, geom, batch_id)
  select f->'properties'->>'name', coalesce(f->'properties'->>'type', 'OTHER'), f->'properties'->>'river',
         f->'properties'->>'municipality', f->'properties'->>'province',
         nullif(f->'properties'->>'service_area_ha', '')::numeric, f->'properties'->>'status',
         f->'properties'->>'source', st_setsrid(st_geomfromgeojson(f->'geometry'), 4326), batch
  from jsonb_array_elements(p_features) f;
  get diagnostics n = row_count;
  update irrigation_sources s set service_area = st_multi(st_setsrid(st_geomfromgeojson(a->'geometry'), 4326))
  from jsonb_array_elements(p_service_areas) a
  where lower(a->'properties'->>'name') = lower(s.name);
  return n;
end $$;
revoke execute on function replace_irrigation_sources(jsonb, jsonb) from public, anon, authenticated;
