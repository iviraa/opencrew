-- companies, their logins, collaboration requests and the notifications they raise

create table public.company (
  id text primary key,  -- matches org.id in the planner database
  name text not null,
  short text not null,
  color text not null
);

insert into public.company (id, name, short, color) values
  ('desc', 'Dominion Energy South Carolina', 'Dominion SC', '#2f6bff'),
  ('gpc', 'Georgia Power', 'Georgia Power', '#ff5d5d');

create table public.member (
  user_id uuid primary key references auth.users on delete cascade,
  company_id text not null references public.company,
  username text not null unique,
  name text not null
);

create table public.collab_request (
  id bigint generated always as identity primary key,
  opportunity_id integer not null,  -- the overlap, from the planner database
  from_company text not null references public.company,
  to_company text not null references public.company,
  summary jsonb not null default '{}',  -- project names and savings at send time, so both sides see the same thing
  note text check (length(note) <= 2000),
  status text not null default 'pending' check (status in ('pending', 'approved', 'declined')),
  feedback text check (length(feedback) <= 2000),
  created_by uuid not null default auth.uid() references auth.users,
  created_at timestamptz not null default now(),
  responded_by uuid references auth.users,
  responded_at timestamptz,
  check (from_company <> to_company)
);
create unique index collab_one_pending on public.collab_request (opportunity_id, from_company) where status = 'pending';

create table public.notification (
  id bigint generated always as identity primary key,
  company_id text not null references public.company,  -- who sees it
  request_id bigint not null references public.collab_request on delete cascade,
  kind text not null check (kind in ('request', 'approved', 'declined')),
  created_at timestamptz not null default now(),
  read_at timestamptz
);
create index notification_company_idx on public.notification (company_id, created_at desc);

create function public.my_company() returns text
language sql stable security definer set search_path = public
as $$ select company_id from public.member where user_id = auth.uid() $$;

-- a new request notifies the other company
create function public.notify_request() returns trigger
language plpgsql security definer set search_path = public
as $$
begin
  insert into public.notification (company_id, request_id, kind) values (new.to_company, new.id, 'request');
  return new;
end $$;

create trigger collab_request_notify after insert on public.collab_request
for each row execute function public.notify_request();

-- only the receiving company answers, once, and the sender hears back
create function public.respond_request(request_id bigint, decision text, feedback text default null) returns public.collab_request
language plpgsql security definer set search_path = public
as $$
declare r public.collab_request;
begin
  if decision not in ('approved', 'declined') then
    raise exception 'decision must be approved or declined';
  end if;
  update public.collab_request c
     set status = decision, feedback = nullif(trim(respond_request.feedback), ''), responded_by = auth.uid(), responded_at = now()
   where c.id = request_id and c.status = 'pending' and c.to_company = public.my_company()
  returning * into r;
  if r.id is null then
    raise exception 'request not found or already answered';
  end if;
  insert into public.notification (company_id, request_id, kind) values (r.from_company, r.id, decision);
  update public.notification set read_at = now() where notification.request_id = r.id and company_id = r.to_company and read_at is null;
  return r;
end $$;

alter table public.company enable row level security;
alter table public.member enable row level security;
alter table public.collab_request enable row level security;
alter table public.notification enable row level security;

create policy "signed in users see companies" on public.company for select to authenticated using (true);
create policy "signed in users see the directory" on public.member for select to authenticated using (true);

create policy "companies see their requests" on public.collab_request for select to authenticated
  using (public.my_company() in (from_company, to_company));
create policy "companies send requests as themselves" on public.collab_request for insert to authenticated
  with check (from_company = public.my_company() and created_by = auth.uid() and status = 'pending'
              and feedback is null and responded_by is null and responded_at is null);

create policy "companies see their notifications" on public.notification for select to authenticated
  using (company_id = public.my_company());
create policy "companies mark their notifications read" on public.notification for update to authenticated
  using (company_id = public.my_company()) with check (company_id = public.my_company());

revoke update on public.notification from authenticated;
grant update (read_at) on public.notification to authenticated;  -- only the read mark can change
revoke all on function public.notify_request() from public, anon, authenticated;
revoke all on function public.respond_request(bigint, text, text) from public, anon;
grant execute on function public.respond_request(bigint, text, text) to authenticated;

alter publication supabase_realtime add table public.collab_request, public.notification;
