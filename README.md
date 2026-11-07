# Lite Resources

Make wall panels and other low-powered displays start faster by loading **only the custom cards their dashboards use**.

Home Assistant loads every dashboard resource (every custom card and mod you've installed) on every device, whether or not the dashboard on screen uses it. On a phone or desktop that's fine; on a wall tablet or NSPanel it can mean several megabytes of JavaScript to download and run before the first card appears.

Lite Resources lets you pick the users that wall panels log in as. Those users get a trimmed resource list: just what their dashboards need. Every other user, and every other device, is unaffected.

## How it works

- The frontend asks Home Assistant for the resource list once per page load (`lovelace/resources`). For the chosen users, this integration answers with a filtered list instead.
- It reads the chosen dashboards, collects every `custom:` type used (including cards inside pop-ups, stacks and features), and finds which resource files define them.
- Mods that don't add a card type are detected from dashboard keys: `card_mod` → card-mod, `kiosk_mode` → kiosk-mode. Anything else can be added under **Always include**.
- Resources served by integrations (e.g. `/browser_mod.js`, `/webrtc/...`) can't be read, so by default they're always included.
- Nothing is changed on disk: your resources stay as they are. Remove the integration and everything is back to normal.

## Install

### HACS
1. HACS → ⋮ → **Custom repositories** → add `https://github.com/evski/ha-lite-resources`, type **Integration**.
2. Install **Lite Resources** and restart Home Assistant.

### Manual
Copy `custom_components/lite_resources` into your `config/custom_components/` folder and restart.

## Set up
**Settings → Devices & services → Add integration → Lite Resources**

| Option | What to choose |
|---|---|
| Light users | The user(s) your panels log in as. Give each panel its own user if you don't already. |
| Their dashboards | Every dashboard those users open. |
| Always include | Resources to load regardless (e.g. a mod used by a theme). |
| Include resources that can't be checked | Leave on unless you know those resources aren't needed. |

Reload the panel after saving.

## Check what a panel gets
**Developer tools → Actions → `lite_resources.preview`** shows the included and skipped resources and any `custom:` types no local resource was found for.

## Notes
- Filtering is per **user**, not per device: if you log in as a light user on your phone, you get the light list there too.
- If a light user opens a dashboard that isn't in their list, cards from skipped resources won't load. Add the dashboard and reload.
- Admin pages that list resources show the filtered list to light users.

## License
MIT
