const {test, before, beforeEach, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {PGlite} = require('@electric-sql/pglite');
const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';
const ADMIN = '33333333-3333-4333-8333-333333333333';
const session = id => id.replace(/^./, 'a');
const cnpj = '00000000000191';
let db;

before(async () => {
    if (process.env.TEST_DATABASE_URL) {
        const {Client} = require('pg');
        const client = new Client({connectionString:process.env.TEST_DATABASE_URL});
        await client.connect();
        db = {query:(...args)=>client.query(...args), exec:sql=>client.query(sql), close:()=>client.end()};
    } else { db = new PGlite(); }
    await db.exec(`
      create role anon nologin; create role authenticated nologin;
      create schema auth;
      create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz);
      create table auth.sessions(id uuid primary key,user_id uuid references auth.users(id) on delete cascade);
      create function auth.jwt() returns jsonb language sql stable as
        $$ select coalesce(nullif(current_setting('request.jwt.claims',true),''),'{}')::jsonb $$;
      create function auth.uid() returns uuid language sql stable as
        $$ select nullif(auth.jwt()->>'sub','')::uuid $$;
      grant usage on schema auth to authenticated,anon;
      grant execute on function auth.jwt(),auth.uid() to authenticated,anon;
    `);
    const root = path.resolve(__dirname, '../../supabase/migrations');
    for (const name of fs.readdirSync(root).filter(n=>n.endsWith('.sql')).sort()) {
        await db.exec(fs.readFileSync(path.join(root,name),'utf8'));
    }
    for (const id of [A,B,ADMIN]) {
        await db.query('insert into auth.users values($1,$2,now())',[id,id+'@example.test']);
    }
});
beforeEach(async () => {
    await db.exec('reset role; truncate public.app_reviews,public.app_contact_attempts,public.app_contact_state,public.app_preferences,public.app_data_requests;');
    await db.exec("update public.app_accounts set status='active',role='user',access_until=null; delete from auth.sessions;");
    await db.query("update public.app_accounts set role='admin' where user_id=$1",[ADMIN]);
    for (const id of [A,B,ADMIN]) await db.query('insert into auth.sessions values($1,$2)',[session(id),id]);
});
after(async () => {await db.close();});
async function as(id, fn, extra={}) {
    await db.exec('begin; set local role authenticated;');
    await db.query("select set_config('request.jwt.claims',$1,true)", [JSON.stringify({sub:id,session_id:session(id),role:'authenticated',...extra})]);
    try {const result = await fn(); await db.exec('commit'); return result;}
    catch(error) {await db.exec('rollback');throw error;}
}
const importReview = id => as(id,()=>db.query('select public.app_import_reviews($1::jsonb) as result',[
    JSON.stringify([{cnpj,status:'contatado',source:'test'}])
]));

test('same CNPJ belongs independently to two users and foreign writes are blocked', async () => {
    await importReview(A);
    assert.equal((await as(B,()=>db.query('select * from public.app_reviews'))).rows.length,0);
    await importReview(B);
    assert.equal((await as(A,()=>db.query('select * from public.app_reviews'))).rows.length,1);
    await assert.rejects(as(A,()=>db.query("insert into public.app_reviews values($1,'11222333000181','contatado','bad',now())",[B])),{code:'42501'});
    await assert.rejects(as(A,()=>db.query('update public.app_reviews set user_id=$1',[B])),{code:'42501'});
    await as(A,()=>db.query('delete from public.app_reviews'));
    assert.equal((await as(B,()=>db.query('select * from public.app_reviews'))).rows.length,1);
});
test('anonymous role has neither table access nor RPC execution', async () => {
    await db.exec('set role anon');
    try {
        await assert.rejects(db.query('select * from public.app_reviews'),{code:'42501'});
        await assert.rejects(db.query("select public.app_import_reviews('[]')"),{code:'42501'});
    } finally {await db.exec('reset role');}
});
test('users cannot activate themselves, edit roles, or trust user_metadata', async () => {
    await assert.rejects(as(A,()=>db.query("update public.app_accounts set role='admin' where user_id=$1",[A])),{code:'42501'});
    await assert.rejects(as(A,()=>db.query("select public.app_admin_set_access($1,'admin','active',null)",[A]),
        {user_metadata:{role:'admin'},app_metadata:{role:'admin'}}),{code:'42501'});
    assert.equal((await as(A,()=>db.query('select app_private.is_admin() as admin'),{user_metadata:{role:'admin'}})).rows[0].admin,false);
    await db.query("update public.app_accounts set status='pending' where user_id=$1",[B]);
    await as(B,()=>db.query('select public.app_provision_account()'));
    assert.equal((await as(B,()=>db.query('select status from public.app_accounts'))).rows[0].status,'pending');
});
test('blocked, expired, and revoked sessions cannot read or change private data', async () => {
    await importReview(A);
    await db.query("update public.app_accounts set status='blocked' where user_id=$1",[A]);
    assert.equal((await as(A,()=>db.query('select * from public.app_reviews'))).rows.length,0);
    await assert.rejects(importReview(A),{code:'42501'});
    await db.query("update public.app_accounts set status='active',access_until=now()-interval '1 minute' where user_id=$1",[A]);
    await assert.rejects(importReview(A),{code:'42501'});
    await db.query('update public.app_accounts set access_until=null where user_id=$1',[A]);
    await db.query('delete from auth.sessions where user_id=$1',[A]);
    assert.equal((await as(A,()=>db.query('select * from public.app_reviews'))).rows.length,0);
    await assert.rejects(importReview(A),{code:'42501'});
});
test('administrators can release another account but cannot read another users contacts', async () => {
    await importReview(A);
    await as(ADMIN,()=>db.query("select public.app_admin_set_access($1,'user','blocked',null)",[B]));
    assert.equal((await as(B,()=>db.query('select status from public.app_accounts'))).rows[0].status,'blocked');
    assert.equal((await as(ADMIN,()=>db.query('select * from public.app_reviews'))).rows.length,0);
    await assert.rejects(as(ADMIN,()=>db.query("select public.app_admin_set_access($1,'user','blocked',null)",[ADMIN])),{code:'42501'});
});
test('attempt idempotence is scoped by user and imports are atomic', async () => {
    const record = id=>as(id,()=>db.query("select public.app_record_attempt('same',$1,'5533999999999','Maria','20% + café') as added",[cnpj]));
    assert.equal((await record(A)).rows[0].added,true);
    assert.equal((await record(A)).rows[0].added,false);
    assert.equal((await record(B)).rows[0].added,true);
    assert.equal((await as(A,()=>db.query('select attempt_count from public.app_contact_state'))).rows[0].attempt_count,1);
    const invalid=[{cnpj,status:'contatado',source:'ok'},{cnpj:'invalid',status:'contatado'}];
    await assert.rejects(as(A,()=>db.query('select public.app_import_reviews($1::jsonb)',[JSON.stringify(invalid)])));
    assert.equal((await as(A,()=>db.query('select * from public.app_reviews'))).rows.length,0);
});
test('preferences and reused database connections cannot cross users', async () => {
    await as(A,()=>db.query('insert into public.app_preferences values($1,$2)',[A,{sender:'Alice'}]));
    assert.equal((await as(B,()=>db.query('select * from public.app_preferences'))).rows.length,0);
    await db.exec('set role authenticated');
    try {assert.equal((await db.query('select * from public.app_preferences')).rows.length,0);}
    finally {await db.exec('reset role');}
});
test('data jobs require admin, prevent parallel loads, and enforce a shared daily quota', async () => {
    await assert.rejects(as(A,()=>db.query('select public.app_reserve_data_update(null)')),{code:'42501'});
    const reserve=()=>as(ADMIN,()=>db.query('select public.app_reserve_data_update(null) as job'));
    let job=(await reserve()).rows[0].job;
    assert.equal(job.requested_by,ADMIN);
    await assert.rejects(reserve(),/data_update_in_progress/);
    await as(ADMIN,()=>db.query("select public.app_update_data_job($1,'succeeded')",[job.id]));
    for(let i=0;i<2;i++) {
        job=(await reserve()).rows[0].job;
        await as(ADMIN,()=>db.query("select public.app_update_data_job($1,'succeeded')",[job.id]));
    }
    await assert.rejects(reserve(),/data_update_daily_limit/);
});
