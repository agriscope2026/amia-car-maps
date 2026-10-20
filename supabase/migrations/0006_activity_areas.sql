-- An activity can take place in several municipalities (and provinces): one activity, a list of places, so the
-- activity, its beneficiaries and its budget are counted once. Existing rows keep their one municipality.

alter table activities add column if not exists area_keys text[];
do $$ begin
  if exists (select 1 from information_schema.columns where table_name = 'activities' and column_name = 'area_key') then
    update activities set area_keys = array[area_key] where area_keys is null;
    alter table activities drop column area_key;
  end if;
end $$;
alter table activities alter column area_keys set not null;
alter table activities drop constraint if exists activities_area_keys_check;
alter table activities add constraint activities_area_keys_check check (cardinality(area_keys) >= 1);
drop index if exists activities_area_idx;
create index if not exists activities_area_keys_idx on activities using gin (area_keys);

-- every key must be a municipality of the gazetteer (an array cannot have a foreign key)
create or replace function activities_check_areas() returns trigger language plpgsql as $$
declare bad text;
begin
  select k into bad from unnest(new.area_keys) k where not exists (select 1 from gazetteer g where g.area_key = k) limit 1;
  if bad is not null then raise exception 'Unknown municipality: %', bad; end if;
  return new;
end $$;
drop trigger if exists activities_check_areas on activities;
create trigger activities_check_areas before insert or update of area_keys on activities
  for each row execute function activities_check_areas();
