"""Work out which dashboard resources a set of dashboards actually needs."""

from __future__ import annotations

from dataclasses import dataclass, field
import gzip
import json
import logging
import os
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_ALWAYS_INCLUDE,
    CONF_DASHBOARDS,
    CONF_INCLUDE_UNSCANNABLE,
    DEFAULT_DASHBOARD,
    KEY_HINTS,
)

_LOGGER = logging.getLogger(__name__)

# "custom:xxx" anywhere in a dashboard (cards, rows, badges, features, and
# cards nested inside pop-ups or other cards' options).
_CUSTOM_TYPE = re.compile(r'"custom:([A-Za-z0-9_.\-]+)"')
# Quoted dashed names in a resource's JavaScript, e.g. "button-card". A card
# type the dashboard needs is "provided" by any file containing it as a literal.
_JS_NAME = re.compile(rb"[\"'`]([a-z][a-z0-9_]*(?:-[a-z0-9_]+)+)[\"'`]")


@dataclass
class Resolution:
    """Outcome of resolving the resources for a set of dashboards."""

    included: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    needed_types: list[str] = field(default_factory=list)
    unresolved_types: list[str] = field(default_factory=list)
    unverified_types: list[str] = field(default_factory=list)
    dashboards: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a summary suitable for a service response."""
        return {
            "dashboards": self.dashboards,
            "needed_types": self.needed_types,
            "unresolved_types": self.unresolved_types,
            "unverified_types": self.unverified_types,
            "included": [r["url"] for r in self.included],
            "excluded": [r["url"] for r in self.excluded],
        }


class FileCache:
    """Cache of the names found in each resource file, keyed by mtime/size."""

    def __init__(self) -> None:
        """Initialise an empty cache."""
        self._cache: dict[str, tuple[tuple[int, int], frozenset[str]]] = {}

    def names(self, path: str) -> frozenset[str] | None:
        """Return the dashed names in a file (runs in the executor)."""
        for candidate, opener in ((path, open), (path + ".gz", gzip.open)):
            try:
                stat = os.stat(candidate)
            except OSError:
                continue
            key = (stat.st_mtime_ns, stat.st_size)
            cached = self._cache.get(candidate)
            if cached and cached[0] == key:
                return cached[1]
            try:
                with opener(candidate, "rb") as fh:
                    data = fh.read()
            except OSError as err:
                _LOGGER.debug("Cannot read %s: %s", candidate, err)
                return None
            found = frozenset(m.decode() for m in _JS_NAME.findall(data))
            self._cache[candidate] = (key, found)
            return found
        return None


def url_to_path(hass: HomeAssistant, url: str) -> str | None:
    """Map a resource URL to a local file, or None if it isn't a local file."""
    path = urlsplit(url).path
    if path.startswith("/local/"):
        base, rel = hass.config.path("www"), path[len("/local/") :]
    elif path.startswith("/hacsfiles/"):
        base, rel = hass.config.path("www", "community"), path[len("/hacsfiles/") :]
    else:
        return None
    full = os.path.normpath(os.path.join(base, unquote(rel)))
    if not full.startswith(base + os.sep):
        return None
    return full


async def async_all_resources(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return every configured dashboard resource, as core would send it."""
    resources = hass.data[LOVELACE_DATA].resources
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    return list(resources.async_items() or [])


async def _async_dashboard_text(hass: HomeAssistant, key: str) -> str | None:
    """Return a dashboard's config as JSON text, or None if unavailable."""
    url_path = None if key == DEFAULT_DASHBOARD else key
    dashboard = hass.data[LOVELACE_DATA].dashboards.get(url_path)
    if dashboard is None:
        _LOGGER.warning("Dashboard %s not found", key)
        return None
    try:
        config = await dashboard.async_load(False)
    except HomeAssistantError:  # includes ConfigNotFound (empty/auto dashboard)
        return None
    return json.dumps(config)


async def async_resolve(
    hass: HomeAssistant, options: dict[str, Any], cache: FileCache
) -> Resolution:
    """Split the resources into those the configured dashboards need and the rest."""
    result = Resolution(dashboards=list(options.get(CONF_DASHBOARDS, [])))
    # Match on the path only: the query string carries a version that changes on updates.
    always = {urlsplit(u).path for u in options.get(CONF_ALWAYS_INCLUDE, [])}
    include_unscannable = options.get(CONF_INCLUDE_UNSCANNABLE, True)

    needed: set[str] = set()
    hints: set[str] = set()
    for key in result.dashboards:
        text = await _async_dashboard_text(hass, key)
        if text is None:
            continue
        needed.update(_CUSTOM_TYPE.findall(text))
        hints.update(sub for k, sub in KEY_HINTS.items() if f'"{k}"' in text)
    result.needed_types = sorted(needed)

    provided: set[str] = set()
    for item in await async_all_resources(hass):
        url = item.get("url", "")
        if urlsplit(url).path in always or item.get("type") == "css":
            result.included.append(item)
            continue
        path = url_to_path(hass, url)
        names = (
            await hass.async_add_executor_job(cache.names, path) if path else None
        )
        if names is None:
            # Served by an integration or remote: contents can't be checked.
            (result.included if include_unscannable else result.excluded).append(item)
            continue
        matched = needed & names
        provided |= matched
        if matched or any(sub in url for sub in hints):
            result.included.append(item)
        else:
            result.excluded.append(item)

    missing = sorted(needed - provided)
    if any(url_to_path(hass, r.get("url", "")) is None for r in result.included):
        # An included resource we couldn't read may well provide these.
        result.unverified_types = missing
    else:
        result.unresolved_types = missing
    return result
