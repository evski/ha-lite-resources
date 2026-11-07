"""Constants for Lite Resources."""

DOMAIN = "lite_resources"

CONF_USERS = "users"
CONF_DASHBOARDS = "dashboards"
CONF_ALWAYS_INCLUDE = "always_include"
CONF_INCLUDE_UNSCANNABLE = "include_unscannable"

# Value used in the dashboards selector for the default (Overview) dashboard,
# whose url_path is None.
DEFAULT_DASHBOARD = "__default__"

# The websocket command the frontend uses to fetch the resource list.
WS_RESOURCES = "lovelace/resources"

# Dashboard keys that only work when a "mod" resource is loaded. These mods
# don't provide a card type, so they can't be found from "custom:" types.
# key in dashboard JSON -> substring of the resource URL that provides it.
KEY_HINTS: dict[str, str] = {
    "card_mod": "card-mod",
    "kiosk_mode": "kiosk-mode",
}

SERVICE_PREVIEW = "preview"
