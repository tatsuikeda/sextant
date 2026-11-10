#!/usr/bin/env python3
"""sextant: export a maintainer's Firefox and Chrome setup as a reusable baseline,
and run a quarterly review of it.

  sextant.py export              snapshot both browsers into baseline/, ingest the uBlock
                            Origin and AdGuard backup files, regenerate BASELINE.md
  sextant.py check [--no-email] [--no-claude]
                            quarterly review: drift since the export, store health of
                            every extension, and a Claude web review of what to change;
                            writes reports/<date>.md, emails, posts a macOS notification

Disabled extensions are ignored everywhere. Nothing here installs or changes anything
in a browser: it reads profiles and proposes. Stdlib only.
"""
import argparse, configparser, datetime as dt, glob, html, json, os, re, shutil
import smtplib, subprocess, sys, urllib.error, urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "baseline"
PRIVATE = ROOT / "private"          # gitignored: everything personal lives here
RAW = PRIVATE / "raw"               # full browser snapshots and raw blocker backups
REPORTS = PRIVATE / "reports"
STATE = PRIVATE / "state.json"
TIERS = ROOT / "tiers.json"         # public: core and optional only
TIERS_PRIVATE = PRIVATE / "tiers-private.json"
HOME = Path.home()
FF_DIR = HOME / "Library/Application Support/Firefox"
CH_DIR = HOME / "Library/Application Support/Google/Chrome"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) sextant-check"
TODAY = dt.date.today()
STALE_DAYS = 365
CLIENT_TIERS = ("core", "optional")
ADGUARD_REGIONAL = {109}  # EasyList Italy; AdGuard's language autodetect adds regional lists per client anyway
# Prefs that describe the maintainer rather than the baseline: kept in private/raw, left out of baseline/.
PERSONAL_PREFS = re.compile(r"^browser\.translations\.|^signon\.firefoxRelay|^privacy\.(clearHistory|clearOnShutdown|cpd)\.|"
                            r"^privacy\.userContext\.|^network\.trr\.|^credentials_|^enable_do_not_track$")

# Prefs worth carrying between machines: privacy, security, passwords, DNS, telemetry.
FF_PREF_PREFIXES = ("privacy.", "browser.contentblocking.", "network.cookie.", "dom.security.https_only",
                    "signon.", "network.trr.", "browser.safebrowsing.", "datareporting.",
                    "toolkit.telemetry.enabled", "browser.translations.", "network.prefetch",
                    "network.dns.disablePrefetch", "network.http.speculative", "browser.urlbar.suggest.",
                    "extensions.formautofill.", "media.eme.enabled", "browser.discovery.enabled",
                    "app.shield.optoutstudies.enabled")
FF_PREF_EXCLUDE = ("services.sync.",)
# Bookkeeping Firefox writes for itself (timestamps, migration flags, cached IDs): not settings,
# and the IDs must never travel to a client machine.
FF_PREF_NOISE = re.compile(r"update ?time|milestone|cached|ProfileID|[Mm]igrat|last_purge|date_in_cookie|lastEpoch|"
                           r"CHIPS|restore|\.pending$|profileInfo|suggestImport|NotifiedTime|AcceptedVersion|"
                           r"\.sort$|mostRecent|panelShown|rustMirror|hasUserInteracted", re.I)
CH_PREF_KEYS = ("safebrowsing.enabled", "safebrowsing.enhanced", "profile.cookie_controls_mode",
                "profile.block_third_party_cookies", "enable_do_not_track", "dns_over_https.mode",
                "dns_over_https.templates", "credentials_enable_service", "credentials_enable_autosignin",
                "https_only_mode_enabled", "net.network_prediction_options", "search.suggest_enabled",
                "autofill.credit_card_enabled", "autofill.profile_enabled",
                "performance_tuning.high_efficiency_mode.state", "privacy_sandbox.m1.topics_enabled",
                "privacy_sandbox.m1.fledge_enabled", "privacy_sandbox.m1.ad_measurement_enabled",
                "translate.enabled", "alternate_error_pages.enabled", "url_keyed_anonymized_data_collection.enabled")

# First-run tier guesses by name; tiers.json is the source of truth once it exists.
TIER_GUESS = [
    ("core", r"^uBlock Origin$|AdGuard AdBlocker|Multi-Account Containers|Facebook Container"),
    ("retire", r"care about cookies|Canvas ?Blocker|Canvas Fingerprint|Don't track me Google|^Google Translate$|"
               r"Secure Password Generator|Adblock(er)? for You|ClearURLs|Skip Redirect"),
    ("optional", r"h264ify|OneTab|Sidebery|Vertical Tabs|SponsorBlock|Return YouTube Dislike|Enhancer for YouTube|"
                 r"Video Speed Controller|Unpaywall|Wayback Machine|Markdown Here|TWP|Docs Offline"),
]

def nodash(s):
    """No em or en dashes in anything this project writes: ranges become "to", the rest commas."""
    s = re.sub(r"(\d)\s*\u2013\s*(\d)", r"\1 to \2", s)
    return re.sub(r"\s*[\u2014\u2013]\s*", ", ", s)


def log(msg):
    print(f"[{dt.datetime.now():%F %T}] {msg}", flush=True)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def save_json(p, obj):
    Path(p).write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# ------------------------------------------------------------------ Firefox

def firefox_profile():
    # profiles.ini often lists stale profiles from old installs whose folders are gone, so take
    # the existing profile whose prefs.js was written most recently (Firefox rewrites it on use).
    ini = configparser.ConfigParser(strict=False)
    ini.read(FF_DIR / "profiles.ini")
    cands = {FF_DIR / ini.get(s, "Path") if ini.get(s, "IsRelative", fallback="1") == "1" else Path(ini.get(s, "Path"))
             for s in ini.sections() if ini.has_option(s, "Path")}
    cands |= set((FF_DIR / "Profiles").glob("*"))
    live = [p for p in cands if (p / "prefs.js").exists() and (p / "extensions.json").exists()]
    return max(live, key=lambda p: (p / "prefs.js").stat().st_mtime) if live else None


def parse_ff_prefs(prof):
    prefs = {}
    for fn in ("prefs.js", "user.js"):
        f = prof / fn
        if not f.exists():
            continue
        for m in re.finditer(r'user_pref\("([^"]+)",\s*(.+?)\);\s*$', f.read_text(errors="replace"), re.M):
            k, raw = m.group(1), m.group(2)
            if not k.startswith(FF_PREF_PREFIXES) or k.startswith(FF_PREF_EXCLUDE) or FF_PREF_NOISE.search(k):
                continue
            try:
                prefs[k] = json.loads(raw)
            except ValueError:
                prefs[k] = raw
    return prefs


def snapshot_firefox():
    prof = firefox_profile()
    if not prof or not (prof / "extensions.json").exists():
        return None
    data = load_json(prof / "extensions.json", {"addons": []})
    exts = {}
    for a in data.get("addons", []):
        gid = a.get("id", "")
        if (a.get("type") != "extension" or not a.get("active")
                or a.get("location") in ("app-builtin", "app-system-defaults", "app-system-addons")
                or gid.endswith(("@mozilla.org", "@mozilla.com"))):
            continue
        exts[gid] = {"name": (a.get("defaultLocale") or {}).get("name") or gid,
                     "version": a.get("version"),
                     "store": f"https://addons.mozilla.org/firefox/addon/{gid}/"}
    return {"profile": prof.name, "extensions": exts, "prefs": parse_ff_prefs(prof)}


# ------------------------------------------------------------------ Chrome

def _dig(d, dotted):
    for k in dotted.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _ext_name(manifest, mpath):
    name = manifest.get("name") or ""
    if name.startswith("__MSG_"):
        key = name[6:-2].lower()
        loc = manifest.get("default_locale", "en")
        msgs = load_json(Path(mpath).parent / "_locales" / loc / "messages.json", {})
        name = {k.lower(): v for k, v in msgs.items()}.get(key, {}).get("message", name)
    return name


def snapshot_chrome():
    ls = load_json(CH_DIR / "Local State", None)
    if not ls:
        return None
    out = {"profiles": {}}
    for prof, info in (ls.get("profile", {}).get("info_cache") or {}).items():
        pdir = CH_DIR / prof
        merged, prefs_doc = {}, load_json(pdir / "Preferences", {})
        for doc in (load_json(pdir / "Secure Preferences", {}), prefs_doc):
            for k, v in (_dig(doc, "extensions.settings") or {}).items():
                merged.setdefault(k, {}).update(v)
        exts = {}
        for eid, v in merged.items():
            if v.get("location") in (5, 10) or v.get("disable_reasons") or v.get("state") == 0:
                continue  # component extensions, or disabled
            mfs = sorted(glob.glob(str(pdir / "Extensions" / eid / "*" / "manifest.json")))
            if not mfs:
                continue
            m = load_json(mfs[-1], {})
            if "app" in m:
                continue  # legacy hosted apps (bookmark-like), not extensions
            exts[eid] = {"name": _ext_name(m, mfs[-1]), "version": m.get("version"),
                         "manifest_version": m.get("manifest_version"),
                         "store": f"https://chromewebstore.google.com/detail/{eid}"}
        out["profiles"][prof] = {"name": info.get("name"), "extensions": exts,
                                 "prefs": {k: _dig(prefs_doc, k) for k in CH_PREF_KEYS}}
    return out


def chrome_exts(snap):
    exts = {}
    for p in (snap or {}).get("profiles", {}).values():
        exts.update(p["extensions"])
    return exts


# ------------------------------------------------------------------ blocker backups

def newest(patterns):
    hits = []
    for d in (PRIVATE / "inbox", HOME / "Downloads", Path("/private/tmp")):
        for pat in patterns:
            hits += [Path(h) for h in glob.glob(str(d / pat))
                     if os.name == "nt" or Path(h).stat().st_uid == os.getuid()]  # /private/tmp is shared
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def ingest_backups():
    """Copy the newest raw blocker backups into private/raw (they hold personal allowlists)."""
    found = {}
    for key, pats, dest in (("ublock", ["my-ublock-backup*.txt", "*ublock*backup*.txt", "*ublock*backup*.json"],
                             "ublock-backup.json"),
                            ("adguard", ["adg*settings*.json", "*adguard*settings*.json", "*AdGuard*.json"],
                             "adguard-settings.json")):
        src = newest(pats)
        if src:
            shutil.copy2(src, RAW / dest)
            found[key] = {"source": src.name, "copied": str(TODAY),
                          "file_date": str(dt.date.fromtimestamp(src.stat().st_mtime))}
    return found


def sanitize_ublock(b):
    """Client-safe uBO backup: lists kept; My filters, personal trusted sites and imported-but-unused lists dropped."""
    b = json.loads(json.dumps(b))
    b["userFilters"] = []
    b["whitelist"] = [w for w in b.get("whitelist", []) if w.endswith("-scheme")]  # uBO's built-in defaults
    # Per-site rules name sites the maintainer visits: keep only global ("*") and behind-the-scene rules.
    keep = lambda line: line.split(" ", 1)[0] in ("*", "behind-the-scene")
    b["dynamicFilteringString"] = "\n".join(l for l in (b.get("dynamicFilteringString") or "").splitlines() if keep(l))
    b["hostnameSwitchesString"] = "\n".join(l for l in (b.get("hostnameSwitchesString") or "").splitlines()
                                            if len(l.split()) > 1 and l.split()[1] in ("*", "behind-the-scene"))
    b["urlFilteringString"] = ""
    b["hiddenSettings"] = {}
    sel = b.get("selectedFilterLists", [])
    us = b.get("userSettings") or {}
    ext = [u for u in (us.get("importedLists") or []) if u in sel]
    if us:
        us["importedLists"], us["externalLists"] = ext, "\n".join(ext)
    return b


def sanitize_adguard(b):
    """Client-safe AdGuard export: user rules and allowlist emptied, regional lists dropped (autodetect re-adds them)."""
    b = json.loads(json.dumps(b))
    f = b.setdefault("filters", {})
    f["enabled-filters"] = [i for i in f.get("enabled-filters", []) if i not in ADGUARD_REGIONAL]
    f.setdefault("user-filter", {})["rules"] = ""
    f["user-filter"]["disabled-rules"] = ""
    f.setdefault("allowlist", {})["domains"] = []
    f["allowlist"]["inverted-domains"] = []
    f["custom-filters"] = []
    return b


def ublock_summary(path=None):
    b = load_json(path or BASE / "ublock-backup.json", None)
    if not b:
        return None
    uf = b.get("userFilters") or []
    lines = uf.splitlines() if isinstance(uf, str) else [x for l in uf for x in str(l).splitlines()]  # str in old backups, list in v6
    return {"lists": sorted(b.get("selectedFilterLists", [])),
            "my_filters_lines": len([l for l in lines if l.strip()]),
            "trusted_sites": len((b.get("whitelist") or b.get("trustedSiteDirectives") or [])),
            "version": b.get("version")}


_ADG_NAMES = {}


def adguard_names():
    if not _ADG_NAMES:
        code, body, _ = fetch("https://filters.adtidy.org/extension/chromium-mv3/filters.json", timeout=20)
        if code == 200:
            _ADG_NAMES.update({f["filterId"]: f["name"] for f in json.loads(body).get("filters", [])})
    return _ADG_NAMES


def adguard_summary(path=None):
    b = load_json(path or BASE / "adguard-settings.json", None)
    if not b:
        return None
    filters = b.get("filters") or {}
    enabled = filters.get("enabled-filters") or filters.get("enabledFilters") or []
    names = adguard_names()
    stealth = b.get("stealth") or {}
    return {"enabled_filter_ids": enabled, "filters": [f"{names.get(i, 'filter')} ({i})" for i in enabled],
            "groups": filters.get("enabled-groups") or [],
            "stealth_mode_on": not stealth.get("stealth-disable-stealth-mode", False),
            "custom_filters": len(filters.get("custom-filters") or []),
            "user_rules": len([l for l in ((filters.get("user-filter") or {}).get("rules") or "").splitlines() if l.strip()]),
            "allowlisted": len((filters.get("allowlist") or {}).get("domains") or []),
            "protocol": b.get("protocol-version") or b.get("version")}


# ------------------------------------------------------------------ tiers, public baseline, BASELINE.md

def load_tiers():
    """tiers.json (public) holds core and optional; private/tiers-private.json holds the rest."""
    pub, priv = load_json(TIERS, {}), load_json(TIERS_PRIVATE, {})
    return {b: {**pub.get(b, {}), **priv.get(b, {})} for b in ("firefox", "chrome")}


def save_tiers(tiers):
    pub = {b: {k: v for k, v in t.items() if v["tier"] in CLIENT_TIERS} for b, t in tiers.items()}
    priv = {b: {k: v for k, v in t.items() if v["tier"] not in CLIENT_TIERS} for b, t in tiers.items()}
    save_json(TIERS, pub)
    save_json(TIERS_PRIVATE, priv)


def assign_tiers(ff, ch):
    tiers = load_tiers()
    for browser, exts in (("firefox", (ff or {}).get("extensions", {})), ("chrome", chrome_exts(ch))):
        for eid, e in exts.items():
            if eid in tiers[browser]:
                tiers[browser][eid]["name"] = e["name"]
                continue
            tier = next((t for t, rx in TIER_GUESS if re.search(rx, e["name"], re.I)), "unclassified")
            tiers[browser][eid] = {"name": e["name"], "tier": tier}
    save_tiers(tiers)
    return tiers


def tier_of(tiers, browser, eid):
    return (tiers.get(browser, {}).get(eid) or {}).get("tier", "unclassified")


def with_offstore(exts, tiers, browser):
    out = {k: dict(v) for k, v in exts.items() if tier_of(tiers, browser, k) in CLIENT_TIERS}
    for k, t in tiers.get(browser, {}).items():
        if t.get("off_store") and t["tier"] in CLIENT_TIERS:
            out.setdefault(k, {"name": t["name"], "version": "not installed here"})
            out[k]["store"] = t.get("homepage", "")
            out[k]["off_store"] = True
    return out


def public_firefox(ff, tiers):
    return {"extensions": with_offstore(ff["extensions"], tiers, "firefox"),
            "prefs": {k: v for k, v in ff["prefs"].items() if not PERSONAL_PREFS.search(k)}}


def public_chrome(ch, tiers):
    prefs = next(iter(ch["profiles"].values()), {}).get("prefs", {})  # first profile is the reference one
    return {"extensions": with_offstore(chrome_exts(ch), tiers, "chrome"),
            "prefs": {k: v for k, v in prefs.items() if not PERSONAL_PREFS.search(k)}}


def write_baseline_md(ff, ch, tiers, backups):
    L = ["# Sextant baseline", "", f"Exported {TODAY} by `sextant.py export`. Client-safe: only **core** (every client) and "
         "**optional** (on request) extensions, and settings with personal ones removed. Tiers live in `tiers.json`.", ""]
    for label, exts, browser in (("Firefox", (ff or {}).get("extensions", {}), "firefox"),
                                 ("Chrome", (ch or {}).get("extensions", {}), "chrome")):
        L += [f"## {label} extensions", "", "| tier | extension | version | store |", "|---|---|---|---|"]
        for eid, e in sorted(exts.items(), key=lambda kv: (tier_of(tiers, browser, kv[0]) != "core", kv[1]["name"].lower())):
            src = f"{e['store']} (outside the official store)" if e.get("off_store") else e["store"]
            L.append(f"| {tier_of(tiers, browser, eid)} | {e['name']} | {e['version']} | {src} |")
        L.append("")
    if ff:
        L += ["## Firefox settings (privacy and security prefs that differ from default)", "", "| pref | value |", "|---|---|"]
        L += [f"| `{k}` | `{json.dumps(v)}` |" for k, v in sorted(ff["prefs"].items())] + [""]
    if ch:
        L += ["## Chrome settings", "", "`null` means the Chrome default.", "", "| pref | value |", "|---|---|"]
        L += [f"| `{k}` | `{json.dumps(v)}` |" for k, v in ch["prefs"].items()] + [""]
    u, a = ublock_summary(), adguard_summary()
    L += ["## Blocker settings", ""]
    if u:
        L += [f"uBlock Origin (Firefox) `baseline/ublock-backup.json`, from {backups.get('ublock', {}).get('file_date', 'an earlier export')}: "
              f"{len(u['lists'])} filter lists. My filters and personal trusted sites removed.", "",
              "Lists: " + ", ".join(f"`{x}`" for x in u["lists"]), ""]
    else:
        L += ["uBlock Origin: no backup yet. In uBO open the Dashboard, Settings tab, **Back up to file**, then rerun `sextant.py export`.", ""]
    if a:
        L += [f"AdGuard (Chrome) `baseline/adguard-settings.json`, from {backups.get('adguard', {}).get('file_date', 'an earlier export')}: "
              f"{len(a['enabled_filter_ids'])} filters, Stealth Mode {'on' if a['stealth_mode_on'] else 'off'}. "
              "User rules, allowlist and regional lists removed.", "", "Filters: " + ", ".join(a["filters"]), ""]
    else:
        L += ["AdGuard: no export yet. In AdGuard open Settings, General, **Export settings**, then rerun `sextant.py export`.", ""]
    L += ["## Deploying", "", "`sextant.py policies` writes `baseline/policies/firefox/policies.json` and "
          "`baseline/policies/chrome/sextant-chrome.mobileconfig`. See README.md.", ""]
    (BASE / "BASELINE.md").write_text(nodash("\n".join(L)))


def cmd_export(_):
    for d in (BASE, RAW, REPORTS):
        d.mkdir(parents=True, exist_ok=True)
    ff, ch = snapshot_firefox(), snapshot_chrome()
    if ff: save_json(RAW / "firefox.json", ff)
    if ch: save_json(RAW / "chrome.json", ch)
    backups = ingest_backups()
    meta = load_json(PRIVATE / "meta.json", {})
    meta.update({"exported": str(TODAY)}); meta.setdefault("backups", {}).update(backups)
    save_json(PRIVATE / "meta.json", meta)
    tiers = assign_tiers(ff, ch)
    pff = public_firefox(ff, tiers) if ff else None
    pch = public_chrome(ch, tiers) if ch else None
    if pff: save_json(BASE / "firefox.json", pff)
    if pch: save_json(BASE / "chrome.json", pch)
    if (RAW / "ublock-backup.json").exists():
        save_json(BASE / "ublock-backup.json", sanitize_ublock(load_json(RAW / "ublock-backup.json", {})))
    if (RAW / "adguard-settings.json").exists():
        save_json(BASE / "adguard-settings.json", sanitize_adguard(load_json(RAW / "adguard-settings.json", {})))
    save_json(BASE / "meta.json", {"exported": str(TODAY),
                                   "blocker_backups": {k: v["file_date"] for k, v in meta["backups"].items()}})
    write_baseline_md(pff, pch, tiers, meta["backups"])
    log(f"firefox: {len((ff or {}).get('extensions', {}))} active extensions ({len((pff or {}).get('extensions', {}))} client-safe), "
        f"{len((pff or {}).get('prefs', {}))} prefs")
    log(f"chrome: {len(chrome_exts(ch))} active extensions ({len((pch or {}).get('extensions', {}))} client-safe)")
    log(f"blocker backups ingested: {', '.join(backups) or 'none found (see BASELINE.md)'}")
    unc = [v["name"] for b in tiers.values() for v in b.values() if v["tier"] == "unclassified"]
    if unc:
        log("unclassified, set a tier in private/tiers-private.json (or move to tiers.json as core/optional): " + "; ".join(unc))


# ------------------------------------------------------------------ check: drift

def diff_snap(old, new, label):
    out = []
    if not old or not new:
        return out
    oe, ne = old.get("extensions", {}), new.get("extensions", {})
    for k in sorted(ne.keys() - oe.keys()): out.append(f"{label}: added extension **{ne[k]['name']}**")
    for k in sorted(oe.keys() - ne.keys()): out.append(f"{label}: removed or disabled **{oe[k]['name']}**")
    op, np_ = old.get("prefs", {}), new.get("prefs", {})
    for k in sorted(op.keys() | np_.keys()):
        if op.get(k) != np_.get(k):
            out.append(f"{label}: `{k}` changed from `{json.dumps(op.get(k))}` to `{json.dumps(np_.get(k))}`")
    return out


def drift():
    out = diff_snap(load_json(RAW / "firefox.json", None), snapshot_firefox(), "Firefox")
    oc, nc = load_json(RAW / "chrome.json", None), snapshot_chrome()
    for prof in sorted(((oc or {}).get("profiles", {}).keys()) | ((nc or {}).get("profiles", {}).keys())):
        out += diff_snap((oc or {}).get("profiles", {}).get(prof), (nc or {}).get("profiles", {}).get(prof), f"Chrome {prof}")
    return out


# ------------------------------------------------------------------ check: store health

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, str(e), url


def amo_health(gid):
    code, body, _ = fetch(f"https://addons.mozilla.org/api/v5/addons/addon/{urllib.request.quote(gid, safe='@')}/")
    if code != 200:
        return {"ok": code != 0, "reachable": code != 0, "status": code}
    d = json.loads(body)
    return {"ok": True, "reachable": True, "status": 200, "url": d.get("url"),
            "version": (d.get("current_version") or {}).get("version"),
            "updated": (d.get("last_updated") or "")[:10],
            "recommended": any(p.get("category") == "recommended" for p in (d.get("promoted") or [])
                               if isinstance(p, dict)),
            "users": d.get("average_daily_users"),
            "authors": sorted(a.get("name", "") for a in d.get("authors") or []),
            "disabled": d.get("is_disabled")}


def cws_health(eid):
    code, body, url = fetch(f"https://chromewebstore.google.com/detail/{eid}")
    if code != 200:
        return {"ok": code != 0, "reachable": code != 0, "status": code}
    ver = re.search(r"Version</div><div[^>]*>([^<]+)", body)
    upd = re.search(r"Updated</div><div[^>]*>([^<]+)", body)
    updated = None
    if upd:
        try:
            updated = str(dt.datetime.strptime(upd.group(1).strip(), "%B %d, %Y").date())
        except ValueError:
            updated = upd.group(1).strip()
    # A listing that no longer exists redirects to the store front page rather than 404ing.
    gone = eid not in url
    return {"ok": True, "reachable": True, "status": 404 if gone else 200, "url": url,
            "version": ver.group(1).strip() if ver else None, "updated": updated}


def offstore_latest(entry, browser):
    """Latest version and download link from an off-store extension's own update manifest."""
    if browser == "firefox" and entry.get("update_manifest"):
        code, body, _ = fetch(entry["update_manifest"])
        if code == 200:
            ups = next(iter(json.loads(body).get("addons", {}).values()), {}).get("updates", [])
            if ups:
                return {"version": ups[-1].get("version"), "link": ups[-1].get("update_link"), "status": 200}
        return {"status": code}
    if browser == "chrome" and entry.get("update_url"):
        code, body, _ = fetch(entry["update_url"])
        m = re.search(r"codebase='([^']+)'\s+version='([^']+)'", body or "")
        return {"version": m.group(2), "link": m.group(1), "status": 200} if m else {"status": code}
    return {"status": 0}


def health(tiers, prev_state):
    findings, rows, state = [], [], {"firefox": {}, "chrome": {}}
    ff = load_json(RAW / "firefox.json", {}).get("extensions", {})
    ch = chrome_exts(load_json(RAW / "chrome.json", {}))
    for browser, exts, probe in (("firefox", ff, amo_health), ("chrome", ch, cws_health)):
        for eid, e in sorted(exts.items(), key=lambda kv: kv[1]["name"].lower()):
            tier = tier_of(tiers, browser, eid)
            entry = tiers.get(browser, {}).get(eid, {})
            if entry.get("off_store"):
                o = offstore_latest(entry, browser)
                h = {"ok": True, "reachable": o["status"] != 0, "status": o["status"], "version": o.get("version"),
                     "updated": None, "off_store": True}
            else:
                h = probe(eid)
            state[browser][eid] = h
            flags = []
            if not h.get("reachable"):
                flags.append("store check failed (network)")
            elif h.get("off_store") and h["status"] != 200:
                flags.append(f"own update server returned HTTP {h['status']}")
            elif h.get("off_store") and h.get("version") and h["version"] != e["version"]:
                flags.append(f"installed {e['version']}, update server offers {h['version']}")
            elif h["status"] in (401, 403, 404, 410):
                flags.append("no longer listed in the store (removed, or never public)")
            elif h["status"] != 200:
                flags.append(f"store returned HTTP {h['status']}")
            if h.get("updated") and re.match(r"\d{4}-\d\d-\d\d$", h["updated"]):
                age = (TODAY - dt.date.fromisoformat(h["updated"])).days
                if age > STALE_DAYS:
                    flags.append(f"not updated in {age // 30} months")
            if h.get("disabled"):
                flags.append("disabled by Mozilla")
            old = prev_state.get(browser, {}).get(eid, {})
            if old.get("authors") and h.get("authors") and old["authors"] != h["authors"]:
                flags.append(f"developer changed from {', '.join(old['authors'])} to {', '.join(h['authors'])}")
            if old.get("recommended") and h.get("recommended") is False:
                flags.append("lost Mozilla Recommended status")
            if browser == "chrome" and e.get("manifest_version") == 2:
                flags.append("Manifest V2: Chrome no longer runs it")
            rows.append({"browser": browser, "tier": tier, "name": e["name"], "version": e["version"],
                         "store_version": h.get("version"), "updated": h.get("updated"), "flags": flags})
            if flags:
                findings.append(f"{browser.title()} [{tier}] **{e['name']}**: " + "; ".join(flags))
    return findings, rows, state


# ------------------------------------------------------------------ check: Claude web review

def claude_review(tiers, last_check, health_findings):
    ff = load_json(BASE / "firefox.json", {})
    ch = load_json(BASE / "chrome.json", {})
    client_ext = lambda browser, exts: [f"- {e['name']} ({tier_of(tiers, browser, k)})" for k, e in exts.items()
                                        if tier_of(tiers, browser, k) in CLIENT_TIERS]
    u, a = ublock_summary(), adguard_summary()
    chrome_prefs = ch.get("prefs", {})
    prompt = f"""You are reviewing a privacy and security browser baseline that an IT consultant installs for small-office clients on macOS, Windows and Ubuntu.
Today is {TODAY}. The previous review was {last_check or 'never'}. Use web search to find what changed since then. Only cite things you found at a source; give the source URL for every recommendation.

Firefox baseline extensions:
{chr(10).join(client_ext('firefox', ff.get('extensions', {}))) or '- none'}
Firefox prefs: {json.dumps(ff.get('prefs', {}))}
uBlock Origin filter lists: {', '.join(u['lists']) if u else 'unknown'}

Chrome baseline extensions:
{chr(10).join(client_ext('chrome', ch.get('extensions', {}))) or '- none'}
Chrome prefs (null means Chrome default): {json.dumps(chrome_prefs)}
AdGuard enabled filters: {', '.join(a['filters']) if a else 'unknown'}; Stealth Mode {('on' if a['stealth_mode_on'] else 'off') if a else 'unknown'}

Automated store checks flagged: {'; '.join(health_findings) or 'nothing'}

Report, in Markdown, with exactly these sections:
## Recommended changes
Concrete changes to make to the baseline: settings to turn on or off, extensions to add, replace or remove, filter lists to add or drop. For each: what to do, why, and the source URL. Include security incidents, ownership sales, malware reports or removals affecting any listed extension, and new built-in browser features that make an extension unnecessary.
## Watch
Things that are announced but not yet actionable.
## Nothing to change
One line per area you checked and found fine.
Keep it under 600 words. Do not use em dashes or en dashes. Write for a technician, not a marketer."""
    claude = shutil.which("claude", path=os.pathsep.join([str(HOME / ".local/bin"), "/usr/local/bin", os.environ.get("PATH", "")]))
    if not claude:
        return "_Claude CLI not found; web review skipped._"
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # use the subscription login
    try:
        import tempfile
        # Web pages are untrusted input to this run: give it web tools only (no files, shell or MCP servers)
        # and an empty working directory, so injected instructions have nothing to read or send.
        with tempfile.TemporaryDirectory(prefix="sextant-review-") as scratch:
            r = subprocess.run([claude, "-p", "--output-format", "text", "--tools", "WebSearch,WebFetch",
                                "--allowedTools", "WebSearch", "WebFetch", "--strict-mcp-config",
                                "--setting-sources", "user"],
                               input=prompt, capture_output=True, text=True, timeout=1500, cwd=scratch, env=env)
        if r.returncode == 0 and r.stdout.strip():
            return nodash(r.stdout.strip())
        return f"_Claude review failed (exit {r.returncode}): {(r.stderr or r.stdout).strip()[:300]}_"
    except subprocess.TimeoutExpired:
        return "_Claude review timed out after 25 minutes._"


# ------------------------------------------------------------------ report, email, notification

def md_to_html(md):
    out, in_list, in_table = [], False, False
    def inline(s):
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"`([^`]+)`", r'<code style="background:#f1f3f6;padding:1px 4px;border-radius:3px">\1</code>', s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" style="color:#1d4ed8">\1</a>', s)
        s = re.sub(r'(?<![">])(https?://[^\s<)]+)', r'<a href="\1" style="color:#1d4ed8">\1</a>', s)
        return s
    for line in md.splitlines():
        t = line.strip()
        if in_list and not t.startswith(("- ", "* ")):
            out.append("</ul>"); in_list = False
        if in_table and not t.startswith("|"):
            out.append("</table>"); in_table = False
        if t.startswith("|"):
            cells = [c.strip() for c in t.strip("|").split("|")]
            if all(re.fullmatch(r":?-+:?", c) for c in cells):
                continue
            weight = "" if in_table else "font-weight:600;background:#f1f3f6;"
            if not in_table:
                out.append('<table style="border-collapse:collapse;font-size:13px;margin:8px 0">'); in_table = True
            out.append("<tr>" + "".join(f'<td style="{weight}border:1px solid #d8dde6;padding:4px 8px">{inline(c)}</td>' for c in cells) + "</tr>")
        elif m := re.match(r"(#{1,3})\s+(.*)", t):
            size = {1: 22, 2: 17, 3: 15}[len(m.group(1))]
            out.append(f'<h{len(m.group(1))} style="font-size:{size}px;color:#1c2440;margin:18px 0 6px">{inline(m.group(2))}</h{len(m.group(1))}>')
        elif t.startswith(("- ", "* ")):
            if not in_list:
                out.append('<ul style="margin:4px 0 8px 18px;padding:0">'); in_list = True
            out.append(f'<li style="margin:3px 0">{inline(t[2:])}</li>')
        elif t:
            out.append(f'<p style="margin:6px 0">{inline(t)}</p>')
    if in_list: out.append("</ul>")
    if in_table: out.append("</table>")
    return ('<div style="background:#ffffff;color:#1f2937;font-family:-apple-system,Helvetica,Arial,sans-serif;'
            'font-size:14px;line-height:1.5;max-width:720px;margin:0 auto;padding:16px">' + "\n".join(out) + "</div>")


def send_email(env, subject, md, to, bcc=()):
    addr, pw = env.get("GMAIL_ADDRESS"), env.get("GMAIL_APP_PASSWORD")
    if not (addr and pw and (to or bcc)):
        log("email skipped: GMAIL_ADDRESS, GMAIL_APP_PASSWORD or recipients missing in .env")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"] = subject, f"Sextant <{addr}>"
    msg["To"] = ", ".join(to) if to else addr  # clients-only mail is addressed to ourselves, clients in Bcc
    msg.attach(MIMEText(md, "plain", "utf-8"))
    msg.attach(MIMEText(md_to_html(md), "html", "utf-8"))
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as s:
        s.starttls(); s.login(addr, pw)
        s.sendmail(addr, list(to or [addr]) + list(bcc), msg.as_string())  # Bcc only in the envelope
    log(f"email sent: {subject} to {len(to)} owner, {len(bcc)} client (bcc)")
    return True


def notify(title, text):
    subprocess.run(["osascript", "-e", "on run argv", "-e",
                    "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run",
                    title, text], capture_output=True)


def read_clients():
    f = PRIVATE / "clients.txt"
    if not f.exists():
        return []
    return [l.split("#")[0].strip() for l in f.read_text().splitlines() if "@" in l.split("#")[0]]


def cmd_check(args):
    REPORTS.mkdir(parents=True, exist_ok=True)
    tiers = load_tiers()
    prev = load_json(STATE, {})
    last = prev.get("last_check")
    log("drift"); dr = drift()
    log("store health"); hf, rows, hstate = health(tiers, prev)
    review = "_Skipped (--no-claude)._" if args.no_claude else (log("claude web review") or claude_review(tiers, last, hf))

    client_hf = [f for f in hf if re.search(r"\[(core|optional)\]", f)]
    table = ["| browser | tier | extension | installed | store | store updated | flags |", "|---|---|---|---|---|---|---|"]
    table += [f"| {r['browser']} | {r['tier']} | {r['name']} | {r['version']} | {r['store_version'] or ''} | {r['updated'] or ''} | {'; '.join(r['flags'])} |"
              for r in rows]
    client_table = [table[0], table[1]] + [t for t, r in zip(table[2:], rows) if r["tier"] in CLIENT_TIERS]

    head = f"# Sextant review, {TODAY}"
    owner_md = "\n".join([head, "", f"Previous review: {last or 'none'}. Baseline exported {load_json(PRIVATE / 'meta.json', {}).get('exported', '?')}.", "",
                          "## Store flags", ""] + ([f"- {x}" for x in hf] or ["- none"]) +
                         ["", "## Drift on Tatsu's browsers since the export", ""] + ([f"- {x}" for x in dr] or ["- none"]) +
                         ["", "If the drift is intentional, run `sextant.py export` to make it the new baseline.", "",
                          review, "", "## All extensions", ""] + table)
    client_md = "\n".join([head, "", "Quarterly check of the recommended browser setup. Nothing has been changed on your computer; "
                           "Tatsu will contact you about anything that needs doing.", "", "## Store flags", ""] +
                          ([f"- {x}" for x in client_hf] or ["- none"]) + ["", review, "", "## Recommended extensions", ""] +
                          client_table)
    owner_md, client_md = nodash(owner_md), nodash(client_md)
    rpath = REPORTS / f"{TODAY}.md"
    rpath.write_text(owner_md)
    (REPORTS / f"{TODAY}-client.md").write_text(client_md)
    save_json(STATE, {"last_check": str(TODAY), **hstate})
    log(f"report: {rpath}")

    n = len(hf) + len(dr) + review.count("\n- ")
    if not args.no_email:
        env = load_env()
        owners = [e.strip() for e in env.get("OWNER_EMAILS", "").split(",") if e.strip()]
        try:
            send_email(env, f"Sextant review {TODAY}: {len(hf)} store flag(s), {len(dr)} drift", owner_md, owners)
            clients = read_clients()
            if clients:
                send_email(env, f"Quarterly browser security check, {TODAY:%B %Y}", client_md, [], clients)
        except (smtplib.SMTPException, OSError) as e:
            log(f"email failed: {e}")
    notify("Sextant review", f"{len(hf)} store flag(s), {len(dr)} drift. Report: reports/{rpath.name}")


# ------------------------------------------------------------------ policies: Firefox policies.json, Chrome .mobileconfig
# Built against Mozilla policy-templates docs/index.md and Chromium policy_definitions (checked 2026-11-10).

FF_PREF_POLICY_OK = ("accessibility.", "app.update.", "browser.", "datareporting.policy.", "dom.", "extensions.",
                     "geo.", "media.", "network.", "pdfjs.", "places.", "print.", "signon.", "privacy.fingerprintingProtection",
                     "privacy.baselineFingerprintingProtection", "privacy.globalprivacycontrol.enabled")
FF_PREF_VIA_POLICY = ("browser.contentblocking.category",)  # expressed through EnableTrackingProtection instead
CWS_UPDATE = "https://clients2.google.com/service/update2/crx"
AMO_LATEST = "https://addons.mozilla.org/firefox/downloads/latest/{}/latest.xpi"


def pick_optional(exts, tiers, browser, wanted):
    if not wanted:
        return set()
    if wanted.strip().lower() == "all":
        return {k for k in exts if tier_of(tiers, browser, k) == "optional"}
    terms = [w.strip().lower() for w in wanted.split(",") if w.strip()]
    return {k for k, e in exts.items() if tier_of(tiers, browser, k) == "optional"
            and any(t in e["name"].lower() for t in terms)}


def firefox_policies(ff, tiers, optional):
    exts = ff.get("extensions", {})
    chosen = {k for k in exts if tier_of(tiers, "firefox", k) == "core"} | pick_optional(exts, tiers, "firefox", optional)
    settings, notes = {}, []
    for k in sorted(chosen):
        url = AMO_LATEST.format(urllib.request.quote(k, safe="@"))
        if exts[k].get("off_store"):
            latest = offstore_latest(tiers["firefox"][k], "firefox")
            if not latest.get("link"):
                notes.append(f"{exts[k]['name']}: update server unreachable, left out"); continue
            url = latest["link"]  # pinned file; the extension then updates itself from its own update URL
            notes.append(f"{exts[k]['name']}: installs {latest['version']} from its own server, not addons.mozilla.org")
        settings[k] = {"installation_mode": "force_installed" if tier_of(tiers, "firefox", k) == "core" else "normal_installed",
                       "install_url": url}
    for n in notes:
        log("firefox: " + n)
    pol = {"ExtensionSettings": settings}
    prefs = ff.get("prefs", {})
    if prefs.get("browser.contentblocking.category") == "strict":
        # Individual protections rather than Category "strict": Category locks the setting, these leave it changeable.
        pol["EnableTrackingProtection"] = {"Value": True, "Locked": False, "Cryptomining": True, "Fingerprinting": True,
                                           "EmailTracking": True, "BaselineExceptions": True,
                                           "SuspectedFingerprinting": bool(prefs.get("privacy.fingerprintingProtection")),
                                           "ConvenienceExceptions": bool(prefs.get("privacy.trackingprotection.allow_list.convenience.enabled", True))}
    if prefs.get("datareporting.healthreport.uploadEnabled") is False:
        pol["DisableTelemetry"] = True
    if prefs.get("app.shield.optoutstudies.enabled") is False:
        pol["DisableFirefoxStudies"] = True
    pp = {}
    for k, v in sorted(prefs.items()):
        if k in FF_PREF_VIA_POLICY or not k.startswith(FF_PREF_POLICY_OK):
            continue
        t = "boolean" if isinstance(v, bool) else "number" if isinstance(v, int) else "string"
        pp[k] = {"Value": v, "Status": "default", "Type": t}  # "default": preset but the user can change it
    if pp:
        pol["Preferences"] = pp
    ubo = "uBlock0@raymondhill.net"
    u = load_json(BASE / "ublock-backup.json", None)
    if ubo in chosen and u:
        pol["3rdparty"] = {"Extensions": {ubo: {"toOverwrite": {"filterLists": sorted(u.get("selectedFilterLists", []))}}}}
    return {"policies": pol}, sorted(exts[k]["name"] for k in chosen)


def chrome_policies(ch, tiers, optional):
    """Chrome policy dict, identical on every OS; only the delivery format differs."""
    exts = ch.get("extensions", {})
    chosen = {k for k in exts if tier_of(tiers, "chrome", k) == "core"} | pick_optional(exts, tiers, "chrome", optional)
    pol = {"ExtensionSettings": {
        k: {"installation_mode": "force_installed" if tier_of(tiers, "chrome", k) == "core" else "normal_installed",
            "update_url": tiers["chrome"][k]["update_url"] if exts[k].get("off_store") else CWS_UPDATE} for k in sorted(chosen)}}
    prefs = ch.get("prefs", {})
    # Chrome policies delivered by profile, registry or managed JSON are mandatory (locked): only settings worth locking.
    if prefs.get("profile.cookie_controls_mode") == 1 or prefs.get("profile.block_third_party_cookies") is True:
        pol["BlockThirdPartyCookies"] = True
    if prefs.get("search.suggest_enabled") is False:
        pol["SearchSuggestEnabled"] = False
    if prefs.get("autofill.credit_card_enabled") is False:
        pol["AutofillCreditCardEnabled"] = False
    offstore = sorted(exts[k]["name"] for k in chosen if exts[k].get("off_store"))
    return pol, sorted(exts[k]["name"] for k in chosen), offstore


def chrome_mobileconfig(pol):
    import plistlib, uuid
    ns = uuid.UUID("6f1c2b1e-3d4a-4b8e-9a51-0c7d2e4f8a10")
    inner = {"PayloadType": "com.google.Chrome", "PayloadVersion": 1, "PayloadDisplayName": "Google Chrome policies",
             "PayloadIdentifier": "local.sextant.chrome.policies",
             "PayloadUUID": str(uuid.uuid5(ns, "chrome.policies")).upper(), **pol}
    outer = {"PayloadType": "Configuration", "PayloadVersion": 1, "PayloadScope": "System",
             "PayloadDisplayName": "Sextant: Google Chrome",
             "PayloadDescription": "Installs the recommended Chrome extensions and privacy settings. Remove this profile to undo.",
             "PayloadIdentifier": "local.sextant.chrome",
             "PayloadUUID": str(uuid.uuid5(ns, "chrome")).upper(),  # stable, so a newer profile replaces the old one
             "PayloadRemovalDisallowed": False, "PayloadContent": [inner]}
    return plistlib.dumps(outer, fmt=plistlib.FMT_XML, sort_keys=True)


def chrome_reg(pol, remove=False):
    """Windows .reg (UTF-16 LE, as regedit expects for version 5.00). Dict policies are JSON strings, booleans DWORDs."""
    key = r"HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Google\Chrome"
    lines = ["Windows Registry Editor Version 5.00", "", f"[{key}]"]
    for k, v in pol.items():
        if remove:
            lines.append(f'"{k}"=-')
        elif isinstance(v, bool):
            lines.append(f'"{k}"=dword:{int(v):08x}')
        elif isinstance(v, int):
            lines.append(f'"{k}"=dword:{v:08x}')
        else:
            s = v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))
            lines.append(f'"{k}"="' + s.replace("\\", "\\\\").replace('"', '\\"') + '"')
    return ("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-16-le")


def cmd_policies(args):
    out = BASE / "policies"
    for d in ("firefox", "chrome"):
        (out / d).mkdir(parents=True, exist_ok=True)
    tiers = load_tiers()
    ff, ch = load_json(BASE / "firefox.json", None), load_json(BASE / "chrome.json", None)
    if not (ff and ch):
        sys.exit("run `sextant.py export` first")
    fpol, fnames = firefox_policies(ff, tiers, args.optional)
    save_json(out / "firefox" / "policies.json", fpol)
    cpol, cnames, offstore = chrome_policies(ch, tiers, args.optional)
    (out / "chrome" / "sextant-chrome.mobileconfig").write_bytes(chrome_mobileconfig(cpol))
    (out / "chrome" / "sextant-chrome-windows.reg").write_bytes(chrome_reg(cpol))
    (out / "chrome" / "sextant-chrome-windows-remove.reg").write_bytes(chrome_reg(cpol, remove=True))
    save_json(out / "chrome" / "sextant-chrome-linux.json", cpol)
    log(f"firefox policies.json (all OSes): {', '.join(fnames)}; policies: {', '.join(k for k in fpol['policies'] if k != 'ExtensionSettings')}")
    log(f"chrome (.mobileconfig macOS, .reg Windows, .json Linux): {', '.join(cnames)}; policies: {', '.join(k for k in cpol if k != 'ExtensionSettings')}")
    for n in offstore:
        log(f"chrome: {n} is not in the Chrome Web Store. Chrome installs it by policy on Linux, but on macOS only when MDM "
            "managed or enrolled in Chrome Enterprise Core, and on Windows only when domain or Entra joined or enrolled in "
            "Chrome Enterprise Core. Otherwise install it by hand (Developer mode, Load unpacked).")
    log("AdGuard filter settings cannot be set by policy: import baseline/adguard-settings.json by hand (Settings, General, Import settings)")
    return fpol, cpol


# ------------------------------------------------------------------ detect and apply on a client machine

def detect():
    """OS, distro and installed browsers, with where each browser reads machine-wide policy."""
    import platform
    sysname = platform.system()
    info = {"os": {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(sysname, sysname.lower()),
            "release": platform.release(), "machine": platform.machine(), "browsers": {}}
    b = info["browsers"]
    if info["os"] == "macos":
        info["version"] = platform.mac_ver()[0]
        for app in ("/Applications/Firefox.app", str(HOME / "Applications/Firefox.app")):
            if Path(app).exists():
                b["firefox"] = {"install": app, "policy_target": f"{app}/Contents/Resources/distribution/policies.json"}
                break
        if Path("/Applications/Google Chrome.app").exists():
            b["chrome"] = {"install": "/Applications/Google Chrome.app", "policy_target": "configuration profile (.mobileconfig)"}
    elif info["os"] == "windows":
        info["version"] = platform.version()
        for root in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"))):
            fx = Path(root) / "Mozilla Firefox"
            if (fx / "firefox.exe").exists() and "firefox" not in b:
                b["firefox"] = {"install": str(fx), "policy_target": str(fx / "distribution" / "policies.json")}
            gc = Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if gc.exists() and "chrome" not in b:
                b["chrome"] = {"install": str(gc.parent), "policy_target": r"HKLM\SOFTWARE\Policies\Google\Chrome (.reg)"}
    elif info["os"] == "linux":
        osr = {}
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1); osr[k] = v.strip('"')
        except OSError:
            pass
        info["distro"], info["version"] = osr.get("ID", "unknown"), osr.get("VERSION_ID", "")
        snaps = ""
        if shutil.which("snap"):
            snaps = subprocess.run(["snap", "list"], capture_output=True, text=True).stdout
        if shutil.which("firefox") or re.search(r"^firefox\s", snaps, re.M):
            kind = "snap" if re.search(r"^firefox\s", snaps, re.M) else "package"
            # Mozilla documents /etc/firefox/policies for system-wide policy; Ubuntu uses the same path for the snap.
            b["firefox"] = {"install": kind, "policy_target": "/etc/firefox/policies/policies.json"}
        if Path("/opt/google/chrome/chrome").exists():
            b["chrome"] = {"install": "/opt/google/chrome", "policy_target": "/etc/opt/chrome/policies/managed/sextant.json"}
        if re.search(r"^chromium\s", snaps, re.M) or shutil.which("chromium-browser") or shutil.which("chromium"):
            # Community reports disagree on which path the Chromium snap reads, so both are written.
            b["chromium"] = {"install": "snap" if re.search(r"^chromium\s", snaps, re.M) else "package",
                             "policy_target": ["/etc/chromium-browser/policies/managed/sextant.json",
                                               "/etc/chromium/policies/managed/sextant.json",
                                               "/var/snap/chromium/current/policies/managed/sextant.json"]}
    return info


def cmd_detect(_):
    print(json.dumps(detect(), indent=2))


def _is_admin():
    if os.name == "nt":
        import ctypes
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def _write_root(path, data, run):
    """Write a file that needs admin rights: directly when root/admin, else through sudo on macOS and Linux."""
    path = Path(path)
    if _is_admin() or os.name == "nt":
        if run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return f"write {path}"
    if run:
        subprocess.run(["sudo", "mkdir", "-p", str(path.parent)], check=True)
        subprocess.run(["sudo", "tee", str(path)], input=data, stdout=subprocess.DEVNULL, check=True)
        subprocess.run(["sudo", "chmod", "644", str(path)], check=True)
    return f"sudo write {path}"


def cmd_apply(args):
    info = detect()
    fpol, cpol = cmd_policies(args)
    out, run, steps = BASE / "policies", args.yes, []
    if info["os"] == "windows" and run and not _is_admin():
        sys.exit("run this from an elevated (Run as administrator) terminal")
    fx = info["browsers"].get("firefox")
    if fx:
        steps.append(_write_root(fx["policy_target"], json.dumps(fpol, indent=2).encode(), run))
    if "chrome" in info["browsers"]:
        if info["os"] == "macos":
            mc = out / "chrome" / "sextant-chrome.mobileconfig"
            steps.append(f"open {mc}, then approve it in System Settings, General, Device Management")
            if run:
                subprocess.run(["open", str(mc)])
        elif info["os"] == "windows":
            reg = out / "chrome" / "sextant-chrome-windows.reg"
            steps.append(f"reg import {reg}")
            if run:
                subprocess.run(["reg", "import", str(reg)], check=True)
        else:
            steps.append(_write_root(info["browsers"]["chrome"]["policy_target"], json.dumps(cpol, indent=2).encode(), run))
    if "chromium" in info["browsers"]:
        for t in info["browsers"]["chromium"]["policy_target"]:
            steps.append(_write_root(t, json.dumps(cpol, indent=2).encode(), run))
    print(json.dumps({"detected": info, "steps": steps, "applied": run}, indent=2))
    if not run:
        log("dry run: nothing changed. Rerun with --yes to apply.")
    else:
        log("applied. Restart the browsers, then check about:policies (Firefox) and chrome://policy (Chrome). "
            "Import baseline/adguard-settings.json into AdGuard by hand.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export", help="maintainer: snapshot your own browsers into baseline/").set_defaults(fn=cmd_export)
    sub.add_parser("detect", help="print this machine's OS and installed browsers").set_defaults(fn=cmd_detect)
    for name, fn, hlp in (("policies", cmd_policies, "write policy files for every OS from the baseline"),
                          ("apply", cmd_apply, "detect the OS and install the policies on this machine (dry run unless --yes)")):
        pp = sub.add_parser(name, help=hlp)
        pp.add_argument("--optional", default="", help='optional extensions to include: "all", or comma separated name fragments')
        if name == "apply":
            pp.add_argument("--yes", action="store_true", help="actually write the policy files")
        pp.set_defaults(fn=fn)
    c = sub.add_parser("check", help="maintainer: quarterly review"); c.set_defaults(fn=cmd_check)
    c.add_argument("--no-email", action="store_true"); c.add_argument("--no-claude", action="store_true")
    args = ap.parse_args()
    args.fn(args)



if __name__ == "__main__":
    main()
