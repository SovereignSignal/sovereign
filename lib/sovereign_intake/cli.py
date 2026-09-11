import argparse
import json
import os
from pathlib import Path
import sys

from . import client, collector, importer, server
from .common import IntakeError, json_read


def main():
    parser = argparse.ArgumentParser(description="Selected contribution intake. No brain read wire.")
    parser.add_argument("command", choices=["assess", "init", "run", "status", "import", "init-server", "serve"])
    parser.add_argument("--config", default=str(Path(os.environ.get("SOV_STATE_DIR", "~/.local/state/sovereign")).expanduser() / "connectors.json"))
    parser.add_argument("--client")
    parser.add_argument("--repo")
    parser.add_argument("--name")
    parser.add_argument("--email")
    parser.add_argument("--root")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--receive-only", action="store_true")
    args = parser.parse_args()
    try:
        path = Path(args.config).expanduser().absolute()
        state_dir = path.parent
        if args.command == "serve":
            server.serve(args.repo, args.name)
            return 0
        if args.command == "init-server":
            result = server.init(args.repo) if args.apply else {"state": "dry-run", "action": "initialize-independent-intake", "writes": False}
        else:
            manifest = json_read(path)
            if not isinstance(manifest, dict):
                raise IntakeError("connector_manifest_required")
            if args.command == "import":
                if (manifest.get("machine") or {}).get("role") != "hub":
                    raise IntakeError("explicit_hub_role_required")
                config = dict(manifest["intakes"][args.client], client_id=args.client)
                root = args.root or (Path.home() / ".brain-root").read_text().strip()
                result = importer.import_client(config, state_dir, root, args.apply, args.receive_only)
            else:
                if (manifest.get("machine") or {}).get("role") != "client" or (manifest.get("machine") or {}).get("mode") != "contribute-only":
                    raise IntakeError("explicit_contribute_only_role_required")
                config = manifest["intake"]
                if args.command == "assess":
                    result = collector.assess(config)
                    result.pop("items")  # Assessment reports selection without source bodies.
                elif args.command == "status":
                    result = json_read(state_dir / "contribution.json", {"state": "not-run"})
                elif args.command == "init":
                    result = client.init_spool(config, args.name, args.email) if args.apply else {"state": "dry-run", "action": "initialize-independent-spool", "writes": False}
                else:
                    result = client.run(config, state_dir) if args.apply else {"state": "dry-run", "action": "collect-and-deliver", "writes": False, "network": False}
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok", True) else 1
    except (IntakeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, IntakeError) else "invalid_configuration_or_io_failure"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
