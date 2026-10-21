-- Activities: the number of units delivered (e.g. 3 PISOS, 1 solar-powered irrigation system) and who the
-- beneficiaries are – individual farmers or farmer groups (farmer cooperatives and associations, FCA). The
-- beneficiaries column stays the count: of farmers, or of FCAs.

alter table activities add column if not exists units numeric check (units >= 0);
alter table activities add column if not exists beneficiary_type text check (beneficiary_type in ('individual', 'fca'));
