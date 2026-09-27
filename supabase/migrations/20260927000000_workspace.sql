-- crewly workspace: notes, reminders, saved views, brief snapshots and a per-overlap event log, all company-scoped

create table public.note (
  id bigint generated always as identity primary key,
  company_id text not null default public.my_company() references public.company,
  target_kind text not null check (target_kind in ('overlap', 'project', 'company', 'plan_item')),
  target_id text not null,
  text text not null check (length(text) between 1 and 2000),
  created_by uuid not null default auth.uid() references auth.users on delete cascade,
  created_at timestamptz not null default now()
);
create index note_target_idx on public.note (company_id, target_kind, target_id, created_at desc);

create table public.reminder (
  id bigint generated always as identity primary key,
  company_id text not null default public.my_company() references public.company,
  text text not null check (length(text) between 1 and 500),
  due_at timestamptz not null,
  target_kind text check (target_kind in ('overlap', 'request', 'plan', 'company')),
  target_id text,
  done_at timestamptz,
  notified_at timestamptz,  -- set once the bell carried it
  created_by uuid not null default auth.uid() references auth.users on delete cascade,
  created_at timestamptz not null default now()
);
create index reminder_due_idx on public.reminder (company_id, due_at) where done_at is null;

create table public.saved_view (
  id bigint generated always as identity primary key,
  company_id text not null default public.my_company() references public.company,
  name text not null check (length(name) between 1 and 80),
  state jsonb not null default '{}',  -- {tab, partner, focus, selected, bbox}
  created_by uuid not null default auth.uid() references auth.users on delete cascade,
  created_at timestamptz not null default now(),
  unique (company_id, name)
);

create table public.brief_snapshot (
  id bigint generated always as identity primary key,
  company_id text not null default public.my_company() references public.company,
  overlap_ids integer[] not null default '{}',
  request_ids integer[] not null default '{}',
  taken_at timestamptz not null default now()
);

-- what happened on an overlap, one row per company that can see it
create table public.overlap_event (
  id bigint generated always as identity primary key,
  company_id text not null default public.my_company() references public.company,
  opportunity_id integer not null,
  kind text not null check (kind in ('status', 'request_sent', 'request_received', 'approved', 'declined', 'note')),
  detail jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index overlap_event_idx on public.overlap_event (company_id, opportunity_id, created_at desc);

-- requests and their answers log themselves for both companies
create function public.log_request_event() returns trigger
language plpgsql security definer set search_path = public
as $$
begin
  if tg_op = 'INSERT' then
    insert into public.overlap_event (company_id, opportunity_id, kind, detail) values
      (new.from_company, new.opportunity_id, 'request_sent', jsonb_build_object('request_id', new.id, 'to', new.to_company, 'note', new.note)),
      (new.to_company, new.opportunity_id, 'request_received', jsonb_build_object('request_id', new.id, 'from', new.from_company, 'note', new.note));
  elsif new.status is distinct from old.status and new.status in ('approved', 'declined') then
    insert into public.overlap_event (company_id, opportunity_id, kind, detail) values
      (new.from_company, new.opportunity_id, new.status, jsonb_build_object('request_id', new.id, 'by', new.to_company, 'feedback', new.feedback)),
      (new.to_company, new.opportunity_id, new.status, jsonb_build_object('request_id', new.id, 'by', new.to_company, 'feedback', new.feedback));
  end if;
  return new;
end $$;

create trigger collab_request_log after insert or update on public.collab_request
for each row execute function public.log_request_event();

alter table public.note enable row level security;
alter table public.reminder enable row level security;
alter table public.saved_view enable row level security;
alter table public.brief_snapshot enable row level security;
alter table public.overlap_event enable row level security;

create policy "companies read their notes" on public.note for select to authenticated using (company_id = public.my_company());
create policy "companies add notes" on public.note for insert to authenticated with check (company_id = public.my_company() and created_by = auth.uid());
create policy "companies delete their notes" on public.note for delete to authenticated using (company_id = public.my_company());

create policy "companies read their reminders" on public.reminder for select to authenticated using (company_id = public.my_company());
create policy "companies add reminders" on public.reminder for insert to authenticated with check (company_id = public.my_company() and created_by = auth.uid());
create policy "companies update their reminders" on public.reminder for update to authenticated
  using (company_id = public.my_company()) with check (company_id = public.my_company());
create policy "companies delete their reminders" on public.reminder for delete to authenticated using (company_id = public.my_company());

create policy "companies read their views" on public.saved_view for select to authenticated using (company_id = public.my_company());
create policy "companies save views" on public.saved_view for insert to authenticated with check (company_id = public.my_company() and created_by = auth.uid());
create policy "companies update their views" on public.saved_view for update to authenticated
  using (company_id = public.my_company()) with check (company_id = public.my_company());
create policy "companies delete their views" on public.saved_view for delete to authenticated using (company_id = public.my_company());

create policy "companies read their snapshots" on public.brief_snapshot for select to authenticated using (company_id = public.my_company());
create policy "companies take snapshots" on public.brief_snapshot for insert to authenticated with check (company_id = public.my_company());

create policy "companies read their overlap events" on public.overlap_event for select to authenticated using (company_id = public.my_company());
create policy "companies log their own events" on public.overlap_event for insert to authenticated with check (company_id = public.my_company());

revoke all on function public.log_request_event() from public, anon, authenticated;
