import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from sovereign_intake.common import IntakeError
from . import core, recovery


def template_hub_instance():
    """The template-run hub's instance file, or None.

    Same location bin/sov checks before running the law check, so one machine
    answers "which hub am I" the same way everywhere.
    """
    state = os.environ.get('SOV_STATE_DIR') or os.path.join(os.path.expanduser('~'), '.local/state/sovereign')
    instance = Path(state) / 'hub.json'
    return instance if instance.is_file() else None


def delegated_status():
    """Answer `status` from the template hub's job table, or None if it is not this machine.

    Returns that command's exit code, so a failing job status is not swallowed.
    """
    if not template_hub_instance():
        return None
    sov_hub = Path(__file__).resolve().parents[2] / 'bin' / 'sov-hub'
    if not sov_hub.is_file():
        return None
    return subprocess.call([sys.executable, str(sov_hub), 'jobs', 'status'])


def main():
    parser = argparse.ArgumentParser(description='Install and recover one local Sovereign Hub. Changes are previews unless --apply is given.')
    sub = parser.add_subparsers(dest='command', required=True)
    install = sub.add_parser('install'); install.add_argument('--archive', required=True); install.add_argument('--destination', required=True); install.add_argument('--model', required=True)
    install.add_argument('--endpoint', default='http://127.0.0.1:11434/v1/chat/completions'); install.add_argument('--lane', default='curator'); install.add_argument('--max-items', type=int, default=40); install.add_argument('--apply', action='store_true')
    for command in ('status', 'doctor', 'activate', 'run', 'recovery'):
        p = sub.add_parser(command); p.add_argument('--config'); p.add_argument('--apply', action='store_true') if command not in ('status', 'doctor') else None
        if command == 'activate': p.add_argument('--confirm-single-hub', action='store_true')
        if command == 'run':
            p.add_argument('job', choices=[*core.JOBS, 'approve', 'reject']); p.add_argument('--proposal'); p.add_argument('--reason', default='')
        if command == 'recovery': p.add_argument('--folder', required=True, type=Path); p.add_argument('--key-file', required=True, type=Path)
    p = sub.add_parser('key'); p.add_argument('--output', type=Path, required=True); p.add_argument('--apply', action='store_true')
    p = sub.add_parser('snapshot'); p.add_argument('--config'); p.add_argument('--output', type=Path, required=True); p.add_argument('--key-file', type=Path, required=True); p.add_argument('--apply', action='store_true')
    p = sub.add_parser('restore'); p.add_argument('--capsule', type=Path, required=True); p.add_argument('--destination', type=Path, required=True); p.add_argument('--key-file', type=Path, required=True); p.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'install':
            plan = core.install_plan(args.archive, args.destination, args.model, args.endpoint, args.lane, args.max_items); result = core.install(plan, args.apply)
        elif args.command == 'key': result = recovery.recovery_key(args.output, args.apply)
        elif args.command == 'restore': result = recovery.restore(args.capsule, args.destination, args.key_file, args.apply)
        else:
            if args.command == 'status' and not core.config_path(args.config).exists():
                delegated = delegated_status()
                if delegated is not None:
                    return delegated
            config = core.load(core.config_path(args.config))
            if args.command == 'status': result = core.status(config)
            elif args.command == 'doctor': result = core.doctor(config)
            elif args.command == 'activate': result = core.activate(config, args.apply, args.confirm_single_hub)
            elif args.command == 'run': result = core.run(config, args.job, args.apply, args.proposal, args.reason)
            elif args.command == 'recovery': result = recovery.configure(config, args.folder, args.key_file, args.apply)
            else: result = recovery.snapshot(config, args.output, args.key_file, args.apply)
        print(json.dumps(result, indent=2)); return 0 if result.get('exit', 0) == 0 else 1
    except (ValueError, OSError, KeyError, IntakeError, subprocess.SubprocessError) as exc:
        message = 'The operation failed. Existing installation and archive were preserved where possible; inspect the operation receipt before retrying.' if isinstance(exc, subprocess.SubprocessError) else str(exc)
        print(json.dumps({'error': message, 'state': 'failed', 'inspect_receipts': True})); return 65
