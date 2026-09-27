-- free-standing notes in the notebook: a note need not be about an overlap or a project
alter table public.note drop constraint if exists note_target_kind_check;
alter table public.note add constraint note_target_kind_check check (target_kind in ('overlap', 'project', 'company', 'plan_item', 'general'));
