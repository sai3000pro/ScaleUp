"""Write the server's published OpenAPI schema to the frontend, where the client
types are generated from it.

    python scripts/export_openapi.py            # writes frontend/lib/openapi.json
    python scripts/export_openapi.py --check    # exit 1 when the committed file is stale

Deterministic (sorted keys, fixed indentation) so the committed file only changes
when the contract does. Run from the repo root with the backend venv active, then
`npm run build:api-types` in frontend/ to regenerate `lib/apiSchema.ts`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "frontend" / "lib" / "openapi.json"
sys.path.insert(0, str(REPO_ROOT / "backend"))


def render() -> str:
    from app.main import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


# @spec OPS-CONTRACT-003
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail when the committed schema is stale")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print(f"{TARGET.relative_to(REPO_ROOT)} is stale; run scripts/export_openapi.py", file=sys.stderr)
            return 1
        print("openapi.json is current")
        return 0
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
