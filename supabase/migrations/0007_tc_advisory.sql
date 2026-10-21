-- Special Farm Weather Outlook and Advisory: a product made from the PAGASA Tropical Cyclone Bulletin (the CAR
-- municipalities under each wind signal). Its period is the event – the bulletin's issue date to the last forecast
-- position inside PAR – not a dekad, month or season.

alter type product_type add value if not exists 'tc_advisory';
alter type period_kind add value if not exists 'event';

-- activities can answer the tropical cyclone outlook too
alter table activities drop constraint if exists activities_hazard_check;
alter table activities add constraint activities_hazard_check
  check (hazard in ('general', 'envi', 'drought', 'rainfall_dekad', 'rainfall_seasonal', 'tc_advisory'));
