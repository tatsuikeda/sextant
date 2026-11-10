# Sextant baseline

Exported 2026-11-10 by `sextant.py export`. Client-safe: only **core** (every client) and **optional** (on request) extensions, and settings with personal ones removed. Tiers live in `tiers.json`.

## Firefox extensions

| tier | extension | version | store |
|---|---|---|---|
| core | Facebook Container | 2.3.12 | https://addons.mozilla.org/firefox/addon/@contain-facebook/ |
| core | Firefox Multi-Account Containers | 8.4.0 | https://addons.mozilla.org/firefox/addon/@testpilot-containers/ |
| core | uBlock Origin | 1.76.0 | https://addons.mozilla.org/firefox/addon/uBlock0@raymondhill.net/ |
| optional | Bypass Paywalls Clean | 4.4.9.0 | https://gitflic.ru/project/magnolia1234/bypass-paywalls-chrome-clean (outside the official store) |
| optional | enhanced-h264ify | 2.2.1 | https://addons.mozilla.org/firefox/addon/{9a41dee2-b924-4161-a971-7fb35c053a4a}/ |
| optional | Enhancer for YouTube™ | 2.0.136 | https://addons.mozilla.org/firefox/addon/enhancerforyoutube@maximerf.addons.mozilla.org/ |
| optional | Markdown Here | 2.16.0 | https://addons.mozilla.org/firefox/addon/markdown-here-webext@adam.pritchard/ |
| optional | OneTab | 2.25 | https://addons.mozilla.org/firefox/addon/extension@one-tab.com/ |
| optional | Return YouTube Dislike | 4.1.7 | https://addons.mozilla.org/firefox/addon/{762f9885-5a13-4abd-9c77-433dcd38b8fd}/ |
| optional | Sidebery | 5.6.1 | https://addons.mozilla.org/firefox/addon/{3c078156-979c-498b-8990-85f7987dd929}/ |
| optional | SponsorBlock for YouTube - Skip Sponsorships | 6.1.7 | https://addons.mozilla.org/firefox/addon/sponsorBlocker@ajay.app/ |
| optional | TWP - Translate Web Pages | 10.2.1.0 | https://addons.mozilla.org/firefox/addon/{036a55b4-5e72-4d05-a06c-cba2dfcc134a}/ |
| optional | Unpaywall | 3.98 | https://addons.mozilla.org/firefox/addon/{f209234a-76f0-4735-9920-eb62507a54cd}/ |

## Chrome extensions

| tier | extension | version | store |
|---|---|---|---|
| core | AdGuard AdBlocker | 5.5.4.56 | https://chromewebstore.google.com/detail/bgnkhhnnamicmpeenaelnjfhikgbkllg |
| optional | Bypass Paywalls Clean | not installed here | https://gitflic.ru/project/magnolia1234/bypass-paywalls-chrome-clean (outside the official store) |
| optional | Enhancer for YouTube™ | 3.0.19 | https://chromewebstore.google.com/detail/ponfpcnoihfmfllpaingbgckeeldkhle |
| optional | Google Docs Offline | 1.111.1 | https://chromewebstore.google.com/detail/ghbmnnjooekpmoecnnnilnnbdlolhkhi |
| optional | h264ify | 2.0.1 | https://chromewebstore.google.com/detail/aleakchihdccplidncghkekgioiakgal |
| optional | Markdown Here | 2.16.0 | https://chromewebstore.google.com/detail/elifhakcjgalahccnjkneoccemfahfoa |
| optional | OneTab | 2.24 | https://chromewebstore.google.com/detail/chphlpgkkbolifaimnlloiipkdnihall |
| optional | Return YouTube Dislike | 4.1.7 | https://chromewebstore.google.com/detail/gebbhagfogifgggkldgodflihgfeippi |
| optional | SponsorBlock for YouTube - Skip Sponsorships | 6.1.6 | https://chromewebstore.google.com/detail/mnjggcdmjocbbbhaepdhchncahnbgone |
| optional | Unpaywall | 3.99 | https://chromewebstore.google.com/detail/iplffkdpngmdjhlpjmppncnlhomiipha |
| optional | Vertical Tabs in Side Panel | 1.0.8 | https://chromewebstore.google.com/detail/akahnknmcbmgodngfjcflnaljdbhnlfo |
| optional | Video Speed Controller | 0.11.1 | https://chromewebstore.google.com/detail/nffaoalbilbmmfgbnbgppjihopabppdk |
| optional | Wayback Machine | 3.4.8 | https://chromewebstore.google.com/detail/fpnmgdkabkmnadcjpehmlllkndpkmiak |

## Firefox settings (privacy and security prefs that differ from default)

| pref | value |
|---|---|
| `app.shield.optoutstudies.enabled` | `false` |
| `browser.contentblocking.category` | `"strict"` |
| `browser.discovery.enabled` | `false` |
| `datareporting.healthreport.uploadEnabled` | `false` |
| `network.dns.disablePrefetch` | `true` |
| `network.http.speculative-parallel-limit` | `0` |
| `network.prefetch-next` | `false` |
| `privacy.annotate_channels.strict_list.enabled` | `true` |
| `privacy.bounceTrackingProtection.mode` | `1` |
| `privacy.clearOnShutdown_v2.formdata` | `true` |
| `privacy.fingerprintingProtection` | `true` |
| `privacy.query_stripping.enabled` | `true` |
| `privacy.query_stripping.enabled.pbmode` | `true` |
| `privacy.trackingprotection.allow_list.convenience.enabled` | `false` |
| `privacy.trackingprotection.consentmanager.skip.pbmode.enabled` | `false` |
| `privacy.trackingprotection.emailtracking.enabled` | `true` |
| `privacy.trackingprotection.enabled` | `true` |
| `privacy.trackingprotection.socialtracking.enabled` | `true` |

## Chrome settings

`null` means the Chrome default.

| pref | value |
|---|---|
| `safebrowsing.enabled` | `null` |
| `safebrowsing.enhanced` | `null` |
| `profile.cookie_controls_mode` | `1` |
| `profile.block_third_party_cookies` | `null` |
| `dns_over_https.mode` | `null` |
| `dns_over_https.templates` | `null` |
| `https_only_mode_enabled` | `null` |
| `net.network_prediction_options` | `0` |
| `search.suggest_enabled` | `false` |
| `autofill.credit_card_enabled` | `false` |
| `autofill.profile_enabled` | `true` |
| `performance_tuning.high_efficiency_mode.state` | `null` |
| `privacy_sandbox.m1.topics_enabled` | `null` |
| `privacy_sandbox.m1.fledge_enabled` | `null` |
| `privacy_sandbox.m1.ad_measurement_enabled` | `null` |
| `translate.enabled` | `null` |
| `alternate_error_pages.enabled` | `true` |
| `url_keyed_anonymized_data_collection.enabled` | `true` |

## Blocker settings

uBlock Origin (Firefox) `baseline/ublock-backup.json`, from 2026-11-10: 30 filter lists. My filters and personal trusted sites removed.

Lists: `adguard-cookies`, `adguard-generic`, `adguard-mobile-app-banners`, `adguard-other-annoyances`, `adguard-popup-overlays`, `adguard-social`, `adguard-spyware-url`, `adguard-widgets`, `block-lan`, `curben-phishing`, `easylist`, `easylist-annoyances`, `easylist-chat`, `easylist-newsletters`, `easylist-notifications`, `easyprivacy`, `fanboy-cookiemonster`, `fanboy-social`, `fanboy-thirdparty_social`, `https://ublockorigin.github.io/uAssets/filters/resource-abuse.txt`, `plowe-0`, `ublock-annoyances`, `ublock-badware`, `ublock-cookies-adguard`, `ublock-cookies-easylist`, `ublock-filters`, `ublock-privacy`, `ublock-quick-fixes`, `ublock-unbreak`, `urlhaus-1`

AdGuard (Chrome) `baseline/adguard-settings.json`, from 2026-11-10: 6 filters, Stealth Mode off. User rules, allowlist and regional lists removed.

Filters: AdGuard Base filter (2), AdGuard Tracking Protection filter (3), AdGuard Social Media filter (4), AdGuard URL Tracking filter (17), AdGuard Cookie Notices filter (18), Online Malicious URL Blocklist (208)

## Deploying

`sextant.py policies` writes `baseline/policies/firefox/policies.json` and `baseline/policies/chrome/sextant-chrome.mobileconfig`. See README.md.
