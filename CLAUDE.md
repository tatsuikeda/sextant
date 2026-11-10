# sextant: rules for Claude

## What this is

A baseline of Tatsu's browser setup, used as an IT service to set up client browsers. See `README.md` for the layout and commands.

## Applying the baseline to a client browser

1. Read `baseline/BASELINE.md`, `tiers.json` and the newest `private/reports/<date>.md` if present. If the newest report recommends a change that Tatsu has not yet folded into the baseline, ask before applying either version.
2. Install **core** extensions, plus any **optional** ones the client asked for. Nothing in `private/` ever goes to a client. Preferred route: `sextant.py policies` and the deploy steps in README.md.
3. Install from the official store links in `BASELINE.md` (addons.mozilla.org, chromewebstore.google.com). Never sideload.
4. Blocker settings: `baseline/` copies are already cleaned (no My filters, personal trusted sites, user rules, allowlist or regional lists). uBO gets its lists through `policies.json`; AdGuard is imported by hand. Never import anything from `private/raw/`.
5. One ad blocker per browser. Never install a second blocker or a canvas fingerprint add-on next to it (both broke sites in Tatsu's own setup in Nov 2026).
6. Settings go through the generated policies, never by editing `prefs.js` or Chrome's `Preferences`. Chrome profile policies are locked, so only add a Chrome setting to `chrome_profile()` if locking it is acceptable for every client.
7. Never copy anything else from Tatsu's profiles to a client: no passwords, cookies, history, sync settings or profile IDs.
8. Record what was installed per client in `private/clients/<client>.md`.

## Writing

No em dashes, en dashes or double hyphens in anything this project writes, including email text. `sextant.py` replaces them in Claude's review output; keep that in place.

## Keep private data private

`private/` and `.env` are gitignored. Before any commit, grep the staged files for personal sites, emails and extension names that belong in `private/tiers-private.json`.
