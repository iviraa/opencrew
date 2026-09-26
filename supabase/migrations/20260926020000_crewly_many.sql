-- any number of utilities: the directory carries each company's state, planner and login

alter table public.company add column if not exists state text;
alter table public.company add column if not exists planner text;
alter table public.company add column if not exists login text unique;
update public.company set state = 'SC', planner = 'filing', login = 'dominion' where id = 'desc' and login is null;
update public.company set state = 'GA', planner = 'filing', login = 'georgia' where id = 'gpc' and login is null;
