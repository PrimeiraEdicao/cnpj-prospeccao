"""Atribui o histórico legado somente ao dono informado; padrão é simulação."""
import argparse
from datetime import datetime,timezone
import os
from pathlib import Path
import sqlite3
import sys
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.reviews import load_review_registry,import_cnpj,REVIEW_LABELS


def read_legacy(root, sqlite_path=None):
    reviews={r['cnpj']:r for f in ['config/reviewed_cnpjs.csv','state/contacted_cnpjs.csv'] for r in load_review_registry(root/f)}
    attempts=[];states=[]
    path=sqlite_path or root/'data/contact_state.db'
    if path.is_file():
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as legacy:
            legacy.row_factory=sqlite3.Row
            tables={r[0] for r in legacy.execute("select name from sqlite_master where type='table'")}
            if 'company_reviews' in tables:
                reviews.update({r['cnpj']:dict(r) for r in legacy.execute('select * from company_reviews')})
            if 'contact_attempts' in tables:attempts=[dict(r) for r in legacy.execute('select * from contact_attempts')]
            if 'company_contact_state' in tables:states=[dict(r) for r in legacy.execute('select * from company_contact_state')]
    for row in [*reviews.values(),*attempts,*states]:
        if import_cnpj(row['cnpj'])!=row['cnpj']:raise ValueError('Há CNPJ inválido no histórico; corrija antes de migrar.')
    if any(r['status'] not in REVIEW_LABELS for r in reviews.values()):raise ValueError('Há status inválido no histórico.')
    return list(reviews.values()),attempts,states


def transfer(conn,user_id,email,records,apply=False):
    account=conn.execute('select a.email,u.email_confirmed_at from public.app_accounts a join auth.users u on u.id=a.user_id where a.user_id=%s',(user_id,)).fetchone()
    if not account or account['email'].casefold()!=email.casefold() or not account['email_confirmed_at']:
        raise ValueError('UUID e e-mail não correspondem a uma conta confirmada de destino.')
    reviews,attempts,states=records
    if apply:
        for row in reviews:
            conn.execute('insert into public.app_reviews(user_id,cnpj,status,source,reviewed_at) values(%s,%s,%s,%s,%s) on conflict(user_id,cnpj) do nothing',
                (user_id,row['cnpj'],row['status'],row.get('source','')[:2000],row.get('reviewed_at') or datetime.now(timezone.utc)))
        for row in attempts:
            conn.execute('insert into public.app_contact_attempts(user_id,attempt_id,cnpj,phone,contact_name,message,attempted_at) values(%s,%s,%s,%s,%s,%s,%s) on conflict(user_id,attempt_id) do nothing',
                (user_id,row['attempt_id'],row['cnpj'],row['phone'],row['contact_name'],row['message'],row['attempted_at']))
        for row in states:
            conn.execute('insert into public.app_contact_state(user_id,cnpj,attempt_count,first_attempt_at,last_attempt_at,last_phone,last_contact_name) values(%s,%s,%s,%s,%s,%s,%s) on conflict(user_id,cnpj) do nothing',
                (user_id,row['cnpj'],row['attempt_count'],row['first_attempt_at'],row['last_attempt_at'],row['last_phone'],row['last_contact_name']))
    return {'reviews':len(reviews),'attempts':len(attempts),'states':len(states),'applied':apply}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id',type=UUID,required=True)
    parser.add_argument('--email',required=True)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--sqlite',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    records=read_legacy(args.root,args.sqlite)
    with psycopg.connect(os.environ['MIGRATIONS_DATABASE_URL'],row_factory=dict_row) as conn:
        print(transfer(conn,args.user_id,args.email,records,args.apply))
    print('Migração concluída; registros preexistentes foram mantidos.' if args.apply else 'Simulação; nada foi alterado. Confira os totais antes de usar --apply.')

if __name__=='__main__':
    try:main()
    except (psycopg.Error,KeyError,OSError,sqlite3.Error):raise SystemExit('Falha na migração. Confira os arquivos e MIGRATIONS_DATABASE_URL; detalhes sensíveis omitidos.')
    except ValueError as exc:raise SystemExit(str(exc))
