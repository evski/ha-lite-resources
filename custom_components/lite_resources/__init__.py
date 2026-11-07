"""Lite Resources: load only the dashboard resources a light device needs.

Home Assistant's frontend fetches the full list of dashboard resources (custom
cards and mods) with the "lovelace/resources" websocket command, and loads all
of them on every device. For users chosen here, this integration answers that
command with only the resources their dashboards use. Everyone else gets the
normal, full list.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_USERS, DOMAIN, SERVICE_PREVIEW, WS_RESOURCES
from .resolver import FileCache, async_resolve

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Take over the resources websocket command for the configured users."""
    handlers = hass.data.get(websocket_api.DOMAIN, {})
    original = handlers.get(WS_RESOURCES)
    if original is None:
        raise ConfigEntryNotReady("Dashboards (lovelace) not set up yet")
    original_handler, original_schema = original
    cache = FileCache()

    @websocket_api.websocket_command({vol.Required("type"): WS_RESOURCES})
    @websocket_api.async_response
    async def ws_resources(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        user = connection.user
        if user is None or user.id not in entry.options.get(CONF_USERS, []):
            original_handler(hass, connection, msg)
            return
        try:
            result = await async_resolve(hass, dict(entry.options), cache)
        except Exception:  # never leave a device without its cards
            _LOGGER.exception("Resolving resources failed; sending the full list")
            original_handler(hass, connection, msg)
            return
        if result.unresolved_types:
            _LOGGER.warning(
                "No local resource provides %s for %s; add it under 'Always include' "
                "if those cards fail to load",
                ", ".join(result.unresolved_types),
                user.name,
            )
        _LOGGER.debug(
            "%s gets %d of %d resources",
            user.name,
            len(result.included),
            len(result.included) + len(result.excluded),
        )
        connection.send_result(msg["id"], result.included)

    websocket_api.async_register_command(hass, ws_resources)

    async def preview(call: ServiceCall) -> ServiceResponse:
        result = await async_resolve(hass, dict(entry.options), cache)
        names = []
        for user_id in entry.options.get(CONF_USERS, []):
            user = await hass.auth.async_get_user(user_id)
            names.append(user.name if user else user_id)
        return {"users": names, **result.as_dict()}

    hass.services.async_register(
        DOMAIN, SERVICE_PREVIEW, preview, supports_response=SupportsResponse.ONLY
    )

    def restore() -> None:
        hass.data[websocket_api.DOMAIN][WS_RESOURCES] = (
            original_handler,
            original_schema,
        )
        hass.services.async_remove(DOMAIN, SERVICE_PREVIEW)

    entry.async_on_unload(restore)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed: nothing cached depends on them, but reload to be safe."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload: the on-unload callbacks restore the original command."""
    return True
