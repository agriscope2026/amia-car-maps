-- Colour per crop for the dashboard crop overlay and the crop circles on exported maps (chosen by admins).
alter table crops_tables add column if not exists colors jsonb not null default '{}';
