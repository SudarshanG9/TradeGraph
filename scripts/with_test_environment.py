"""Run explicit native tests with private test configuration; never prints secrets."""
import argparse
import os
from pathlib import Path
import subprocess
from dotenv import dotenv_values


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--admin-password-file',type=Path,required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command:parser.error('Provide a command after --')
    for path in (args.env_file,args.admin_password_file):
        info=path.stat()
        if info.st_uid!=os.getuid() or info.st_mode & 0o077:raise ValueError('Private owner-only files required')
    values={k:v for k,v in dotenv_values(args.env_file,interpolate=False).items() if v is not None}
    if not values.get('POSTGRES_DB','').startswith(('tradegraph_test_','tradegraph_registration_')):
        raise ValueError('Explicit isolated test database required')
    env=dict(os.environ,**values,PGPASSWORD=args.admin_password_file.read_text().strip())
    return subprocess.call(command,env=env)


if __name__=='__main__':raise SystemExit(main())
