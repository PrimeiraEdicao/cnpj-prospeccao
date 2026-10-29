-- Additive migration: legacy tables and CSV files are deliberately left intact.
create schema if not exists app_private;
revoke all on schema app_private from public, anon, authenticated;
grant usage on schema app_private to authenticated;

create table public.app_accounts (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  role text not null default 'user' check (role in ('user','admin')),
  status text not null default 'pending' check (status in ('pending','active','blocked')),
  access_until timestamptz,
  created_at timestamptz not null default now()
);
create table public.app_reviews (
  user_id uuid not null references public.app_accounts(user_id) on delete cascade,
  cnpj varchar(14) not null check (cnpj ~ '^[0-9]{14}$'),
  status text not null check (status in ('revisado','contatado','fora_perfil')),
  source text not null check (length(source) <= 2000),
  reviewed_at timestamptz not null default now(),
  primary key (user_id,cnpj)
);
create table public.app_contact_attempts (
  user_id uuid not null references public.app_accounts(user_id) on delete cascade,
  attempt_id varchar(64) not null,
  cnpj varchar(14) not null check (cnpj ~ '^[0-9]{14}$'),
  phone varchar(20), contact_name varchar(255), message text check (length(message) <= 10000),
  attempted_at timestamptz not null default now(),
  primary key (user_id,attempt_id)
);
create index app_attempts_user_company on public.app_contact_attempts(user_id,cnpj,attempted_at);
create table public.app_contact_state (
  user_id uuid not null references public.app_accounts(user_id) on delete cascade,
  cnpj varchar(14) not null check (cnpj ~ '^[0-9]{14}$'),
  attempt_count integer not null check (attempt_count > 0),
  first_attempt_at timestamptz not null, last_attempt_at timestamptz not null,
  last_phone varchar(20), last_contact_name varchar(255),
  primary key (user_id,cnpj)
);
create table public.app_preferences (
  user_id uuid primary key references public.app_accounts(user_id) on delete cascade,
  value jsonb not null default '{}'::jsonb check (jsonb_typeof(value)='object' and octet_length(value::text) <= 8192)
);
create table public.app_data_requests (
  id uuid primary key default gen_random_uuid(),
  requested_by uuid not null references public.app_accounts(user_id),
  scope jsonb,
  status text not null default 'reserved' check (status in ('reserved','queued','running','succeeded','failed')),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index app_requests_owner on public.app_data_requests(requested_by,created_at desc);
create index app_requests_active on public.app_data_requests(created_at) where status in ('reserved','queued','running');

-- Privileged lookups stay outside exposed schemas, with fixed search paths.
-- Identity always comes from Supabase-verified JWT claims, never user_metadata.
create function app_private.session_is_valid() returns boolean
language plpgsql stable security definer set search_path = '' as $$
declare actor uuid := auth.uid(); session_uuid uuid;
begin
  if actor is null or coalesce((auth.jwt()->>'is_anonymous')::boolean,false) then return false; end if;
  session_uuid := nullif(auth.jwt()->>'session_id','')::uuid;
  return session_uuid is not null and exists (
    select 1 from auth.sessions s join auth.users u on u.id=s.user_id
    where s.id=session_uuid and s.user_id=actor and u.email_confirmed_at is not null
  );
exception when invalid_text_representation then return false;
end $$;
create function app_private.account_is_active() returns boolean
language sql stable security definer set search_path = '' as $$
  select app_private.session_is_valid() and exists (
    select 1 from public.app_accounts a where a.user_id=auth.uid() and a.status='active'
    and (a.access_until is null or a.access_until > now())
  )
$$;
create function app_private.is_admin() returns boolean
language sql stable security definer set search_path = '' as $$
  select app_private.account_is_active() and exists (
    select 1 from public.app_accounts a where a.user_id=auth.uid() and a.role='admin'
  )
$$;
create function app_private.provision_account() returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not app_private.session_is_valid() then raise insufficient_privilege; end if;
  insert into public.app_accounts(user_id,email)
    select id,email from auth.users where id=auth.uid()
    on conflict (user_id) do nothing;
end $$;
create function app_private.on_auth_user_created() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.email is not null then
    insert into public.app_accounts(user_id,email) values(new.id,new.email) on conflict do nothing;
  end if;
  return new;
end $$;
create trigger cnpj_account_after_signup after insert on auth.users
for each row execute function app_private.on_auth_user_created();
insert into public.app_accounts(user_id,email)
  select id,email from auth.users where email is not null on conflict do nothing;

alter table public.app_accounts enable row level security;
create policy app_accounts_read on public.app_accounts for select to authenticated
using ((select app_private.session_is_valid()) and (user_id=(select auth.uid()) or (select app_private.is_admin())));
-- No INSERT/UPDATE/DELETE policy or grants on accounts: users cannot grant themselves access.

alter table public.app_reviews enable row level security;
alter table public.app_reviews force row level security;
create policy app_reviews_owner on public.app_reviews for all to authenticated
using (user_id=(select auth.uid()) and (select app_private.account_is_active()))
with check (user_id=(select auth.uid()) and (select app_private.account_is_active()));
alter table public.app_contact_attempts enable row level security;
alter table public.app_contact_attempts force row level security;
create policy app_attempts_owner on public.app_contact_attempts for all to authenticated
using (user_id=(select auth.uid()) and (select app_private.account_is_active()))
with check (user_id=(select auth.uid()) and (select app_private.account_is_active()));
alter table public.app_contact_state enable row level security;
alter table public.app_contact_state force row level security;
create policy app_state_owner on public.app_contact_state for all to authenticated
using (user_id=(select auth.uid()) and (select app_private.account_is_active()))
with check (user_id=(select auth.uid()) and (select app_private.account_is_active()));
alter table public.app_preferences enable row level security;
alter table public.app_preferences force row level security;
create policy app_preferences_owner on public.app_preferences for all to authenticated
using (user_id=(select auth.uid()) and (select app_private.account_is_active()))
with check (user_id=(select auth.uid()) and (select app_private.account_is_active()));
alter table public.app_data_requests enable row level security;
create policy app_requests_read on public.app_data_requests for select to authenticated
using ((select app_private.account_is_active()) and (requested_by=(select auth.uid()) or (select app_private.is_admin())));

create function public.app_provision_account() returns void
language sql security invoker set search_path = '' as $$ select app_private.provision_account() $$;

create function public.app_import_reviews(p_records jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare added integer; total integer;
begin
  if not app_private.account_is_active() then raise insufficient_privilege; end if;
  if jsonb_typeof(p_records) is distinct from 'array' then raise exception 'invalid records'; end if;
  if jsonb_array_length(p_records) not between 1 and 50000 then raise exception 'invalid record count'; end if;
  if exists (select 1 from jsonb_array_elements(p_records) r
    where jsonb_typeof(r) is distinct from 'object' or r->>'cnpj' is null or (r->>'cnpj') !~ '^[0-9]{14}$'
    or coalesce(r->>'status','') not in ('revisado','contatado','fora_perfil') or length(coalesce(r->>'source','')) > 2000)
    then raise exception 'invalid record'; end if;
  select count(distinct r->>'cnpj') into total from jsonb_array_elements(p_records) r;
  insert into public.app_reviews(user_id,cnpj,status,source)
    select auth.uid(),r->>'cnpj',r->>'status',coalesce(r->>'source','') from jsonb_array_elements(p_records) r
    on conflict(user_id,cnpj) do nothing;
  get diagnostics added = row_count;
  return jsonb_build_object('added',added,'existing',total-added);
end $$;

create function public.app_record_attempt(p_attempt_id text,p_cnpj text,p_phone text,p_contact_name text,p_message text) returns boolean
language plpgsql security invoker set search_path = '' as $$
declare added integer;
begin
  if not app_private.account_is_active() then raise insufficient_privilege; end if;
  if length(p_attempt_id) not between 1 and 64 then raise exception 'invalid attempt'; end if;
  insert into public.app_contact_attempts(user_id,attempt_id,cnpj,phone,contact_name,message)
    values(auth.uid(),p_attempt_id,p_cnpj,p_phone,p_contact_name,p_message) on conflict do nothing;
  get diagnostics added = row_count;
  if added=0 then return false; end if;
  insert into public.app_contact_state(user_id,cnpj,attempt_count,first_attempt_at,last_attempt_at,last_phone,last_contact_name)
    values(auth.uid(),p_cnpj,1,now(),now(),p_phone,p_contact_name)
    on conflict(user_id,cnpj) do update set attempt_count=public.app_contact_state.attempt_count+1,
      last_attempt_at=excluded.last_attempt_at,last_phone=excluded.last_phone,last_contact_name=excluded.last_contact_name;
  return true;
end $$;

create function app_private.set_account_access(p_user_id uuid,p_role text,p_status text,p_access_until timestamptz) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not app_private.is_admin() or p_user_id=auth.uid() then raise insufficient_privilege; end if;
  if p_role not in ('user','admin') or p_status not in ('pending','active','blocked') then raise exception 'invalid access'; end if;
  update public.app_accounts set role=p_role,status=p_status,access_until=p_access_until where user_id=p_user_id;
  if not found then raise exception 'account not found'; end if;
end $$;
create function public.app_admin_set_access(p_user_id uuid,p_role text,p_status text,p_access_until timestamptz default null) returns void
language sql security invoker set search_path = '' as $$
  select app_private.set_account_access(p_user_id,p_role,p_status,p_access_until)
$$;

create function app_private.reserve_data_update(p_scope jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare job public.app_data_requests;
begin
  if not app_private.is_admin() then raise insufficient_privilege; end if;
  if p_scope is not null and (jsonb_typeof(p_scope) <> 'object' or coalesce(p_scope->>'uf','') !~ '^[A-Z]{2}$'
      or coalesce(p_scope->>'municipio_code','') !~ '^[0-9]{4}$') then raise exception 'invalid scope'; end if;
  perform pg_advisory_xact_lock(741852963);
  update public.app_data_requests set status='failed',updated_at=now()
    where status in ('reserved','queued','running') and created_at < now()-interval '6 hours';
  if exists(select 1 from public.app_data_requests where status in ('reserved','queued','running')) then
    raise exception 'data_update_in_progress'; end if;
  if (select count(*) from public.app_data_requests where created_at >= date_trunc('day',now())) >= 3 then
    raise exception 'data_update_daily_limit'; end if;
  insert into public.app_data_requests(requested_by,scope) values(auth.uid(),p_scope) returning * into job;
  return to_jsonb(job);
end $$;
create function public.app_reserve_data_update(p_scope jsonb default null) returns jsonb
language sql security invoker set search_path = '' as $$ select app_private.reserve_data_update(p_scope) $$;
create function app_private.update_data_job(p_job_id uuid,p_status text) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not app_private.is_admin() then raise insufficient_privilege; end if;
  if p_status not in ('queued','running','succeeded','failed') then raise exception 'invalid status'; end if;
  update public.app_data_requests set status=p_status,updated_at=now() where id=p_job_id;
end $$;
create function public.app_update_data_job(p_job_id uuid,p_status text) returns void
language sql security invoker set search_path = '' as $$ select app_private.update_data_job(p_job_id,p_status) $$;

-- Explicit grants work with projects that disable automatic Data API grants.
revoke all on public.app_accounts,public.app_reviews,public.app_contact_attempts,public.app_contact_state,
  public.app_preferences,public.app_data_requests from public,anon,authenticated;
grant select on public.app_accounts,public.app_data_requests to authenticated;
grant select,insert,update,delete on public.app_reviews,public.app_preferences to authenticated;
grant select,insert,update on public.app_contact_attempts,public.app_contact_state to authenticated;
revoke all on all functions in schema app_private from public,anon,authenticated;
grant execute on function app_private.session_is_valid(),app_private.account_is_active(),app_private.is_admin(),
  app_private.provision_account(),app_private.set_account_access(uuid,text,text,timestamptz),
  app_private.reserve_data_update(jsonb),app_private.update_data_job(uuid,text) to authenticated;
revoke all on function public.app_provision_account(),public.app_import_reviews(jsonb),
  public.app_record_attempt(text,text,text,text,text),public.app_admin_set_access(uuid,text,text,timestamptz),
  public.app_reserve_data_update(jsonb),public.app_update_data_job(uuid,text) from public,anon,authenticated;
grant execute on function public.app_provision_account(),public.app_import_reviews(jsonb),
  public.app_record_attempt(text,text,text,text,text),public.app_admin_set_access(uuid,text,text,timestamptz),
  public.app_reserve_data_update(jsonb),public.app_update_data_job(uuid,text) to authenticated;
