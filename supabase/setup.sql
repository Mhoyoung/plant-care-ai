-- 전용 무료 Supabase 프로젝트의 SQL Editor에서 한 번 실행합니다.
-- 기존 정원 데이터는 덮어쓰지 않습니다. 팀원 접근은 Streamlit의 비공개 공유로 제한합니다.
begin;
create table if not exists public.pc_gardens (
    id text primary key check (id = 'team-garden'),
    state jsonb not null,
    revision bigint not null default 0 check (revision >= 0),
    updated_at timestamptz not null default now()
);
create table if not exists public.pc_garden_writes (
    write_id uuid primary key,
    revision bigint not null,
    created_at timestamptz not null default now()
);
alter table public.pc_gardens enable row level security;
alter table public.pc_garden_writes enable row level security;
revoke all on public.pc_gardens, public.pc_garden_writes from public, anon, authenticated;
grant select, insert, update on public.pc_gardens to service_role;
grant select, insert on public.pc_garden_writes to service_role;

insert into public.pc_gardens(id, state) values ('team-garden',
    '{"version":1,"tables":{"plants":[],"ai_analyses":[],"ai_suggestions":[],"care_logs":[],"plant_weather_regions":[]}}'::jsonb)
on conflict (id) do nothing;

create or replace function public.pc_save_garden(p_expected_revision bigint, p_state jsonb, p_write_id uuid)
returns bigint language plpgsql security invoker set search_path = '' as $$
declare
    current_revision bigint;
    saved_revision bigint;
begin
    select revision into current_revision from public.pc_gardens where id = 'team-garden' for update;
    if not found then
        raise exception sqlstate 'PT404' using message = 'garden_not_initialized';
    end if;
    select revision into saved_revision from public.pc_garden_writes where write_id = p_write_id;
    if found then return saved_revision; end if;
    if current_revision <> p_expected_revision then
        raise exception sqlstate 'PT409' using message = 'garden_changed';
    end if;
    if p_state is null or p_state->>'version' is distinct from '1' or jsonb_typeof(p_state->'tables') is distinct from 'object' then
        raise exception sqlstate 'PT400' using message = 'invalid_state';
    end if;
    if octet_length(p_state::text) > 16777216 then
        raise exception sqlstate 'PT413' using message = 'state_too_large';
    end if;
    saved_revision := current_revision + 1;
    update public.pc_gardens set state = p_state, revision = saved_revision, updated_at = now() where id = 'team-garden';
    insert into public.pc_garden_writes(write_id, revision) values (p_write_id, saved_revision);
    return saved_revision;
end;
$$;
revoke all on function public.pc_save_garden(bigint,jsonb,uuid) from public, anon, authenticated;
grant execute on function public.pc_save_garden(bigint,jsonb,uuid) to service_role;

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values ('plant-care-photos', 'plant-care-photos', false, 10485760, array['image/jpeg'])
on conflict (id) do nothing;
commit;
