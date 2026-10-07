-- Supabase's API (pg-safeupdate) refuses a DELETE without a WHERE clause, even inside a function called over RPC:
-- saving the irrigation layer failed with "DELETE requires a WHERE clause (21000)". Replacing the whole layer is
-- intended, so say so explicitly with "where true".

create or replace function replace_irrigation_sources(p_features jsonb, p_service_areas jsonb default '[]')
returns int language plpgsql security definer set search_path = public as $$
declare n int; batch uuid := gen_random_uuid();
begin
  -- called by the server (service role) after an admin role check
  delete from irrigation_sources where true;
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
grant execute on function replace_irrigation_sources(jsonb, jsonb) to service_role;
