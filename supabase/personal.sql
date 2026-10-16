-- SQL Editor에서 기존 setup.sql 다음에 실행. 기존 팀 정원/사진은 변경하지 않습니다.
begin;
create table if not exists public.pc_user_gardens (
    owner_id uuid primary key references auth.users(id) on delete cascade,
    state jsonb not null,
    revision bigint not null default 0 check (revision >= 0),
    updated_at timestamptz not null default now()
);
create table if not exists public.pc_user_garden_writes (
    owner_id uuid not null references auth.users(id) on delete cascade,
    write_id uuid not null,
    revision bigint not null,
    created_at timestamptz not null default now(),
    primary key (owner_id, write_id)
);
alter table public.pc_user_gardens enable row level security;
alter table public.pc_user_garden_writes enable row level security;
revoke all on public.pc_user_gardens, public.pc_user_garden_writes from public, anon, authenticated;
grant select, insert, update on public.pc_user_gardens to authenticated;
grant select, insert on public.pc_user_garden_writes to authenticated;

-- Restrictive boundaries also protect against an accidentally broader future policy.
drop policy if exists pc_garden_owner_boundary on public.pc_user_gardens;
create policy pc_garden_owner_boundary on public.pc_user_gardens as restrictive for all to authenticated
    using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
drop policy if exists pc_writes_owner_boundary on public.pc_user_garden_writes;
create policy pc_writes_owner_boundary on public.pc_user_garden_writes as restrictive for all to authenticated
    using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));

drop policy if exists pc_own_garden_read on public.pc_user_gardens;
create policy pc_own_garden_read on public.pc_user_gardens for select to authenticated
    using (owner_id = (select auth.uid()));
drop policy if exists pc_own_garden_insert on public.pc_user_gardens;
create policy pc_own_garden_insert on public.pc_user_gardens for insert to authenticated
    with check (owner_id = (select auth.uid()));
drop policy if exists pc_own_garden_update on public.pc_user_gardens;
create policy pc_own_garden_update on public.pc_user_gardens for update to authenticated
    using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
drop policy if exists pc_own_writes_read on public.pc_user_garden_writes;
create policy pc_own_writes_read on public.pc_user_garden_writes for select to authenticated
    using (owner_id = (select auth.uid()));
drop policy if exists pc_own_writes_insert on public.pc_user_garden_writes;
create policy pc_own_writes_insert on public.pc_user_garden_writes for insert to authenticated
    with check (owner_id = (select auth.uid()));

create or replace function public.pc_ensure_user_garden()
returns void language plpgsql security invoker set search_path = '' as $$
begin
    if auth.uid() is null then
        raise exception sqlstate 'PT401' using message = 'authentication_required';
    end if;
    insert into public.pc_user_gardens(owner_id, state) values (auth.uid(),
      '{"version":1,"tables":{"plants":[],"ai_analyses":[],"ai_suggestions":[],"care_logs":[],"plant_weather_regions":[],"care_schedules":[]}}'::jsonb)
    on conflict (owner_id) do nothing;
end;
$$;

create or replace function public.pc_save_user_garden(p_expected_revision bigint, p_state jsonb, p_write_id uuid)
returns bigint language plpgsql security invoker set search_path = '' as $$
declare
    current_revision bigint;
    saved_revision bigint;
begin
    if auth.uid() is null then
        raise exception sqlstate 'PT401' using message = 'authentication_required';
    end if;
    select revision into current_revision from public.pc_user_gardens
      where owner_id = auth.uid() for update;
    if not found then
        raise exception sqlstate 'PT404' using message = 'garden_not_initialized';
    end if;
    select revision into saved_revision from public.pc_user_garden_writes
      where owner_id = auth.uid() and write_id = p_write_id;
    if found then return saved_revision; end if;
    if p_expected_revision is null or current_revision <> p_expected_revision then
        raise exception sqlstate 'PT409' using message = 'garden_changed';
    end if;
    if p_state is null or p_state->>'version' is distinct from '1'
       or jsonb_typeof(p_state->'tables') is distinct from 'object' or p_write_id is null then
        raise exception sqlstate 'PT400' using message = 'invalid_state';
    end if;
    if octet_length(p_state::text) > 16777216 then
        raise exception sqlstate 'PT413' using message = 'state_too_large';
    end if;
    saved_revision := current_revision + 1;
    update public.pc_user_gardens set state = p_state, revision = saved_revision, updated_at = now()
      where owner_id = auth.uid();
    insert into public.pc_user_garden_writes(owner_id, write_id, revision)
      values (auth.uid(), p_write_id, saved_revision);
    return saved_revision;
end;
$$;
revoke all on function public.pc_ensure_user_garden() from public, anon;
revoke all on function public.pc_save_user_garden(bigint,jsonb,uuid) from public, anon;
grant execute on function public.pc_ensure_user_garden() to authenticated;
grant execute on function public.pc_save_user_garden(bigint,jsonb,uuid) to authenticated;

-- Never expose legacy photos/<uuid>.jpg or another owner's UUID prefix.
-- Refuse unsafe bucket configuration instead of silently serving public photos.
do $$ begin
    if not exists (select 1 from storage.buckets where id = 'plant-care-photos' and public = false) then
        raise exception 'Private plant-care-photos bucket required; run setup.sql and verify privacy first';
    end if;
end $$;
drop policy if exists pc_photo_owner_boundary on storage.objects;
create policy pc_photo_owner_boundary on storage.objects as restrictive for all to anon, authenticated
    using (bucket_id <> 'plant-care-photos' or (storage.foldername(name))[1] = (select auth.uid())::text)
    with check (bucket_id <> 'plant-care-photos' or (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists pc_own_photo_read on storage.objects;
create policy pc_own_photo_read on storage.objects for select to authenticated
    using (bucket_id = 'plant-care-photos' and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists pc_own_photo_insert on storage.objects;
create policy pc_own_photo_insert on storage.objects for insert to authenticated
    with check (bucket_id = 'plant-care-photos' and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists pc_own_photo_update on storage.objects;
create policy pc_own_photo_update on storage.objects for update to authenticated
    using (bucket_id = 'plant-care-photos' and (storage.foldername(name))[1] = (select auth.uid())::text)
    with check (bucket_id = 'plant-care-photos' and (storage.foldername(name))[1] = (select auth.uid())::text);
commit;
