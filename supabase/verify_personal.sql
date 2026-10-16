-- SQL Editor only. Synthetic subjects exist only within this rolled-back transaction.
-- No email/password/token is created or sent. Abort on failed assertions.
begin;
insert into auth.users(id) values
 ('73e82a91-95b3-4a3b-a073-f325f2700101'), ('73e82a91-95b3-4a3b-a073-f325f2700102');
insert into storage.objects(bucket_id, name) values
 ('plant-care-photos', '73e82a91-95b3-4a3b-a073-f325f2700101/photos/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg'),
 ('plant-care-photos', '73e82a91-95b3-4a3b-a073-f325f2700102/photos/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg');
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"73e82a91-95b3-4a3b-a073-f325f2700101","role":"authenticated"}', true);
select public.pc_ensure_user_garden();
select public.pc_save_user_garden(0,
 '{"version":1,"tables":{"plants":[],"ai_analyses":[],"ai_suggestions":[],"care_logs":[],"plant_weather_regions":[],"care_schedules":[]}}'::jsonb,
 '73e82a91-95b3-4a3b-a073-f325f2700103');
select set_config('request.jwt.claims', '{"sub":"73e82a91-95b3-4a3b-a073-f325f2700102","role":"authenticated"}', true);
select public.pc_ensure_user_garden();
do $$ begin
 if (select count(*) from public.pc_user_gardens) <> 1 then raise exception 'FAIL garden read isolation'; end if;
 if (select revision from public.pc_user_gardens) <> 0 then raise exception 'FAIL independent revision'; end if;
 if exists (select 1 from public.pc_user_garden_writes) then raise exception 'FAIL write history isolation'; end if;
 update public.pc_user_gardens set revision = 99 where owner_id = '73e82a91-95b3-4a3b-a073-f325f2700101';
 if found then raise exception 'FAIL cross-owner update'; end if;
 begin
  insert into public.pc_user_garden_writes(owner_id, write_id, revision)
   values ('73e82a91-95b3-4a3b-a073-f325f2700101', '73e82a91-95b3-4a3b-a073-f325f2700104', 99);
  raise exception 'FAIL cross-owner insert';
 exception when insufficient_privilege then null; end;
 begin
  perform 1 from public.pc_gardens;
  raise exception 'FAIL legacy shared garden access';
 exception when insufficient_privilege then null; end;
 if (select count(*) from storage.objects where bucket_id = 'plant-care-photos') <> 1 then
  raise exception 'FAIL photo read isolation';
 end if;
 begin
  insert into storage.objects(bucket_id, name) values ('plant-care-photos',
   '73e82a91-95b3-4a3b-a073-f325f2700101/photos/cccccccccccccccccccccccccccccccc.jpg');
  raise exception 'FAIL cross-owner photo upload';
 exception when insufficient_privilege then null; end;
 update storage.objects set name = 'blocked' where bucket_id = 'plant-care-photos'
  and name like '73e82a91-95b3-4a3b-a073-f325f2700101/%';
 if found then raise exception 'FAIL cross-owner photo update'; end if;
end $$;
select set_config('request.jwt.claims', '{"sub":"73e82a91-95b3-4a3b-a073-f325f2700101","role":"authenticated"}', true);
do $$ begin
 if (select revision from public.pc_user_gardens) <> 1 then raise exception 'FAIL owner write preservation'; end if;
 if (select count(*) from public.pc_user_garden_writes) <> 1 then raise exception 'FAIL owner write visibility'; end if;
end $$;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);
do $$ begin
 begin
  perform 1 from public.pc_user_gardens;
  raise exception 'FAIL anonymous garden read';
 exception when insufficient_privilege then null; end;
 begin
  perform public.pc_ensure_user_garden();
  raise exception 'FAIL anonymous RPC';
 exception when insufficient_privilege then null; end;
 if exists (select 1 from storage.objects where bucket_id = 'plant-care-photos') then
  raise exception 'FAIL anonymous photos';
 end if;
end $$;
rollback;
select 'PASS: owner read/write/revision/history/photo isolation and anonymous denial; all test rows rolled back' as verification;
