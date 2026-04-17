#!/usr/bin/env python3
"""
Set Sallie.AI Enabled=false for specific shops in the Genesys datatable.

Matches rows by shop number extracted from the Location field
(e.g. "0841 - NORTH DALLAS" -> "0841").

Usage:
  # Dry-run (default)
  py execution/sallie_disable_shops.py --shops 841 853

  # Execute
  py execution/sallie_disable_shops.py --shops 841 853 --execute
"""
import os
import sys
import json
import argparse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

try:
    import requests
except ImportError:
    print("[FAIL] pip install requests")
    sys.exit(1)

from genesys_auth import get_access_token, get_api_base, get_credentials_for_env


def scan_table_rows(session, base_url, table_id):
    """Return all rows from a data table."""
    rows = []
    page = 1
    while True:
        r = session.get(
            f"{base_url}/api/v2/flows/datatables/{table_id}/rows",
            params={"pageSize": 500, "pageNumber": page, "showbrief": "false"},
            timeout=30
        )
        if not r.ok:
            print(f"[WARN] Could not scan table {table_id}: {r.status_code} {r.text[:200]}")
            break
        data = r.json()
        rows.extend(data.get("entities", []))
        if page >= data.get("pageCount", 1):
            break
        page += 1
    return rows


def extract_shop_number(location_str):
    """Extract 4-digit shop number from Location field.
    e.g. '0841 - NORTH DALLAS' -> '0841'
    """
    if not location_str:
        return None
    part = location_str.strip().split(" ")[0].strip()
    return part if part.isdigit() else None


def main():
    parser = argparse.ArgumentParser(description="Disable Sallie.AI for specific shops")
    parser.add_argument("--shops", required=True, nargs="+",
                        help="Shop numbers to disable (e.g. 841 853)")
    parser.add_argument("--execute", action="store_true",
                        help="Apply changes. Omit for dry-run.")
    parser.add_argument("--env", default="prod", choices=["prod", "dev"],
                        help="Target org (default: prod)")
    args = parser.parse_args()

    dry_run = not args.execute

    # Normalize shop numbers to zero-padded 4 digits
    target_shops = set(str(s).zfill(4) for s in args.shops)

    env_suffix = "_DEV" if args.env == "dev" else "_PROD"
    table_id = os.getenv(f"GENESYS_DATATABLE_ID{env_suffix}") or os.getenv("GENESYS_DATATABLE_ID")
    if not table_id:
        print(f"[FAIL] GENESYS_DATATABLE_ID{env_suffix} not set in .env")
        sys.exit(1)

    if dry_run:
        print("[DRY RUN] No changes will be made. Pass --execute to apply.")
    print(f"Target shops: {', '.join(sorted(target_shops))}")
    print(f"Datatable ID: {table_id}")
    print()

    cid, csec, region = get_credentials_for_env(args.env)
    auth = get_access_token(client_id=cid, client_secret=csec, region=region)
    if not auth["success"]:
        print(f"[FAIL] Auth: {auth['error']}")
        sys.exit(1)

    base_url = get_api_base(auth["region"])
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {auth['access_token']}",
        "Content-Type": "application/json"
    })

    print("Scanning datatable rows...")
    rows = scan_table_rows(session, base_url, table_id)
    print(f"Found {len(rows)} total rows.")
    print()

    matched = []
    for row in rows:
        location = row.get("Location") or row.get("location") or ""
        shop_num = extract_shop_number(location)
        if shop_num and shop_num in target_shops:
            matched.append(row)

    if not matched:
        print("[WARN] No rows matched the given shop numbers.")
        print("Sample Location values from the table:")
        for row in rows[:5]:
            loc = row.get("Location") or row.get("location") or "(no Location field)"
            print(f"  key={row.get('key')}  Location={loc!r}")
        sys.exit(1)

    print(f"Matched {len(matched)} row(s):")
    for row in matched:
        location = row.get("Location") or row.get("location") or ""
        enabled = row.get("Enabled")
        print(f"  key={row.get('key')}  Location={location!r}  Enabled={enabled}")
    print()

    results = []
    for row in matched:
        key = row.get("key")
        location = row.get("Location") or row.get("location") or ""

        if dry_run:
            print(f"[DRY RUN] Would set Enabled=false for key={key} ({location})")
            results.append({"key": key, "location": location, "status": "dry-run"})
            continue

        updated_row = dict(row)
        updated_row["Enabled"] = False

        r = session.put(
            f"{base_url}/api/v2/flows/datatables/{table_id}/rows/{key}",
            json=updated_row,
            timeout=30
        )

        if r.ok:
            print(f"[OK] Disabled Sallie for key={key} ({location})")
            results.append({"key": key, "location": location, "status": "disabled"})
        else:
            print(f"[FAIL] key={key} ({location}): {r.status_code} {r.text[:200]}")
            results.append({"key": key, "location": location, "status": f"error {r.status_code}"})

    print()
    if dry_run:
        print("DRY RUN COMPLETE. Re-run with --execute to apply.")
    else:
        success = sum(1 for r in results if r["status"] == "disabled")
        failed  = sum(1 for r in results if r["status"].startswith("error"))
        print(f"COMPLETE. {success} disabled, {failed} failed.")


if __name__ == "__main__":
    main()

# revised

# rev 2

# rev 5
