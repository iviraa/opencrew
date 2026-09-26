-- crewly as an agent: suggestions in the bell, company memory, saved chat, and multi-step goals

-- suggestions ride on notifications so the bell and realtime already carry them
alter table public.notification alter column request_id drop not null;
alter table public.notification drop constraint notification_kind_check;
alter table public.notification add constraint notification_kind_check check (kind in ('request', 'approved', 'declined', 'suggestion'));
alter table public.notification
  add column title text check (length(title) <= 200),
  add column body text check (length(body) <= 2000),
  add column action jsonb,  -- what the suggestion offers to do, e.g. {"type": "open_overlap", "id": 18}
  add column dedup_key text,  -- one suggestion per situation
  add column dismissed_at timestamptz;
alter table public.notification add constraint notification_shape check (
  (kind = 'suggestion' and title is not null) or (kind <> 'suggestion' and request_id is not null));
create unique index notification_dedup on public.notification (company_id, dedup_key) where dedup_key is not null;
grant update (dismissed_at) on public.notification to authenticated;

-- things a company wants crewly to keep in mind, e.g. "we never share crews in hurricane season"
create table public.crewly_memory (
  id bigint generated always as identity primary key,
  company_id text not null default public.my_company() references public.company,
  text text not null check (length(text) between 1 and 500),
  created_by uuid not null default auth.uid() references auth.users on delete cascade,
  created_at timestamptz not null default now()
);

-- chat history, shared by everyone at the company
create table public.chat_message (
  id bigint generated always as identity primary key,
  company_id text not null default public.my_company() references public.company,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  role text not null check (role in ('user', 'model')),
  text text not null check (length(text) <= 8000),
  meta jsonb not null default '{}',  -- overlap cards and confirm buttons shown with the message
  created_at timestamptz not null default now()
);
create index chat_message_company_idx on public.chat_message (company_id, created_at desc);

-- a multi-step goal: ranked overlaps, a drafted note each, and the request that answers it
create table public.agent_task (
  id bigint generated always as identity primary key,
  company_id text not null default public.my_company() references public.company,
  goal text not null check (length(goal) between 1 and 500),
  status text not null default 'active' check (status in ('active', 'done', 'cancelled')),
  steps jsonb not null default '[]',  -- [{"opportunity_id": 18, "title": "...", "note": "...", "request_id": null, "skipped": false}]
  created_by uuid not null default auth.uid() references auth.users on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.crewly_memory enable row level security;
alter table public.chat_message enable row level security;
alter table public.agent_task enable row level security;

create policy "companies read their memory" on public.crewly_memory for select to authenticated using (company_id = public.my_company());
create policy "companies add to their memory" on public.crewly_memory for insert to authenticated
  with check (company_id = public.my_company() and created_by = auth.uid());
create policy "companies forget their memory" on public.crewly_memory for delete to authenticated using (company_id = public.my_company());

create policy "companies read their chat" on public.chat_message for select to authenticated using (company_id = public.my_company());
create policy "people write their own chat" on public.chat_message for insert to authenticated
  with check (company_id = public.my_company() and user_id = auth.uid());
create policy "companies clear their chat" on public.chat_message for delete to authenticated using (company_id = public.my_company());

create policy "companies read their goals" on public.agent_task for select to authenticated using (company_id = public.my_company());
create policy "companies start goals" on public.agent_task for insert to authenticated
  with check (company_id = public.my_company() and created_by = auth.uid());
create policy "companies update their goals" on public.agent_task for update to authenticated
  using (company_id = public.my_company()) with check (company_id = public.my_company());

alter publication supabase_realtime add table public.agent_task;
