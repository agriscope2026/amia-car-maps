-- Irrigation types are no longer a fixed list: DA's data also has RIVER sources, and new kinds may come.
-- A type is any short code (letters, digits, underscores); its display name is stored in type_label.

alter table irrigation_sources drop constraint if exists irrigation_sources_type_check;
alter table irrigation_sources add constraint irrigation_sources_type_check check (type ~ '^[A-Z0-9_]{1,24}$');
alter table irrigation_sources add column if not exists type_label text;

create or replace view irrigation_public as
  select jsonb_build_object(
    'type', 'Feature',
    'geometry', st_asgeojson(geom)::jsonb,
    'properties', jsonb_build_object('name', name, 'type', type, 'type_label', type_label, 'river', river,
                                     'municipality', municipality, 'province', province,
                                     'service_area_ha', service_area_ha, 'status', status, 'source', source,
                                     'has_service_area', service_area is not null)) as feature
  from irrigation_sources;

create or replace function replace_irrigation_sources(p_features jsonb, p_service_areas jsonb default '[]')
returns int language plpgsql security definer set search_path = public as $$
declare n int; batch uuid := gen_random_uuid();
begin
  -- called by the server (service role) after an admin role check
  delete from irrigation_sources;
  insert into irrigation_sources (name, type, type_label, river, municipality, province, service_area_ha, status,
                                  source, geom, batch_id)
  select f->'properties'->>'name', coalesce(nullif(f->'properties'->>'type', ''), 'OTHER'),
         f->'properties'->>'type_label', f->'properties'->>'river',
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
