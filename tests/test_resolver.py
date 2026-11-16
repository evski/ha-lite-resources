"""Resource matching for the dashboards a light user actually opens.

The cases come from a wall panel that loaded two unused card files and
skipped Mushroom, which its dashboards do use. Card types are nested the
way a sections dashboard, a stack, auto-entities and a browser_mod popup
store them. One of the two dashboards is not linked from anywhere.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


def _install_homeassistant_stubs() -> None:
    """Allow importing the resolver without a Home Assistant checkout."""
    if "homeassistant.components.lovelace.const" in sys.modules:
        return
    modules = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.components": types.ModuleType("homeassistant.components"),
        "homeassistant.components.lovelace": types.ModuleType(
            "homeassistant.components.lovelace"
        ),
        "homeassistant.components.lovelace.const": types.ModuleType(
            "homeassistant.components.lovelace.const"
        ),
        "homeassistant.core": types.ModuleType("homeassistant.core"),
        "homeassistant.exceptions": types.ModuleType("homeassistant.exceptions"),
    }
    for name, module in modules.items():
        sys.modules.setdefault(name, module)

    class HomeAssistantError(Exception):
        """Stand-in for the core error the resolver already catches."""

    sys.modules["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    sys.modules["homeassistant.components.lovelace.const"].LOVELACE_DATA = "lovelace"
    sys.modules["homeassistant.core"].HomeAssistant = object


_install_homeassistant_stubs()

ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = ROOT / "custom_components" / "lite_resources"


def _load(module_name: str, filename: str):
    """Load one integration module without running the package __init__."""
    package = sys.modules.setdefault("lite_resources", types.ModuleType("lite_resources"))
    package.__path__ = [str(_PACKAGE)]
    package.__package__ = "lite_resources"
    spec = importlib.util.spec_from_file_location(module_name, _PACKAGE / filename)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "lite_resources"
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_const = _load("lite_resources.const", "const.py")
_resolver = _load("lite_resources.resolver", "resolver.py")

CONF_ALWAYS_EXCLUDE = _const.CONF_ALWAYS_EXCLUDE
CONF_ALWAYS_INCLUDE = _const.CONF_ALWAYS_INCLUDE
CONF_DASHBOARDS = _const.CONF_DASHBOARDS
CONF_INCLUDE_UNSCANNABLE = _const.CONF_INCLUDE_UNSCANNABLE
DEFAULT_DASHBOARD = _const.DEFAULT_DASHBOARD
FileCache = _resolver.FileCache
async_resolve = _resolver.async_resolve
names_in_javascript = _resolver.names_in_javascript

LOVELACE_DATA = "lovelace"

MUSHROOM_JS = b"""
var gg;
Eg = () => { gg = "mushroom"; };
Ek = `${$k = `${gg}-light-card`}-editor`;
customElements.define($k, class extends HTMLElement {});
var entity = `${gg}-entity-card`;
var vacuum = `${gg}-vacuum-card`;
var lock = `${gg}-lock-card`;
// A real bundle also concatenates a couple of names.
var legacy = "mushroom" + "-legacy-template-card";
"""

BUTTON_CARD_JS = b"""
const BUTTON_CARD_NAME = "button-card";
class ButtonCard extends HTMLElement {}
customElements.define(BUTTON_CARD_NAME, ButtonCard);
"""

# Names an unused card, and mentions cards the dashboards do use. The mention
# must not be treated as providing those cards.
LOCK_MANAGER_JS = b"""
const OTHER = ["button-card", "mushroom-lock-card", "vacuum-card", "more-info"];
customElements.define("lock-manager", class extends HTMLElement {});
"""

DREAME_JS = b"""
const ys = "dreame-vacuum-card";
const ks = "dreame-vacuum-card-editor";
// Shared fragments of other cards. Not this file's element.
const pieces = ["vacuum-card", "lock-card", "mushroom-vacuum-card"];
"""

STACK_IN_CARD_JS = b"""
const CARD_NAME = "stack-in-card";
customElements.define(CARD_NAME, class extends HTMLElement {});
"""

CARD_MOD_JS = b"/* card-mod stylesheets have no custom element */\n"

KEYMASTER_JS = b"""
if (!customElements.get("ll-strategy-dashboard-keymaster")) {
  customElements.define("ll-strategy-dashboard-keymaster", class extends HTMLElement {});
}
"""


def _panel_dashboard() -> dict:
    """Dashboard linked in the sidebar. No Mushroom cards."""
    return {
        "title": "Panel",
        "views": [
            {
                "title": "Home",
                "cards": [
                    {
                        "type": "vertical-stack",
                        "cards": [
                            {
                                "type": "custom:button-card",
                                "entity": "light.hall",
                                "card_mod": {"style": "ha-card { }"},
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _hidden_dashboard() -> dict:
    """Second dashboard, reached with browser_mod.navigate and not linked."""
    return {
        "title": "Hidden",
        "views": [
            {
                "title": "Rooms",
                "type": "sections",
                "sections": [
                    {
                        "type": "grid",
                        "cards": [
                            {
                                "type": "vertical-stack",
                                "cards": [
                                    {
                                        "type": "conditional",
                                        "conditions": [
                                            {"entity": "light.kitchen", "state": "on"}
                                        ],
                                        "card": {
                                            "type": "custom:mushroom-light-card",
                                            "entity": "light.kitchen",
                                        },
                                    },
                                    {
                                        "type": "horizontal-stack",
                                        "cards": [
                                            {
                                                "type": "custom:mushroom-entity-card",
                                                "entity": "sensor.kitchen",
                                            }
                                        ],
                                    },
                                ],
                            },
                            {
                                "type": "custom:auto-entities",
                                "card": {"type": "custom:mushroom-entity-card"},
                                "card_param": "cards",
                                "filter": {"include": [{"domain": "light"}]},
                            },
                        ],
                    }
                ],
            },
            {
                "title": "Locks",
                "cards": [
                    {
                        "type": "custom:mushroom-vacuum-card",
                        "entity": "vacuum.downstairs",
                        "tap_action": {
                            "action": "fire-dom-event",
                            "browser_mod": {
                                "service": "browser_mod.popup",
                                "data": {
                                    "content": {
                                        "type": "custom:mushroom-lock-card",
                                        "entity": "lock.front",
                                    }
                                },
                            },
                        },
                    }
                ],
            },
        ],
    }


class _Dashboard:
    def __init__(self, config: dict | None, fail: bool = False) -> None:
        self.config = config
        self.fail = fail

    async def async_load(self, force: bool) -> dict:
        if self.fail:
            raise sys.modules["homeassistant.exceptions"].HomeAssistantError("empty")
        return self.config or {}


class _Resources:
    def __init__(self, items: list[dict]) -> None:
        self.loaded = True
        self._items = items

    async def async_load(self) -> None:
        self.loaded = True

    def async_items(self) -> list[dict]:
        return list(self._items)


class _Config:
    def __init__(self, root: str) -> None:
        self._root = root

    def path(self, *parts: str) -> str:
        return os.path.join(self._root, *parts)


class _Hass:
    def __init__(self, root: str, dashboards: dict, resources: list[dict]) -> None:
        self.config = _Config(root)
        self.data = {
            LOVELACE_DATA: types.SimpleNamespace(
                dashboards=dashboards,
                resources=_Resources(resources),
            )
        }

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _write(root: str, relative: str, payload: bytes) -> None:
    path = Path(root, "www", "community", relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


class NamesInJavascriptTest(unittest.TestCase):
    """Card names recovered from a resource file."""

    def test_mushroom_template_names_are_card_types(self) -> None:
        """prefix = "mushroom" and `${prefix}-light-card` is that card."""
        names = names_in_javascript(MUSHROOM_JS, "mushroom")
        for card in (
            "mushroom-light-card",
            "mushroom-entity-card",
            "mushroom-vacuum-card",
            "mushroom-lock-card",
            "mushroom-legacy-template-card",
        ):
            self.assertIn(card, names)

    def test_mentions_of_other_cards_are_not_registrations(self) -> None:
        """A lock-manager file that quotes button-card does not provide it."""
        names = names_in_javascript(LOCK_MANAGER_JS, "lock-manager")
        self.assertIn("lock-manager", names)
        self.assertNotIn("button-card", names)
        self.assertNotIn("mushroom-lock-card", names)
        self.assertNotIn("vacuum-card", names)

    def test_dreame_file_does_not_claim_mushroom_cards(self) -> None:
        """dreame-vacuum-card.js is not a provider of mushroom-vacuum-card."""
        names = names_in_javascript(DREAME_JS, "dreame-vacuum-card")
        self.assertIn("dreame-vacuum-card", names)
        self.assertNotIn("mushroom-vacuum-card", names)
        self.assertNotIn("vacuum-card", names)
        self.assertNotIn("lock-card", names)

    def test_strategy_element_provides_the_strategy_type(self) -> None:
        """ll-strategy-dashboard-keymaster is the custom:keymaster strategy."""
        names = names_in_javascript(KEYMASTER_JS, "keymaster")
        self.assertIn("keymaster", names)

    def test_define_identifier_is_resolved(self) -> None:
        """vertical-stack-in-card.js registers stack-in-card via a constant."""
        names = names_in_javascript(STACK_IN_CARD_JS, "vertical-stack-in-card")
        self.assertIn("stack-in-card", names)


class ResolveResourcesTest(unittest.IsolatedAsyncioTestCase):
    """Which resource URLs a light user is sent."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _write(self.root, "lovelace-mushroom/mushroom.js", MUSHROOM_JS)
        # Same bundle under a generic file name: only the script contents match.
        _write(self.root, "lovelace-mushroom/cards.js", MUSHROOM_JS)
        _write(self.root, "button-card/button-card.js", BUTTON_CARD_JS)
        _write(self.root, "lock-manager/lock-manager.js", LOCK_MANAGER_JS)
        _write(self.root, "dreame-vacuum-card/dreame-vacuum-card.js", DREAME_JS)
        _write(self.root, "lovelace-card-mod/card-mod.js", CARD_MOD_JS)
        _write(
            self.root,
            "vertical-stack-in-card/vertical-stack-in-card.js",
            STACK_IN_CARD_JS,
        )
        self.resources = [
            {"url": "/hacsfiles/lovelace-mushroom/mushroom.js", "type": "module"},
            {"url": "/hacsfiles/lovelace-mushroom/cards.js", "type": "module"},
            {"url": "/hacsfiles/button-card/button-card.js?v=9", "type": "module"},
            {"url": "/hacsfiles/lock-manager/lock-manager.js", "type": "module"},
            {
                "url": "/hacsfiles/dreame-vacuum-card/dreame-vacuum-card.js",
                "type": "module",
            },
            {"url": "/hacsfiles/lovelace-card-mod/card-mod.js", "type": "module"},
            {
                "url": "/hacsfiles/vertical-stack-in-card/vertical-stack-in-card.js",
                "type": "module",
            },
            # Integration scripts that are not files under /local or /hacsfiles.
            {"url": "/dreame_vacuum/frontend.js?v=abc123", "type": "module"},
            {"url": "/browser_mod.js", "type": "module"},
            {"url": "https://cdn.example/lock-manager.js", "type": "module"},
            {"url": "https://cdn.example/dreame-vacuum-card.js", "type": "module"},
            {"url": "/keymaster_files/keymaster.js", "type": "module"},
        ]
        self.dashboards = {
            "panel": _Dashboard(_panel_dashboard()),
            "hidden": _Dashboard(_hidden_dashboard()),
            None: _Dashboard({"views": []}),
        }

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    def _hass(self) -> _Hass:
        return _Hass(self.root, self.dashboards, self.resources)

    async def _resolve(self, **options) -> dict:
        base = {
            CONF_DASHBOARDS: ["panel", "hidden"],
            CONF_INCLUDE_UNSCANNABLE: True,
        }
        base.update(options)
        result = await async_resolve(self._hass(), base, FileCache())
        return result.as_dict()

    async def test_mushroom_is_included_and_unused_cards_are_not(self) -> None:
        """Mushroom cards on the hidden dashboard load mushroom.js only."""
        summary = await self._resolve()
        included = set(summary["included"])
        excluded = set(summary["excluded"])

        self.assertIn("/hacsfiles/lovelace-mushroom/mushroom.js", included)
        self.assertIn("/hacsfiles/lovelace-mushroom/cards.js", included)
        self.assertIn("/hacsfiles/button-card/button-card.js?v=9", included)
        self.assertIn("/hacsfiles/lovelace-card-mod/card-mod.js", included)
        self.assertIn("/browser_mod.js", included)
        # Generic integration URL: the file name is not the card name.
        self.assertIn("/dreame_vacuum/frontend.js?v=abc123", included)

        for url in (
            "/hacsfiles/lock-manager/lock-manager.js",
            "/hacsfiles/dreame-vacuum-card/dreame-vacuum-card.js",
            "https://cdn.example/lock-manager.js",
            "https://cdn.example/dreame-vacuum-card.js",
            "/keymaster_files/keymaster.js",
            "/hacsfiles/vertical-stack-in-card/vertical-stack-in-card.js",
        ):
            self.assertIn(url, excluded, url)
            self.assertNotIn(url, included, url)

        for card in (
            "mushroom-light-card",
            "mushroom-entity-card",
            "mushroom-vacuum-card",
            "mushroom-lock-card",
            "button-card",
        ):
            self.assertIn(card, summary["needed_types"])
            self.assertNotIn(card, summary["unresolved_types"])
        self.assertNotIn("dreame-vacuum-card", summary["needed_types"])
        self.assertNotIn("lock-manager", summary["needed_types"])

    async def test_hidden_dashboard_is_scanned_when_configured(self) -> None:
        """A dashboard nothing links to is still read if it is configured."""
        both = await self._resolve()
        self.assertEqual(both["dashboards"], ["panel", "hidden"])
        self.assertIn("/hacsfiles/lovelace-mushroom/mushroom.js", both["included"])

        panel_only = await self._resolve(**{CONF_DASHBOARDS: ["panel"]})
        self.assertNotIn(
            "/hacsfiles/lovelace-mushroom/mushroom.js", panel_only["included"]
        )
        self.assertIn(
            "/hacsfiles/button-card/button-card.js?v=9", panel_only["included"]
        )

    async def test_nested_mushroom_cards_are_seen(self) -> None:
        """Stacks, sections, auto-entities and a popup all contribute types."""
        summary = await self._resolve(**{CONF_DASHBOARDS: ["hidden"]})
        self.assertCountEqual(
            summary["needed_types"],
            [
                "auto-entities",
                "mushroom-entity-card",
                "mushroom-light-card",
                "mushroom-lock-card",
                "mushroom-vacuum-card",
            ],
        )
        # auto-entities has no resource here. An unreadable integration script is
        # also included, so the missing type is reported as unverified.
        self.assertEqual(summary["unverified_types"], ["auto-entities"])
        self.assertEqual(summary["unresolved_types"], [])
        self.assertIn("/hacsfiles/lovelace-mushroom/mushroom.js", summary["included"])

    async def test_unreadable_mushroom_url_is_kept_by_its_file_name(self) -> None:
        """A remote mushroom.js still matches custom:mushroom-*-card."""
        self.resources.append(
            {"url": "https://cdn.example/mushroom.js", "type": "module"}
        )
        summary = await self._resolve(**{CONF_INCLUDE_UNSCANNABLE: False})
        self.assertIn("https://cdn.example/mushroom.js", summary["included"])
        self.assertNotIn("/browser_mod.js", summary["included"])

    async def test_strategy_resource_follows_the_strategy_type(self) -> None:
        """custom:keymaster keeps keymaster.js; an unused strategy does not."""
        self.dashboards["locks"] = _Dashboard(
            {"strategy": {"type": "custom:keymaster"}}
        )
        used = await self._resolve(**{CONF_DASHBOARDS: ["locks"]})
        self.assertIn("keymaster", used["needed_types"])
        self.assertIn("/keymaster_files/keymaster.js", used["included"])

    async def test_dashboard_that_fails_to_load_does_not_drop_the_other(self) -> None:
        """One unreadable dashboard does not hide cards on the other."""
        self.dashboards["hidden"] = _Dashboard(None, fail=True)
        summary = await self._resolve()
        self.assertIn("/hacsfiles/button-card/button-card.js?v=9", summary["included"])
        self.assertNotIn(
            "/hacsfiles/lovelace-mushroom/mushroom.js", summary["included"]
        )

    async def test_always_exclude_drops_a_generic_integration_script(self) -> None:
        """Always exclude removes a resource the matcher would otherwise send."""
        summary = await self._resolve(
            **{
                CONF_ALWAYS_EXCLUDE: ["/dreame_vacuum/frontend.js?v=old"],
                CONF_ALWAYS_INCLUDE: ["/dreame_vacuum/frontend.js"],
            }
        )
        self.assertIn("/dreame_vacuum/frontend.js?v=abc123", summary["excluded"])
        self.assertNotIn("/dreame_vacuum/frontend.js?v=abc123", summary["included"])
        self.assertIn("/hacsfiles/lovelace-mushroom/mushroom.js", summary["included"])

    async def test_always_exclude_can_drop_a_card_the_dashboard_uses(self) -> None:
        """Excluding mushroom.js leaves its card types unresolved."""
        summary = await self._resolve(
            **{
                CONF_DASHBOARDS: ["hidden"],
                CONF_INCLUDE_UNSCANNABLE: False,
                CONF_ALWAYS_EXCLUDE: ["/hacsfiles/lovelace-mushroom/mushroom.js"],
            }
        )
        self.assertNotIn(
            "/hacsfiles/lovelace-mushroom/mushroom.js", summary["included"]
        )
        # cards.js is the same bundle under another name, so the types are met.
        self.assertIn("/hacsfiles/lovelace-mushroom/cards.js", summary["included"])
        self.assertNotIn("mushroom-light-card", summary["unresolved_types"])

        summary = await self._resolve(
            **{
                CONF_DASHBOARDS: ["hidden"],
                CONF_INCLUDE_UNSCANNABLE: False,
                CONF_ALWAYS_EXCLUDE: [
                    "/hacsfiles/lovelace-mushroom/mushroom.js",
                    "/hacsfiles/lovelace-mushroom/cards.js?v=2",
                ],
            }
        )
        self.assertNotIn("/hacsfiles/lovelace-mushroom/cards.js", summary["included"])
        self.assertIn("mushroom-light-card", summary["unresolved_types"])
        self.assertIn("mushroom-lock-card", summary["unresolved_types"])

    async def test_always_include_ignores_the_version_query(self) -> None:
        """Always include matches the path, not the ?v= cache buster."""
        summary = await self._resolve(
            **{
                CONF_DASHBOARDS: ["panel"],
                CONF_ALWAYS_INCLUDE: [
                    "/hacsfiles/dreame-vacuum-card/dreame-vacuum-card.js?v=1"
                ],
            }
        )
        self.assertIn(
            "/hacsfiles/dreame-vacuum-card/dreame-vacuum-card.js",
            summary["included"],
        )

    async def test_default_dashboard_key_is_loaded(self) -> None:
        """Overview is stored under url_path None."""
        self.dashboards[None] = _Dashboard(
            {
                "views": [
                    {
                        "cards": [
                            {
                                "type": "custom:stack-in-card",
                                "cards": [
                                    {"type": "custom:mushroom-entity-card"}
                                ],
                            }
                        ]
                    }
                ]
            }
        )
        summary = await self._resolve(**{CONF_DASHBOARDS: [DEFAULT_DASHBOARD]})
        self.assertIn(
            "/hacsfiles/vertical-stack-in-card/vertical-stack-in-card.js",
            summary["included"],
        )
        self.assertIn("/hacsfiles/lovelace-mushroom/mushroom.js", summary["included"])
        self.assertNotIn("/hacsfiles/button-card/button-card.js?v=9", summary["included"])


if __name__ == "__main__":
    unittest.main()
