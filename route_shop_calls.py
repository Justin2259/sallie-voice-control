#!/usr/bin/env python3
"""
Route inbound location calls to the central queue or back to the location.

Sets the Outage boolean in the Genesys routing data table. When Outage=true,
the IVR routes all inbound calls for that location to the central queue.
When Outage=false, calls route normally to the location.

Accepts multiple locations as comma-separated values.

Usage:
  # Check current routing state (no changes made)
  py execution/route_shop_calls.py --shops SHOP0247 --status
  py execution/route_shop_calls.py --shops "SHOP0247,SHOP0123" --status

  # Route one or more locations to the central queue
  py execution/route_shop_calls.py --shops SHOP0247 --direction to-cxc
  py execution/route_shop_calls.py --shops "SHOP0247,SHOP0123,247" --direction to-cxc

  # Restore normal routing back to the location
  py execution/route_shop_calls.py --shops "SHOP0247,SHOP0123" --direction to-shop

Matching: location codes are flexible. CC247, SHOP0247, 247, and "0247" all match SHOP0247.
Name substrings also work: "north dallas" matches SHOP0123 - North Dallas.

Environment variables required:
  GENESYS_ROUTING_TABLE_ID - Genesys data table ID for location routing config
"""

import os
import re
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TABLE_SHOP_INFO = os.environ.get("GENESYS_ROUTING_TABLE_ID", "")


# ---------------------------------------------------------------------------
# Data table helpers
# ---------------------------------------------------------------------------

def fetch_all_shop_rows(session, base_url):
    """Fetch all rows from the Shop Info data table, handling pagination."""
    rows = []
    page = 1
    while True:
        r = session.get(
            f"{base_url}/api/v2/flows/datatables/{TABLE_SHOP_INFO}/rows",
            params={"showbrief": "false", "pageSize": 500, "pageNumber": page},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        entities = data.get("entities", [])
        rows.extend(entities)
        if page >= data.get("pageCount", 1):
            break
        page += 1
    return rows


def get_table_row(session, base_url, key):
    """GET a single Shop Info row by DID key. Returns row dict or None."""
    r = session.get(
        f"{base_url}/api/v2/flows/datatables/{TABLE_SHOP_INFO}/rows/{key}",
        params={"showbrief": "false"},
        timeout=30,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def update_table_row(session, base_url, key, row):
    """PUT a full row back to the data table. Returns updated row or None."""
    r = session.put(
        f"{base_url}/api/v2/flows/datatables/{TABLE_SHOP_INFO}/rows/{key}",
        json=row,
        timeout=30,
    )
    if not r.ok:
        return None, f"{r.status_code}: {r.text[:300]}"
    return r.json(), None


# ---------------------------------------------------------------------------
# Shop matching
# ---------------------------------------------------------------------------

def normalize_shop_input(raw):
    """
    Normalize a shop input token to a 4-digit zero-padded number string if
    it looks numeric or has a CC prefix. Returns the stripped digits (e.g. "0247")
    or None if it is a name-based query.

    Examples:
      "SHOP0247"  -> "0247"
      "CC247"   -> "0247"
      "247"     -> "0247"
      "0247"    -> "0247"
      "oak cliff" -> None  (name search)
    """
    s = raw.strip()
    # Strip leading CC/cc prefix
    without_prefix = re.sub(r"^[Cc]{2}", "", s).strip()
    digits = re.sub(r"\D", "", without_prefix)
    if digits and (digits == without_prefix.strip() or s.upper().startswith("CC")):
        return digits.zfill(4)
    return None


def match_shop(rows, query):
    """
    Find rows matching a query string.
    Returns (list_of_matches, match_type) where match_type is 'exact', 'numeric', or 'name'.
    """
    padded = normalize_shop_input(query)
    if padded:
        prefix = f"CC{padded}"
        matches = [r for r in rows if r.get("Shop", "").upper().startswith(prefix)]
        return matches, "numeric"

    # Name substring fallback
    q = query.strip().upper()
    matches = [r for r in rows if q in r.get("Shop", "").upper()]
    return matches, "name"


# ---------------------------------------------------------------------------
# Core routing logic
# ---------------------------------------------------------------------------

def process_shop(session, base_url, query, desired_outage, status_only):
    """
    Process a single shop query.
    Returns a result dict: {shop, did, old_state, new_state, status, message}
    """
    result = {
        "query": query,
        "shop": "",
        "did": "",
        "old_state": None,
        "new_state": None,
        "status": "FAIL",
        "message": "",
    }

    # Load fresh row from pre-fetched list happens in caller; here we do the update
    return result


def run(shops_input, desired_outage, status_only, env):
    cid, csec, region = get_credentials_for_env(env)
    auth = get_access_token(client_id=cid, client_secret=csec, region=region)
    if not auth["success"]:
        print(f"[FAIL] Auth: {auth.get('error')}")
        sys.exit(1)

    base_url = get_api_base(auth["region"])
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {auth['access_token']}",
        "Content-Type": "application/json",
    })

    if not TABLE_SHOP_INFO:
        print("[FAIL] GENESYS_ROUTING_TABLE_ID not set in .env")
        sys.exit(1)

    print(f"Loading location list from Genesys ({env})...")
    all_rows = fetch_all_shop_rows(session, base_url)
    print(f"  {len(all_rows)} locations loaded\n")

    # Parse comma-separated shop list
    queries = [q.strip() for q in shops_input.split(",") if q.strip()]

    results = []
    for query in queries:
        matches, _ = match_shop(all_rows, query)

        if len(matches) == 0:
            results.append({
                "query": query,
                "shop": "(no match)",
                "did": "",
                "old_state": None,
                "new_state": None,
                "status": "FAIL",
                "message": f"No shop found matching '{query}'",
            })
            continue

        if len(matches) > 1:
            names = ", ".join(m.get("Shop", "") for m in matches)
            results.append({
                "query": query,
                "shop": "(ambiguous)",
                "did": "",
                "old_state": None,
                "new_state": None,
                "status": "FAIL",
                "message": f"'{query}' matched {len(matches)} shops: {names}. Be more specific.",
            })
            continue

        row = matches[0]
        did = row.get("key", "")
        shop_name = row.get("Shop", "")
        old_outage = row.get("Outage", False)

        if status_only:
            routing = "-> CXC" if old_outage else "-> Shop (normal)"
            results.append({
                "query": query,
                "shop": shop_name,
                "did": did,
                "old_state": old_outage,
                "new_state": None,
                "status": "OK",
                "message": f"Current routing: {routing}",
            })
            continue

        # Fetch the full row fresh before updating
        full_row = get_table_row(session, base_url, did)
        if full_row is None:
            results.append({
                "query": query,
                "shop": shop_name,
                "did": did,
                "old_state": old_outage,
                "new_state": None,
                "status": "FAIL",
                "message": "Could not fetch row for update (404)",
            })
            continue

        full_row["Outage"] = desired_outage
        updated, err = update_table_row(session, base_url, did, full_row)

        if err:
            results.append({
                "query": query,
                "shop": shop_name,
                "did": did,
                "old_state": old_outage,
                "new_state": None,
                "status": "FAIL",
                "message": f"PUT failed: {err}",
            })
        else:
            results.append({
                "query": query,
                "shop": shop_name,
                "did": did,
                "old_state": old_outage,
                "new_state": desired_outage,
                "status": "OK",
                "message": "",
            })

    # ---------------------------------------------------------------------------
    # Print results table
    # ---------------------------------------------------------------------------
    print("-" * 80)
    if status_only:
        print(f"{'Shop':<35} {'DID':<12} {'Routing':<20} {'Result'}")
    else:
        action_label = "to CXC" if desired_outage else "to Shop"
        print(f"Routing {len(queries)} shop(s) {action_label}")
        print(f"{'Shop':<35} {'DID':<12} {'Change':<25} {'Result'}")
    print("-" * 80)

    ok_count = 0
    fail_count = 0
    for r in results:
        shop_col = r["shop"][:34]
        did_col = r["did"] or ""

        if r["status"] == "FAIL":
            fail_count += 1
            print(f"{shop_col:<35} {did_col:<12} {'':<25} [FAIL] {r['message']}")
            continue

        ok_count += 1
        if status_only:
            routing_col = ("-> CXC" if r["old_state"] else "-> Shop (normal)")
            print(f"{shop_col:<35} {did_col:<12} {routing_col:<20} [OK]")
        else:
            old_label = "CXC" if r["old_state"] else "Shop"
            new_label = "CXC" if r["new_state"] else "Shop"
            if r["old_state"] == r["new_state"]:
                change_col = f"already -> {new_label}"
            else:
                change_col = f"{old_label} -> {new_label}"
            print(f"{shop_col:<35} {did_col:<12} {change_col:<25} [OK]")

    print("-" * 80)
    print(f"Done: {ok_count} OK, {fail_count} failed\n")

    if fail_count > 0 and ok_count == 0:
        sys.exit(1)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Route shop inbound calls to CXC or back to the shop."
    )
    parser.add_argument(
        "--shops",
        required=True,
        help="Comma-separated shop codes or names (e.g. 'SHOP0247,SHOP0123' or '247,123' or 'oak cliff')",
    )
    parser.add_argument(
        "--direction",
        choices=["to-cxc", "to-shop"],
        help="Routing direction: to-cxc sets Outage=true, to-shop sets Outage=false",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current routing state without making any changes",
    )
    parser.add_argument(
        "--env",
        default="prod",
        choices=["prod", "dev"],
        help="Target Genesys org (default: prod)",
    )
    args = parser.parse_args()

    if not args.status and not args.direction:
        print("[FAIL] Provide either --direction (to-cxc or to-shop) or --status.")
        sys.exit(1)

    desired_outage = None
    if args.direction == "to-cxc":
        desired_outage = True
    elif args.direction == "to-shop":
        desired_outage = False

    run(args.shops, desired_outage, args.status, args.env)


if __name__ == "__main__":
    main()

# revised

# rev 1

# rev 3

# rev 4
