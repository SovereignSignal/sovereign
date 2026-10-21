"""`sov ingest sessions`: the session-capture adapter beside `folder`.

bin/sov-ingest hands `sessions ...` to main() before its own argparse runs. The flags
here are the internal ones connectors/harness/claude-code/sessions.sh drives on each
tick:

  --gate            exit 3 when capture is off for the tool (the tick then stops,
                    silently), 0 when it is on; readiness is the tick's to check, so
                    a waiting reason reaches the lane's manifest
  --tick --dest D   one pass into the private stage folder D
  --commit-tick     merge the rows the tick staged, after a successful publish
  --discard-tick    drop them after a failed one, so every session retries

The owner's commands (the dry plan, --show, --apply, --on/--off, status) join
COMMANDS beside these.
"""
import os
import sys
import time

from . import run

TOOL = "claude-code"
EXIT_OFF = 3
EXIT_USAGE = 64
EXIT_CONFIG = 2
USAGE = "usage: sov ingest sessions --gate | --tick --dest <dir> | --commit-tick | --discard-tick"


def _no_args(args):
    if args:
        raise SystemExit(_usage())


def _usage():
    sys.stderr.write(USAGE + "\n")
    return EXIT_USAGE


def _gate(args, env):
    _no_args(args)
    return 0 if run.enabled(TOOL, env) else EXIT_OFF


def _tick(args, env):
    if len(args) != 2 or args[0] != "--dest" or not args[1]:
        return _usage()
    summary = run.tick(TOOL, env, args[1], time.time())
    if summary["status"] != "off":
        line = "sessions: %d call(s), %d capture(s), %d waiting" % (
            summary["calls"], summary["captures"], summary["pending"])
        if summary["reason"]:
            line += "; waiting: " + summary["reason"]
        print(line)
    return summary["exit"]


def _commit(args, env):
    _no_args(args)
    run.commit(TOOL, env)
    return 0


def _discard(args, env):
    _no_args(args)
    run.discard(TOOL, env)
    return 0


COMMANDS = {"--gate": _gate, "--tick": _tick, "--commit-tick": _commit, "--discard-tick": _discard}


def main(argv, env=None):
    env = os.environ if env is None else env
    if not argv or argv[0] not in COMMANDS:
        return _usage()
    try:
        return COMMANDS[argv[0]](list(argv[1:]), env)
    except (ValueError, OSError) as exc:
        sys.stderr.write("sov ingest sessions: %s\n" % exc)
        return EXIT_CONFIG
