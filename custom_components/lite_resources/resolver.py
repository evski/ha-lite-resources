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
    BASE_ENTITIES,
    CONF_ALWAYS_INCLUDE,
    CONF_DASHBOARDS,
    CONF_EXTRA_ENTITIES,
    CONF_INCLUDE_UNSCANNABLE,
    DEFAULT_DASHBOARD,
    KEY_HINTS,
)

_LOGGER = logging.getLogger(__name__)

# "custom:xxx" anywhere in a dashboard (cards, rows, badges, features, and
# cards nested inside pop-ups, stacks, sections or other cards' options).
_CUSTOM_TYPE = re.compile(r'"custom:([A-Za-z0-9_.\-]+)"')
# A dashed name this file actually registers, not every hyphenated token it
# mentions. Mentions of another card ("button-card" inside an unrelated file)
# must not pull that file in.
_DEFINE_LITERAL = re.compile(
    rb"""customElements\.define\(\s*["'`]([a-z][a-z0-9_]*(?:-[a-z0-9_]+)+)["'`]"""
)
_DEFINE_IDENT = re.compile(
    rb"""customElements\.define\(\s*([A-Za-z_$][A-Za-z0-9_$]{2,40})\s*[,)]"""
)
_ASSIGN = re.compile(
    rb"""(?<![A-Za-z0-9_$])([A-Za-z_$][A-Za-z0-9_$]{0,40})\s*=\s*(["'])([a-z0-9_-]{1,80})\2"""
)
# Mushroom (and similar bundles) build the element name: `${prefix}-light-card`.
_TEMPLATE = re.compile(
    rb"""\$\{([A-Za-z_$][A-Za-z0-9_$]{0,40})\}(-[a-z0-9]+(?:-[a-z0-9]+)*)"""
)
_CONCAT = re.compile(
    rb"""(["'])([a-z0-9_-]+)\1\s*\+\s*(["'])([a-z0-9_-]+)\3"""
)
_CUSTOM_CARD_TYPE = re.compile(
    rb"""type\s*:\s*["']([a-z][a-z0-9_]*(?:-[a-z0-9_]+)+)["']"""
)
# custom:keymaster is implemented by <ll-strategy-dashboard-keymaster>.
_STRATEGY_TYPE = re.compile(
    rb"""ll-strategy-(?:dashboard|view|section)-([a-z0-9]+(?:-[a-z0-9]+)*)"""
)
_QUOTED = re.compile(rb"""["'`]([a-z][a-z0-9_]*(?:-[a-z0-9_]+)+)["'`]""")
_CARDISH = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
# File names that do not identify one card. An unreadable resource with one of
# these names stays under the "include resources that can't be checked" option.
_GENERIC_STEMS = frozenset(
    {
        "app",
        "bundle",
        "card",
        "cards",
        "dist",
        "frontend",
        "index",
        "loader",
        "main",
        "module",
        "plugin",
        "polyfill",
        "resource",
        "resources",
        "script",
        "scripts",
    }
)


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
            found = names_in_javascript(data, _stem_from_filename(candidate))
            self._cache[candidate] = (key, found)
            return found
        return None


def names_in_javascript(data: bytes, stem: str = "") -> frozenset[str]:
    """Return card and strategy types a resource file registers.

    Quoted hyphenated words are not enough. Mushroom's bundle never contains
    the literal ``mushroom-light-card``; it assigns ``prefix = "mushroom"`` and
    defines ``${prefix}-light-card``. Other files mention card names they do
    not provide (a lock card that talks about ``button-card``), and those
    mentions must not count. A constant inside a file whose name is that card
    still counts (``button-card.js`` containing ``"button-card"``).
    """
    found: set[str] = set()
    bindings: dict[str, str] = {}
    for ident, _quote, value in _ASSIGN.findall(data):
        bindings[ident.decode()] = value.decode()

    def consider(name: str) -> None:
        if _CARDISH.match(name):
            found.add(name)

    for literal in _DEFINE_LITERAL.findall(data):
        consider(literal.decode())
    for ident in _DEFINE_IDENT.findall(data):
        consider(bindings.get(ident.decode(), ""))
    for _q1, left, _q2, right in _CONCAT.findall(data):
        consider(left.decode() + right.decode())
    for ident, tail in _TEMPLATE.findall(data):
        base = bindings.get(ident.decode())
        if base is not None:
            consider(base + tail.decode())
    for card_type in _CUSTOM_CARD_TYPE.findall(data):
        consider(card_type.decode())
    for strategy in _STRATEGY_TYPE.findall(data):
        name = strategy.decode()
        if re.fullmatch(r"[a-z][a-z0-9-]+", name):
            found.add(name)
    if len(stem) >= 3 and stem not in _GENERIC_STEMS and "_" not in stem:
        prefix = stem + "-"
        for quoted in _QUOTED.findall(data):
            name = quoted.decode()
            if name == stem or name.startswith(prefix):
                consider(name)
    return frozenset(found)


def _stem_from_filename(path: str) -> str:
    """Stem of a file on disk, ignoring a trailing ``.gz``."""
    name = os.path.basename(path).lower()
    if name.endswith(".gz"):
        name = name[:-3]
    return resource_stem(name)


def resource_stem(url: str) -> str:
    """Return the lower-case file name of a resource without its script suffix."""
    name = os.path.basename(urlsplit(url).path).lower()
    for suffix in (".js", ".mjs"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def types_for_stem(stem: str, needed: set[str]) -> set[str]:
    """Card types a file name itself accounts for.

    The whole stem has to be the type or its leading prefix (``mushroom.js``
    provides ``mushroom-light-card``). A shared piece is not enough, so
    ``dreame-vacuum-card.js`` does not provide ``mushroom-vacuum-card`` and
    ``lock-manager.js`` does not provide ``mushroom-lock-card``.
    """
    if len(stem) < 3 or stem in _GENERIC_STEMS:
        return set()
    if "_" in stem:
        return {name for name in needed if name == stem}
    prefix = stem + "-"
    return {name for name in needed if name == stem or name.startswith(prefix)}


def stem_names_unused_card(stem: str, needed: set[str]) -> bool:
    """True when the file name is a particular card these dashboards don't use.

    Generic names (``frontend.js``) and integration scripts such as
    ``browser_mod.js`` are not specific enough to drop unread.
    """
    if len(stem) < 3 or stem in _GENERIC_STEMS or "_" in stem:
        return False
    if types_for_stem(stem, needed):
        return False
    return "-" in stem or len(stem) >= 6


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


async def async_dashboard_entities(
    hass: HomeAssistant, options: dict[str, Any]
) -> set[str]:
    """Return every entity the configured dashboards can show.

    Any existing entity id that appears anywhere in the dashboards' JSON (cards, pop-ups,
    conditions, actions), the members of any groups among them, the configured extras,
    and a few the frontend uses itself.
    """
    domains = {state.domain for state in hass.states.async_all()}
    if not domains:
        return set()
    pattern = re.compile(
        r"(?<![\w.])(?:"
        + "|".join(sorted(map(re.escape, domains), key=len, reverse=True))
        + r")\.[a-z0-9_]+"
    )
    found: set[str] = set(BASE_ENTITIES) | set(options.get(CONF_EXTRA_ENTITIES, []))
    for key in options.get(CONF_DASHBOARDS, []):
        text = await _async_dashboard_text(hass, key)
        if text:
            found.update(pattern.findall(text))
    # add group members (light groups, old-style groups, ...), recursively
    todo = list(found)
    while todo:
        state = hass.states.get(todo.pop())
        members = state.attributes.get("entity_id") if state else None
        if isinstance(members, (list, tuple)):
            for member in members:
                if isinstance(member, str) and member not in found:
                    found.add(member)
                    todo.append(member)
    return {e for e in found if hass.states.get(e) is not None}


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
        if any(sub in url for sub in hints):
            result.included.append(item)
            continue
        stem = resource_stem(url)
        stem_types = types_for_stem(stem, needed)
        path = url_to_path(hass, url)
        names = (
            await hass.async_add_executor_job(cache.names, path) if path else None
        )
        if names is None:
            # Served by an integration, missing, or remote: contents can't be
            # checked. Keep it unless the file name is a card that isn't used.
            provided |= stem_types
            keep = bool(stem_types) or (
                include_unscannable and not stem_names_unused_card(stem, needed)
            )
            (result.included if keep else result.excluded).append(item)
            continue
        matched = (needed & names) | stem_types
        provided |= matched
        if matched:
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
