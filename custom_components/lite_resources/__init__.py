"""Lite Resources: make wall panels and other light devices do less work.

For users chosen here (for example the login a wall panel uses):
- Resources: Home Assistant's frontend fetches the full list of dashboard resources (custom
  cards and mods) with the "lovelace/resources" websocket command and loads all of them. This
  integration answers that command with only the resources their dashboards use.
- States (optional): the frontend streams every entity's state with "subscribe_entities". This
  integration limits that stream to the entities their dashboards show.
Everyone else gets Home Assistant's normal behaviour. Nothing is changed on disk.
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
    callback,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entityfilter import convert_include_exclude_filter

from .const import (
    CONF_FILTER_STATES,
    CONF_USERS,
    DOMAIN,
    SERVICE_PREVIEW,
    WS_RESOURCES,
    WS_SUBSCRIBE_ENTITIES,
)
from .resolver import FileCache, async_dashboard_entities, async_resolve

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Take over the resources (and optionally states) commands for the chosen users."""
    handlers = hass.data.get(websocket_api.DOMAIN, {})
    original = handlers.get(WS_RESOURCES)
    original_sub = handlers.get(WS_SUBSCRIBE_ENTITIES)
    if original is None or original_sub is None:
        raise ConfigEntryNotReady("Dashboards (lovelace) not set up yet")
    original_handler, original_schema = original
    sub_handler, sub_schema = original_sub
    cache = FileCache()

    def is_light_user(connection: websocket_api.ActiveConnection) -> bool:
        user = connection.user
        return user is not None and user.id in entry.options.get(CONF_USERS, [])

    @websocket_api.websocket_command({vol.Required("type"): WS_RESOURCES})
    @websocket_api.async_response
    async def ws_resources(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        if not is_light_user(connection):
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
                connection.user.name,
            )
        _LOGGER.debug(
            "%s gets %d of %d resources",
            connection.user.name,
            len(result.included),
            len(result.included) + len(result.excluded),
        )
        connection.send_result(msg["id"], result.included)

    websocket_api.async_register_command(hass, ws_resources)

    @callback
    def ws_subscribe_entities(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        # Only the frontend's unfiltered "all states" subscription is narrowed.
        if (
            not entry.options.get(CONF_FILTER_STATES)
            or not is_light_user(connection)
            or msg.get("entity_ids")
            or not _empty_filter(msg)
        ):
            sub_handler(hass, connection, msg)
            return

        async def narrowed() -> None:
            try:
                entities = await async_dashboard_entities(hass, dict(entry.options))
            except Exception:
                _LOGGER.exception("Working out dashboard entities failed; sending all states")
                entities = set()
            if not entities:
                sub_handler(hass, connection, msg)
                return
            _LOGGER.debug(
                "%s gets states for %d of %d entities",
                connection.user.name,
                len(entities),
                len(hass.states.async_entity_ids()),
            )
            sub_handler(hass, connection, {**msg, "entity_ids": sorted(entities)})

        hass.async_create_task(narrowed(), eager_start=True)

    websocket_api.async_register_command(
        hass, WS_SUBSCRIBE_ENTITIES, ws_subscribe_entities, sub_schema
    )

    async def preview(call: ServiceCall) -> ServiceResponse:
        options = dict(entry.options)
        result = await async_resolve(hass, options, cache)
        names = []
        for user_id in options.get(CONF_USERS, []):
            user = await hass.auth.async_get_user(user_id)
            names.append(user.name if user else user_id)
        response: dict[str, Any] = {"users": names, **result.as_dict()}
        if options.get(CONF_FILTER_STATES):
            entities = await async_dashboard_entities(hass, options)
            response["state_entities"] = sorted(entities)
            response["state_entities_count"] = (
                f"{len(entities)} of {len(hass.states.async_entity_ids())}"
            )
        return response

    hass.services.async_register(
        DOMAIN, SERVICE_PREVIEW, preview, supports_response=SupportsResponse.ONLY
    )

    def restore() -> None:
        commands = hass.data[websocket_api.DOMAIN]
        commands[WS_RESOURCES] = (original_handler, original_schema)
        commands[WS_SUBSCRIBE_ENTITIES] = (sub_handler, sub_schema)
        hass.services.async_remove(DOMAIN, SERVICE_PREVIEW)

    entry.async_on_unload(restore)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


def _empty_filter(msg: dict[str, Any]) -> bool:
    """True if the subscription has no include/exclude filter (the schema adds empty ones)."""
    try:
        return convert_include_exclude_filter(msg).empty_filter
    except (KeyError, TypeError):
        return not any(msg.get(k) for k in ("include", "exclude"))


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed: reload so the new settings apply to new connections."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload: the on-unload callbacks restore the original commands."""
    return True
