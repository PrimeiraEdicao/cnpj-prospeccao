"""Libera o primeiro administrador usando uma conexão SQL de operação, fora do app."""
import argparse
import os
from uuid import UUID
import psycopg


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id',required=True,type=UUID)
    parser.add_argument('--email',required=True,help='Deve corresponder ao cadastro confirmado no Supabase')
    parser.add_argument('--apply',action='store_true',help='Sem este parâmetro apenas confere a conta')
    args=parser.parse_args()
    with psycopg.connect(os.environ['MIGRATIONS_DATABASE_URL']) as conn:
        row=conn.execute('select u.email,u.email_confirmed_at,a.role from auth.users u join public.app_accounts a on a.user_id=u.id where u.id=%s',(args.user_id,)).fetchone()
        if not row or row[0].casefold()!=args.email.casefold() or not row[1]:
            raise ValueError('UUID e e-mail devem corresponder a uma conta com e-mail confirmado.')
        if args.apply:
            # Não substitui um administrador existente por engano.
            other=conn.execute("select 1 from public.app_accounts where role='admin' and status='active' and user_id<>%s limit 1",(args.user_id,)).fetchone()
            if other:raise ValueError('Já existe outro administrador ativo. Use a interface para conceder acesso.')
            conn.execute("update public.app_accounts set role='admin',status='active',access_until=null where user_id=%s",(args.user_id,))
        print('Administrador ativado.' if args.apply else 'Conta verificada. Simulação; nenhuma alteração realizada.')

if __name__=='__main__':
    try:main()
    except (psycopg.Error,KeyError):raise SystemExit('Falha na operação. Confira MIGRATIONS_DATABASE_URL e as migrações; credenciais omitidas.')
    except ValueError as exc:raise SystemExit(str(exc))
