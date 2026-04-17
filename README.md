# Sallie Voice Control

Real-time state machine for routing AI voice agent calls across distributed locations via Genesys Cloud. Flip a single boolean in a data table and all inbound calls for a location reroute in under a minute.

---

## What It Does

Two scripts that control Genesys Cloud call routing and AI voice agent availability per location:

**`route_shop_calls.py`** - Routes inbound calls for one or more locations to a central queue or back to the location. Flips the `Outage` boolean in the Genesys routing data table. When `Outage=true`, the IVR sends all calls for that location to the central queue. When `false`, calls route normally.

**`sallie_disable_shops.py`** - Disables the Sallie AI voice agent for specific locations by setting `Enabled=false` in the Genesys configuration data table. Supports dry-run mode.

---

## Usage

```bash
# Check current routing state for one or more locations
python route_shop_calls.py --shops SHOP0247 --status
python route_shop_calls.py --shops "SHOP0247,SHOP0123" --status

# Reroute calls to central queue
python route_shop_calls.py --shops SHOP0247 --direction to-cxc
python route_shop_calls.py --shops "SHOP0247,SHOP0123,247" --direction to-cxc

# Restore normal routing
python route_shop_calls.py --shops "SHOP0247,SHOP0123" --direction to-shop

# Disable the AI voice agent for specific locations (dry run)
python sallie_disable_shops.py --shops 841 853

# Apply the change
python sallie_disable_shops.py --shops 841 853 --execute
```

### Location matching is flexible

All of these match the same location: `SHOP0247`, `CC247`, `247`, `0247`. Name substrings also work: `"north dallas"` matches `SHOP0123 - North Dallas`.

---

## Environment Variables

```
# Genesys Cloud OAuth2
GENESYS_CLIENT_ID=your_client_id
GENESYS_CLIENT_SECRET=your_client_secret
GENESYS_REGION=mypurecloud.com

# Data table IDs (from Genesys Admin > Architect > Data Tables)
GENESYS_ROUTING_TABLE_ID=your-routing-table-uuid
GENESYS_DATATABLE_ID=your-agent-config-table-uuid

# Optional: separate prod/dev table IDs
GENESYS_DATATABLE_ID_PROD=your-prod-table-uuid
GENESYS_DATATABLE_ID_DEV=your-dev-table-uuid
```

---

## How Routing Works

The Genesys IVR flow reads the `Outage` column from the routing data table on every inbound call. No flow republish is needed - data table changes take effect on the next call.

```
Inbound call hits IVR
    |
    v
IVR reads Outage flag from data table
    |
    +-- Outage=true  --> Transfer to central queue
    |
    +-- Outage=false --> Route to location (normal)
```

Changes propagate within one IVR cycle (typically under 60 seconds for the next call).

---

## Architecture Context

Designed to be triggered by AI agents reading the `directives/sallie_control.md` SOP, or by n8n workflows responding to email commands. Part of the [Enterprise AI Automation Platform](https://github.com/Justin2259/enterprise-ai-automation-platform).
