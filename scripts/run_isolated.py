"""Run a command with the private manifest's isolated DB identities; never print secrets."""
import argparse
import os
import subprocess
from pathlib import Path
from scripts.setup_database_identity import environment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--admin-password-file',help='Private test-cluster admin password file; never a production runtime fallback')
    parser.add_argument('--redis-url',required=True,help='Dedicated test Redis database URL')
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command:parser.error('Provide a command after --')
    selected=environment(args.manifest)
    env=dict(os.environ,**selected,REDIS_URL=args.redis_url)
    if args.admin_password_file:
        source=Path(args.admin_password_file)
        if source.stat().st_mode & 0o077 or source.stat().st_uid!=os.getuid():raise ValueError('Private test admin password file required')
        env['PGPASSWORD']=source.read_text().strip()
    return subprocess.call(command,env=env)


if __name__=='__main__':raise SystemExit(main())
