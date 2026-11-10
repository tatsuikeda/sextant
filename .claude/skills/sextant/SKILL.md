---
name: sextant
description: Set up a client's Firefox and Chrome (or Chromium) with the privacy and security baseline in this repo, on macOS, Windows or Ubuntu. Detects the OS and installed browsers, asks which optional extensions to include (including Bypass Paywalls Clean), installs the policies, and verifies them. Use when asked to set up, harden, configure or "do the browsers" on a client machine, or to produce the policy files for one.
---

# Sextant: set up a client machine

Read `CLAUDE.md` in this repo first; its rules win over anything here.

## 1. Detect

Run on the client machine (Python 3.9+ standard library only, no venv needed there):

```
python3 sextant.py detect          # Windows: py sextant.py detect
```

It prints the OS (`macos`, `windows`, `linux` plus distro), which of Firefox, Google Chrome and Chromium are installed, how (app, snap, package), and where each reads machine-wide policy. Show the person this summary.

If Python is not available on the client (common on Windows), run `sextant.py policies` on the maintainer's Mac instead, copy the files from `baseline/policies/`, and follow the manual steps for that OS in README.md.

## 2. Choose the extensions

- **core** extensions in `tiers.json` always go on (force installed, cannot be removed).
- **optional** ones only on request (normal installed, can be disabled). Ask the person which, by name. Pass them as `--optional "onetab,sponsorblock"` or `--optional all`.
- **Bypass Paywalls Clean** is optional and comes from the developer's own server (gitflic), not Mozilla's or Google's store. Mention that when offering it. Include it with `--optional bypass`. Firefox installs it by policy on every OS. Chrome installs it by policy only on Linux, or on a Mac or Windows PC that is MDM managed, domain or Entra joined, or enrolled in Chrome Enterprise Core; otherwise Chrome ignores the entry and it has to be installed by hand (Developer mode, Load unpacked).

## 3. Apply

Always dry run first and show the planned steps:

```
python3 sextant.py apply --optional "<choices>"
```

Then, after the person confirms:

```
python3 sextant.py apply --optional "<choices>" --yes
```

What it does per OS:

| OS | Firefox | Chrome | Chromium |
|---|---|---|---|
| macOS | `Firefox.app/Contents/Resources/distribution/policies.json` (sudo) | opens the `.mobileconfig`; the person approves it in System Settings, General, Device Management | n/a |
| Windows | `<Program Files>\Mozilla Firefox\distribution\policies.json` | `reg import` of the `.reg` into `HKLM\SOFTWARE\Policies\Google\Chrome` | n/a |
| Ubuntu / Linux | `/etc/firefox/policies/policies.json` (works for the snap and the deb) | `/etc/opt/chrome/policies/managed/sextant.json` | written to all three paths the snap has been reported to read |

Windows must be an elevated (Run as administrator) terminal. macOS and Linux prompt for sudo.

## 4. Finish by hand

- AdGuard (Chrome): Settings, General, **Import settings**, choose `baseline/adguard-settings.json`. Policy cannot set AdGuard's filters.
- Restart both browsers.

## 5. Verify

Do not report success until these are checked on the machine:

- Firefox: `about:policies` shows **Active** with the policies listed, and the core extensions appear in `about:addons`.
- Chrome or Chromium: `chrome://policy` lists `ExtensionSettings` and the other policies with status OK, and AdGuard appears in `chrome://extensions`.
- uBlock Origin's Dashboard, Filter lists tab, shows the baseline lists ticked.

If a policy shows an error, report the exact message.

## 6. Undo

- macOS: remove the profile in System Settings, Device Management; delete `policies.json` from `Firefox.app/Contents/Resources/distribution/`.
- Windows: `reg import baseline\policies\chrome\sextant-chrome-windows-remove.reg`; delete the Firefox `distribution\policies.json`.
- Linux: delete the files listed in step 3.

## 7. Record

Write what was installed (date, OS, browsers, optional extensions, anything that failed) to `private/clients/<client>.md`.
