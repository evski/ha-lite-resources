"""Config and options flow for Lite Resources."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_ALWAYS_INCLUDE,
    CONF_DASHBOARDS,
    CONF_EXTRA_ENTITIES,
    CONF_FILTER_STATES,
    CONF_INCLUDE_UNSCANNABLE,
    CONF_USERS,
    DEFAULT_DASHBOARD,
    DOMAIN,
)
from .resolver import async_all_resources


def _multi(options: list[SelectOptionDict]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options, multiple=True, mode=SelectSelectorMode.DROPDOWN
        )
    )


async def _async_schema(hass: HomeAssistant, current: dict[str, Any]) -> vol.Schema:
    users = [
        SelectOptionDict(value=u.id, label=u.name or u.id)
        for u in await hass.auth.async_get_users()
        if not u.system_generated and u.is_active
    ]
    dashboards = []
    for url_path, dashboard in hass.data[LOVELACE_DATA].dashboards.items():
        if url_path is None:
            dashboards.append(
                SelectOptionDict(value=DEFAULT_DASHBOARD, label="Overview (default)")
            )
            continue
        title = (getattr(dashboard, "config", None) or {}).get("title") or url_path
        dashboards.append(SelectOptionDict(value=url_path, label=f"{title} ({url_path})"))
    resources = [
        SelectOptionDict(value=r["url"], label=r["url"])
        for r in await async_all_resources(hass)
    ]
    return vol.Schema(
        {
            vol.Required(CONF_USERS, default=current.get(CONF_USERS, [])): _multi(users),
            vol.Required(
                CONF_DASHBOARDS, default=current.get(CONF_DASHBOARDS, [])
            ): _multi(dashboards),
            vol.Optional(
                CONF_ALWAYS_INCLUDE, default=current.get(CONF_ALWAYS_INCLUDE, [])
            ): _multi(resources),
            vol.Required(
                CONF_INCLUDE_UNSCANNABLE,
                default=current.get(CONF_INCLUDE_UNSCANNABLE, True),
            ): BooleanSelector(),
            vol.Required(
                CONF_FILTER_STATES, default=current.get(CONF_FILTER_STATES, False)
            ): BooleanSelector(),
            vol.Optional(
                CONF_EXTRA_ENTITIES, default=current.get(CONF_EXTRA_ENTITIES, [])
            ): EntitySelector(EntitySelectorConfig(multiple=True)),
        }
    )


class LiteResourcesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Lite Resources (single instance)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the light users and their dashboards."""
        if user_input is not None:
            return self.async_create_entry(
                title="Lite Resources", data={}, options=user_input
            )
        return self.async_show_form(
            step_id="user", data_schema=await _async_schema(self.hass, {})
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return LiteResourcesOptionsFlow()


class LiteResourcesOptionsFlow(OptionsFlow):
    """Change the light users, dashboards and extras."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=await _async_schema(self.hass, dict(self.config_entry.options)),
        )
