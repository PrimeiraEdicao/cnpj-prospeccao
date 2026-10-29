"""Backup integral PostgreSQL criptografado com age; nenhum arquivo claro é criado."""
import argparse
from datetime import datetime,timezone
import hashlib
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse,unquote,parse_qs


def pg_environment(url):
    parsed=urlparse(url)
    if parsed.scheme not in {'postgres','postgresql'} or not parsed.hostname or not parsed.path.strip('/'):
        raise ValueError('URL PostgreSQL inválida.')
    env=os.environ.copy()
    env.update(PGHOST=parsed.hostname,PGPORT=str(parsed.port or 5432),PGDATABASE=unquote(parsed.path[1:]),
               PGUSER=unquote(parsed.username or 'postgres'),PGPASSWORD=unquote(parsed.password or ''),
               PGSSLMODE=parse_qs(parsed.query).get('sslmode',['require'])[0])
    # O URL completo não precisa ser herdado pelo processo filho.
    env.pop('BACKUP_DATABASE_URL',None);env.pop('RESTORE_DATABASE_URL',None)
    return env


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['backup','restore'])
    parser.add_argument('--directory',type=Path,default=Path('backups'))
    parser.add_argument('--file',type=Path)
    parser.add_argument('--identity',type=Path,help='Chave age para restaurar; mantenha-a fora do servidor de backup')
    parser.add_argument('--confirm-database',help='Obrigatório na restauração; nome EXATO do banco vazio de destino')
    args=parser.parse_args()
    os.umask(0o077)
    if args.operation=='backup':
        args.directory.mkdir(parents=True,exist_ok=True)
        target=args.directory/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.dump.age')
        env=pg_environment(os.environ['BACKUP_DATABASE_URL'])
        recipient=os.environ['BACKUP_AGE_RECIPIENT']
        with subprocess.Popen(['pg_dump','--format=custom','--no-owner'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env) as dump:
            try:
                encrypted=subprocess.run(['age','--recipient',recipient,'--output',str(target)],stdin=dump.stdout,stderr=subprocess.DEVNULL)
            finally:dump.stdout.close()
            ok=dump.wait()==0 and encrypted.returncode==0
        if not ok:
            target.unlink(missing_ok=True);raise ValueError('Backup falhou; arquivo incompleto removido.')
        with target.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
        target.with_suffix(target.suffix+'.sha256').write_text(digest+'  '+target.name+'\n')
        print('Backup criptografado concluído: '+str(target))
    else:
        env=pg_environment(os.environ['RESTORE_DATABASE_URL'])
        if not args.file or not args.identity or args.confirm_database!=env['PGDATABASE']:
            raise ValueError('Informe --file, --identity e --confirm-database com o nome exato do destino vazio.')
        expected=args.file.with_suffix(args.file.suffix+'.sha256').read_text().split()[0]
        with args.file.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        if expected!=actual:raise ValueError('Checksum inválido. Restauração cancelada.')
        # Sem --clean: um alvo ocupado deve falhar. Restauração atômica.
        with subprocess.Popen(['age','--decrypt','--identity',str(args.identity),str(args.file)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL) as decrypt:
            restored=subprocess.run(['pg_restore','--single-transaction','--exit-on-error','--no-owner','--dbname',env['PGDATABASE']],stdin=decrypt.stdout,stderr=subprocess.DEVNULL,env=env)
            decrypt.stdout.close()
            if decrypt.wait()!=0 or restored.returncode:raise ValueError('Restauração falhou. Não use o destino antes de verificar a transação e os dados.')
        print('Restauração concluída. Verifique as tabelas, RLS, funções e dados antes de usar este banco.')

if __name__=='__main__':
    try:main()
    except (KeyError,OSError):raise SystemExit('Operação indisponível. Confira variáveis de ambiente, pg_dump/pg_restore e age. Credenciais omitidas.')
    except ValueError as exc:raise SystemExit(str(exc))
