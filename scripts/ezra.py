#!/usr/bin/env python3
"""
Ezra (עזרא): someone comments a word, and gets the link in a private message.
The ManyChat pattern, run by Claude through the Zernio API. Standard library only.

Everything personal lives in ~/Ezra (Windows: %USERPROFILE%\\Ezra):
  .env          ZERNIO_API_KEY=...  (never printed, never copied into config.json)
  config.json   your campaigns: the word, the message, the buttons
  panel.html    the dashboard, rebuilt by `panel`
  archive/      logs saved before a campaign is deleted or rebuilt
  emails.csv    emails people typed in a DM, exported by `emails`

Commands (all reads are safe; every write needs --yes and prints a preview without it):
  key                      create ~/Ezra/.env and open it, so the key never passes through the chat
  check                    is the key good, which Instagram account is connected; fills ids into config.json
  posts [--limit 12]       recent Instagram posts and their ids (marks the ones that already have a bot)
  list                     every live campaign and workflow, with numbers
  show NAME                what the commenter will see, step by step (nothing is sent)
  create NAME [--yes]      create the campaign on Zernio (comment or story reply -> DM)
  update NAME [--yes]      change a live campaign's text, words or buttons
  pause NAME / resume NAME stop or restart a live campaign
  delete NAME [--yes]      archive its logs, then delete it
  logs NAME [--limit 30]   who commented, what they wrote, did the DM go out
  remind NAME [--yes]      the "⏰ remind me later" button: confirm now, the link again in N hours
  email NAME [--yes]       the "📩 send it to my email too" button: collects the email inside the DM
  emails                   export the collected emails to ~/Ezra/emails.csv
  audit                    safety check of every live campaign; exit code 1 if something is dangerous
  panel [--open] [--mask]  build the dashboard (--mask hides names, for screen recordings)
  builder [--open]         open the reply builder page

Hebrew always goes out through urllib as UTF-8 JSON. Never through curl: the shell mangles it.
"""
import argparse, csv, html, json, os, re, shutil, subprocess, sys, time
import urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "1.0.0"
BASE = "https://zernio.com/api/v1"
SKILL = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("EZRA_HOME") or os.environ.get("DMBOT_HOME") or (Path.home() / "Ezra"))
ENV = HOME / ".env"
CONFIG = HOME / "config.json"
ARCHIVE = HOME / "archive"
TEMPLATES = SKILL / "templates"

# Where Zernio can answer a comment with a private message. Everywhere else
# (YouTube, TikTok, Threads, LinkedIn) the only answer is a public reply.
DM_PLATFORMS = ("instagram", "facebook")
PUBLIC_ONLY = ("youtube", "tiktok", "threads", "linkedin")

# Placeholders the example config ships with. Nothing goes live while one is left.
PLACEHOLDERS = ("PUT-", "FILL-IN", "YOUR-HANDLE", "https://example.com")

# Words people type in everyday comments. A campaign that fires on these sends a DM
# to people who never asked for one, and that is exactly what gets reported as spam.
COMMON_WORDS = {
    "לינק", "מדריך", "תודה", "וואו", "מהמם", "מושלם", "אמן", "כן", "לא", "אני", "רוצה",
    "מעולה", "יפה", "חזק", "אש", "פרטים", "מחיר", "link", "info", "yes", "wow", "love",
}


# ------------------------------------------------------------------ output

def say(msg=""):
    print(msg, flush=True)


def die(msg, code=1):
    print(f"✗ {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def utf16_len(s):
    """Meta counts button titles in UTF-16 units: an emoji costs 2."""
    return len((s or "").encode("utf-16-le")) // 2


# --------------------------------------------------------------------- key

def api_key():
    for name in ("ZERNIO_API_KEY", "LATE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name].strip()
    try:
        for line in ENV.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() in ("ZERNIO_API_KEY", "LATE_API_KEY") and v.strip():
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    die(f"No Zernio key yet. Run `key`, paste the key into {ENV} and save.")


def cmd_key(a):
    HOME.mkdir(parents=True, exist_ok=True)
    if not ENV.exists() or "ZERNIO_API_KEY=" not in ENV.read_text(encoding="utf-8"):
        ENV.write_text("# Paste your Zernio API key right after the = sign, save, close.\n"
                       "ZERNIO_API_KEY=\n", encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass
    filled = bool(re.search(r"^ZERNIO_API_KEY=\S+", ENV.read_text(encoding="utf-8"), re.M))
    say(f"key file: {ENV}  ({'has a key' if filled else 'empty, waiting for the key'})")
    if a.no_open:
        return
    if sys.platform == "darwin":
        subprocess.run(["open", "-e", str(ENV)])
    elif os.name == "nt":
        subprocess.Popen(["notepad.exe", str(ENV)])
    else:
        say("open it in any text editor")
    say("opened in a text editor. Paste the key after the = sign, save (Cmd+S / Ctrl+S), close.")
    say("then run: check")


# --------------------------------------------------------------------- api

def call(method, path, body=None, timeout=60):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Authorization": f"Bearer {api_key()}", "Accept": "application/json",
                 **({"Content-Type": "application/json; charset=utf-8"} if body is not None else {})},
        method=method,
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code == 429 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"error": raw.decode("utf-8", "replace")[:400]}
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 2:
                time.sleep(2)
                continue
            return 0, {"error": f"network: {e}"}
    return 0, {"error": "unreachable"}


def ok(res, what):
    status, data = res
    if status == 401:
        die(f"{what}: the key was refused (401). Run `key` and paste it again, whole.")
    if status == 403:
        die(f"{what}: Zernio says your plan does not include this (403): {short(data)}")
    if not 200 <= status < 300:
        die(f"{what} failed [{status}]: {short(data)}")
    return data


def short(data, n=400):
    return json.dumps(data, ensure_ascii=False)[:n]


def redact(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False).replace(api_key(), "<KEY>"))


def items(data, *keys):
    for k in keys:
        if isinstance(data, dict) and isinstance(data.get(k), list):
            return data[k]
    return data if isinstance(data, list) else []


def oid(x):
    return x.get("id") or x.get("_id") or ""


# ------------------------------------------------------------------ config

def load_config(required=True):
    if not CONFIG.exists():
        if required:
            die(f"No {CONFIG} yet. Run the installer, or `check` to create it.")
        return None
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"config.json is not valid JSON (line {e.lineno}): {e.msg}")


def save_config(cfg):
    HOME.mkdir(parents=True, exist_ok=True)
    if CONFIG.exists():
        bak = HOME / "backups"
        bak.mkdir(exist_ok=True)
        shutil.copy2(CONFIG, bak / f"config-{datetime.now():%Y%m%d-%H%M%S}.json")
        olds = sorted(bak.glob("config-*.json"))
        for old in olds[:-20]:
            old.unlink()
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, CONFIG)


def campaign(cfg, name):
    for c in cfg.get("campaigns", []):
        if c.get("name") == name:
            return c
    names = ", ".join(c.get("name", "?") for c in cfg.get("campaigns", [])) or "(none yet)"
    die(f"No campaign named {name!r} in config.json. Have: {names}")


def has_placeholder(obj):
    blob = json.dumps(obj, ensure_ascii=False)
    return next((p for p in PLACEHOLDERS if p in blob), None)


# ------------------------------------------------------------ live state

def live_automations(cfg=None):
    """Every comment automation on the account, across every profile we know of.
    An account reconnected into a second Zernio profile keeps its old rules there,
    and listing a single profile makes them look deleted."""
    seen, out = set(), []
    prof_ids = []
    if cfg:
        prof_ids = [cfg.get("profileId")] + [c.get("profileId") for c in cfg.get("campaigns", [])]
    for pid in [p for p in prof_ids if p] or [None]:
        q = f"?profileId={urllib.parse.quote(pid)}" if pid else ""
        for a in items(ok(call("GET", f"/comment-automations{q}"), "list automations"), "automations", "data"):
            if oid(a) not in seen:
                seen.add(oid(a))
                out.append(a)
    if cfg and cfg.get("profileId"):  # also catch rules in profiles the config does not know
        for a in items(ok(call("GET", "/comment-automations"), "list automations"), "automations", "data"):
            if oid(a) not in seen:
                seen.add(oid(a))
                out.append(a)
    return out


def live_by_name(cfg):
    return {a.get("name"): a for a in live_automations(cfg)}


def live_workflows():
    return items(ok(call("GET", "/workflows"), "list workflows"), "workflows", "data")


# --------------------------------------------------------- translation

def platform_of(c):
    return (c.get("platform") or "instagram").lower()


def account_of(cfg, c):
    plat = platform_of(c)
    if c.get("accountId"):
        return c["accountId"]
    if plat == "instagram" and cfg.get("instagram", {}).get("accountId"):
        return cfg["instagram"]["accountId"]
    return (cfg.get("accounts", {}).get(plat) or {}).get("accountId", "")


def to_zernio(cfg, c):
    """config.json campaign -> POST /comment-automations body."""
    plat = platform_of(c)
    body = {
        "profileId": c.get("profileId") or cfg.get("profileId"),
        "accountId": account_of(cfg, c),
        "name": c["name"],
        "trigger": c.get("trigger", "comment"),
        "keywords": c.get("keywords", []),
        "matchMode": c.get("match", "contains"),
    }
    if c.get("exclude_keywords"):
        body["excludeKeywords"] = c["exclude_keywords"]
    if c.get("typo_tolerance") and body["matchMode"] == "word":
        body["typoTolerance"] = True
    if c.get("post_id"):
        body["platformPostId"] = str(c["post_id"])
    if plat in PUBLIC_ONLY:
        # No DMs exist there: the public reply IS the delivery, link and all.
        body["commentReply"] = c.get("public_reply", "")
        if c.get("public_reply_variations"):
            body["commentReplyVariations"] = c["public_reply_variations"]
        if c.get("paused"):
            body["isActive"] = False
        return body
    body["dmMessage"] = c["dm"]
    # Off: a redirect wrapper around a link is a spam signal inside DMs.
    body["linkTracking"] = bool(c.get("link_tracking", False))
    if c.get("also_in_dms"):
        body["alsoMatchInDms"] = True  # someone who DMs the word gets the same answer
    if c.get("like_comment"):
        body["actions"] = {"likeComment": True}
    if c.get("dm_delay_seconds"):
        body["dmDelaySeconds"] = int(c["dm_delay_seconds"])
    if c.get("dm_variations"):
        body["dmMessageVariations"] = c["dm_variations"]
    buttons = [dict(b) for b in c.get("buttons", [])]
    for b in buttons:
        if b.get("type") == "url" and c.get("utm"):
            b["url"] = add_utm(b["url"], c["utm"])
    for extra in ("remind", "email_capture"):
        e = c.get(extra)
        if e and e.get("button"):
            buttons.append({"type": "postback", "title": e["button"],
                            "payload": re.sub(r"\W+", "_", f"{c['name']}_{extra}").strip("_")})
    if buttons:
        body["buttons"] = buttons[:3]
    if c.get("trigger", "comment") == "comment":
        if c.get("public_reply"):
            body["commentReply"] = c["public_reply"]
        if c.get("public_reply_variations"):
            body["commentReplyVariations"] = c["public_reply_variations"]
        body["publicReplyPolicy"] = c.get("public_reply_policy", "after_dm")
    gate = c.get("follow_gate")
    if gate:
        body["audience"] = {"followerStatus": "follower", "whenUnknown": "verify"}
        body["followGate"] = {"message": gate["message"], "buttonLabel": gate["button"],
                              "notFollowingMessage": gate["not_following"]}
    if c.get("paused"):
        body["isActive"] = False
    return body


def add_utm(url, utm):
    """utm = "source/medium/campaign", e.g. "ig/dm/bot". Existing utm_* params win."""
    if not url or not utm or "utm_source=" in url:
        return url
    parts = (utm.split("/") + ["", "", ""])[:3]
    q = {k: v for k, v in zip(("utm_source", "utm_medium", "utm_campaign"), parts) if v}
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(q)


# --------------------------------------------------------------- safety

def check_campaign(cfg, c, live=None, net=True):
    """Returns (fails, warns). A fail blocks create/update. Live = name -> automation."""
    fails, warns = [], []
    name = c.get("name", "?")
    trig = c.get("trigger", "comment")
    match = c.get("match", "contains")
    kws = [k.strip() for k in c.get("keywords", []) if k.strip()]

    if trig not in ("comment", "story_reply"):
        fails.append(f"trigger must be comment or story_reply, not {trig!r}")
    if match not in ("contains", "word", "exact"):
        fails.append(f"match must be contains, word or exact, not {match!r}")
    if not kws and not (trig == "story_reply" and c.get("post_id")):
        fails.append("no keywords. Only a story_reply rule scoped to one story may answer every reply")
    scoped_post = trig == "comment" and bool(c.get("post_id"))
    hebrew = any(re.search(r"[\u0590-\u05FF]", k) for k in kws)
    for k in kws:
        if match == "contains" and len(k) <= 2:
            fails.append(f"'{k}' is {len(k)} letters with match=contains: it hides inside too many words")
        elif match == "contains" and len(k) <= 4:
            if scoped_post:
                warns.append(f"'{k}' is short and matched inside the comment, also inside longer words. "
                             f"On one post that is fine (it also catches 'אשמח ל{k}' and '{k} 🙏')")
            else:
                fails.append(f"'{k}' is {len(k)} letters with match=contains on {'stories' if trig == 'story_reply' else 'every post'}: "
                             f"it fires inside other words. Use match=exact and list the forms (ה{k}, ל{k})")
    if match == "word" and hebrew:
        warns.append("Zernio does not document whole-word matching for Hebrew. Test it once from a second account "
                     "with 'אשמח ל<word>', or use contains on a single post")
        if k.lower() in COMMON_WORDS:
            msg = f"'{k}' is an everyday word: people who asked for nothing will get a DM"
            (fails if trig == "story_reply" and not c.get("post_id") else warns).append(msg)
    if trig == "comment" and not c.get("post_id"):
        if c.get("account_wide"):
            warns.append("account-wide: answers this word on EVERY post you ever published")
        else:
            fails.append("no post_id. A comment rule must belong to one post (`posts` lists them). "
                         "Account-wide only with \"account_wide\": true, on purpose")

    plat = platform_of(c)
    if plat in PUBLIC_ONLY:
        if not c.get("public_reply"):
            fails.append(f"{plat} has no private messages: the public reply is the delivery, and it is empty")
        if trig != "comment":
            fails.append(f"{plat}: only comment triggers exist there")
        if not account_of(cfg, c):
            fails.append(f"no {plat} account in config.json. Connect it in Zernio and run `check`")
        if c.get("dm") or c.get("buttons"):
            warns.append(f"{plat} cannot send a DM: dm and buttons are ignored, only public_reply goes out")
        return fails, warns
    if plat not in DM_PLATFORMS:
        fails.append(f"unknown platform {plat!r}")
    has_buttons = bool(c.get("buttons")) or any((c.get(e) or {}).get("button") for e in ("remind", "email_capture"))
    limit = 640 if has_buttons else 1000
    if not (c.get("dm") or "").strip():
        fails.append("no DM text")
    elif len(c["dm"]) > limit:
        fails.append(f"DM is {len(c['dm'])} characters; with buttons Instagram allows {limit}")

    titles, urls = [], []
    total = len(c.get("buttons", [])) + sum(1 for e in ("remind", "email_capture") if (c.get(e) or {}).get("button"))
    if total > 3:
        fails.append(f"{total} buttons; Instagram shows at most 3 under a message")
    for b in c.get("buttons", []) + [{"type": "postback", "title": (c.get(e) or {}).get("button")}
                                     for e in ("remind", "email_capture") if (c.get(e) or {}).get("button")]:
        t = b.get("title") or ""
        if not t:
            fails.append("a button with no title")
        elif utf16_len(t) > 20:
            fails.append(f"button '{t}' is {utf16_len(t)}/20 (an emoji counts 2). Shorten it")
        titles.append((b.get("type"), t))
        if b.get("type") == "url":
            u = b.get("url", "")
            if not u.startswith("https://"):
                fails.append(f"button '{t}': link must start with https:// ({u or 'empty'})")
            else:
                urls.append(u)
    for u in re.findall(r"https?://\S+", c.get("dm", "")):
        urls.append(u.rstrip(").,"))

    gate = c.get("follow_gate")
    if gate:
        for k in ("message", "button", "not_following"):
            if not gate.get(k):
                fails.append(f"follow_gate.{k} is empty")
        if gate.get("button") and utf16_len(gate["button"]) > 20:
            fails.append(f"follow_gate.button is {utf16_len(gate['button'])}/20")

    if trig == "comment" and not c.get("public_reply"):
        warns.append("no public_reply. A visible 'sent you a DM' under the comment tells people to check "
                     "their requests, and every reply is one more comment on the post")
    if c.get("link_tracking"):
        warns.append("link_tracking is on: Zernio wraps the link in a redirect, a spam signal in DMs")

    ph = has_placeholder(c)
    if ph:
        fails.append(f"still has a placeholder ({ph}...). Fill it in first")

    # Postback titles reach Zernio as ordinary inbound text, and a workflow trigger
    # tests "contains". If one title sits inside another, one tap starts two flows.
    live = live or {}
    mine = {t for ty, t in titles if ty == "postback"}
    for other in live.values():
        if other.get("name") == name:
            continue
        for b in other.get("buttons") or []:
            ot = b.get("title") or ""
            if b.get("type") == "postback":
                ours = {x.get("name") for x in cfg.get("campaigns", [])}
                for t in mine:
                    if t and t == ot and other.get("name") in ours:
                        warns.append(f"button '{t}' is also on {other.get('name')}: one flow answers both. "
                                     f"Create that flow only once")
                    elif t and t == ot:
                        fails.append(f"button '{t}' already belongs to live campaign {other.get('name')}, "
                                     f"whose flow sends its own link. Pick another title, e.g. '⏰ תזכירו לי על {kws[0] if kws else '...'}'")
                    elif t and ot and (t in ot or ot in t):
                        fails.append(f"button '{t}' overlaps button '{ot}' of campaign {other.get('name')}: "
                                     f"one tap would start both flows. Pick a distinct title")
        # Two story rules that both catch the same word: the reply gets the wrong DM.
        if trig == "story_reply" and other.get("trigger") == "story_reply" and other.get("isActive", True):
            if other.get("platformPostId") and c.get("post_id") and str(other.get("platformPostId")) != str(c.get("post_id")):
                continue
            for k in kws:
                for ok_ in other.get("keywords") or []:
                    if k and ok_ and (k in ok_ or ok_ in k):
                        fails.append(f"story word '{k}' collides with '{ok_}' of live story rule "
                                     f"{other.get('name')}. Pause that one or choose another word")
            if not other.get("keywords") and not other.get("platformPostId"):
                fails.append(f"live story rule {other.get('name')} answers EVERY story reply")

    if net:
        for u in dict.fromkeys(urls):
            st = probe(u)
            if st is None:
                warns.append(f"could not reach {u} from here (offline?). Open it yourself before going live")
            elif st in (401, 403, 429):
                warns.append(f"{u} blocks automated checks ({st}). Open it on your phone before going live")
            elif st >= 400:
                fails.append(f"{u} answers {st}. A DM with a dead link cannot be re-sent")
    return fails, warns


def probe(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) ezra/" + VERSION})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def print_checks(fails, warns):
    for f in fails:
        say(f"  ✗ {f}")
    for w in warns:
        say(f"  ! {w}")
    if not fails and not warns:
        say("  ✓ all safety checks pass")
    elif not fails:
        say("  ✓ no blockers")


# ------------------------------------------------------------- commands

def cmd_check(a):
    HOME.mkdir(parents=True, exist_ok=True)
    say(f"ezra {VERSION} · folder {HOME}")
    accounts = items(ok(call("GET", "/accounts"), "read accounts"), "accounts", "data")
    profiles = items(ok(call("GET", "/profiles"), "read profiles"), "profiles", "data")
    say(f"✓ the key works · {len(profiles)} profile(s), {len(accounts)} connected account(s)")
    for acc in accounts:
        say(f"  {acc.get('platform', '?'):<10} @{acc.get('username') or acc.get('name') or '?':<22} {oid(acc)}")
    igs = [x for x in accounts if (x.get("platform") or "").lower() == "instagram"]
    if not igs:
        say("✗ no Instagram account is connected to Zernio. Connect it there (it must be a Business or "
            "Creator account), then run check again.")
        sys.exit(2)
    cfg = load_config(required=False)
    if cfg is None:
        example = TEMPLATES / "config.example.json"
        cfg = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {"campaigns": []}
    cfg["accounts"] = {(x.get("platform") or "?").lower(): {"accountId": oid(x), "username": x.get("username") or x.get("name") or ""}
                       for x in accounts}
    ig = cfg.setdefault("instagram", {})
    pick = next((x for x in igs if oid(x) == ig.get("accountId")), None)
    if not pick:
        if len(igs) > 1 and not a.account:
            say("more than one Instagram account. Run again with --account USERNAME")
            sys.exit(2)
        pick = next((x for x in igs if a.account and (x.get("username") or "").lower() == a.account.lower().lstrip("@")), igs[0])
    user = pick.get("username") or ""
    ig.update({"accountId": oid(pick), "username": user,
               "profile_url": f"https://www.instagram.com/{user}/" if user else ig.get("profile_url", "")})
    pid = pick.get("profileId")
    if isinstance(pid, dict):
        pid = oid(pid)
    if not pid and isinstance(pick.get("profile"), dict):
        pid = oid(pick["profile"])
    cfg["profileId"] = pid or cfg.get("profileId") or (oid(profiles[0]) if profiles else "")
    save_config(cfg)
    say(f"✓ Instagram @{user} · ids saved to config.json (never type an id by hand)")
    live = live_automations(cfg)
    say(f"✓ {len(live)} campaign(s) already live on this account")


def cmd_posts(a):
    cfg = load_config(required=False) or {}
    q = urllib.parse.urlencode({"platform": a.platform, "limit": str(a.limit)})
    posts = items(ok(call("GET", f"/inbox/comments?{q}"), "read posts"), "data", "posts")
    bound = {str(x.get("platformPostId")): x.get("name") for x in (live_automations(cfg) if cfg else [])}
    if not posts:
        say("(no posts returned. Is the Instagram account connected in Zernio?)")
    for p in posts:
        pid = str(p.get("platformPostId") or p.get("id"))
        head = re.sub(r"\s+", " ", p.get("content") or p.get("caption") or "")[:60]
        when = (p.get("createdTime") or p.get("createdAt") or "")[:10]
        tag = f"  ← bot: {bound[pid]}" if pid in bound else ""
        say(f"{pid:<22} {when}  {p.get('commentCount', 0):>4} comments  {head}{tag}")


def fmt_stats(a):
    s = a.get("stats") or {}
    return (f"triggered={s.get('triggered', 0)} sent={s.get('dmsSent', 0)} "
            f"failed={s.get('dmsFailed', 0)}")


def cmd_list(a):
    cfg = load_config(required=False) or {}
    live = live_automations(cfg)
    local = {c["name"] for c in cfg.get("campaigns", [])}
    if not live:
        say("(no live campaigns)")
    for x in sorted(live, key=lambda x: x.get("createdAt", ""), reverse=True):
        scope = x.get("platformPostId") or "ALL POSTS"
        state = "on " if x.get("isActive", True) else "off"
        mark = "" if x.get("name") in local else "  (not in config.json)"
        say(f"{state} {x.get('name', '?'):<24} {x.get('trigger', 'comment'):<11} words={x.get('keywords')} "
            f"match={x.get('matchMode')} scope={scope}  {fmt_stats(x)}{mark}")
    for c in cfg.get("campaigns", []):
        if c["name"] not in {x.get("name") for x in live}:
            say(f"--  {c['name']:<24} in config.json only (not created yet)")
    wfs = live_workflows()
    if wfs:
        say("workflows:")
    for w in wfs:
        say(f"  {w.get('status', '?'):<7} {w.get('name', '?'):<34} started={w.get('totalStarted', 0)} "
            f"completed={w.get('totalCompleted', 0)}  {oid(w)}")


def cmd_show(a):
    cfg = load_config()
    c = campaign(cfg, a.name)
    body = to_zernio(cfg, c)
    trig = c.get("trigger", "comment")
    counter = iter(range(1, 20))
    step = lambda: next(counter)
    say(f"━━ {c['name']} · {platform_of(c)} · what the other side sees ━━")
    if platform_of(c) in PUBLIC_ONLY:
        say(f"{step()}. they comment: {' / '.join(c.get('keywords', []))}   [{c.get('match', 'word')}]")
        say(f"{step()}. public reply (rotates): {' | '.join([c.get('public_reply', '')] + c.get('public_reply_variations', []))}")
        print_checks(*check_campaign(cfg, c, live_by_name(cfg), net=not a.offline))
        return
    where = f"post {c['post_id']}" if c.get("post_id") else ("ALL POSTS" if trig == "comment" else "any story")
    say(f"{step()}. they {'comment' if trig == 'comment' else 'reply to the story'} with: "
        f"{' / '.join(c.get('keywords', [])) or '(anything)'}   [{c.get('match', 'word')}, {where}]")
    if trig == "comment" and c.get("public_reply"):
        reps = [c["public_reply"]] + c.get("public_reply_variations", [])
        say(f"{step()}. public reply under their comment (rotates): {' | '.join(reps)}")
    if c.get("follow_gate"):
        g = c["follow_gate"]
        say(f"{step()}. not a follower yet? they first get: «{g['message']}» [button: {g['button']}]")
        say(f"   tapped without following: «{g['not_following']}»")
    say(f"{step()}. the DM:")
    for line in c["dm"].splitlines():
        say(f"   │ {line}")
    for b in body.get("buttons", []):
        kind = "→ " + b.get("url", "") if b["type"] == "url" else "(starts a flow)"
        say(f"   [ {b['title']} ]  {kind}")
    if c.get("remind"):
        r = c["remind"]
        say(f"{step()}. tap «{r['button']}»: «{r.get('confirm', '')}», then after {r.get('hours', 4)}h: «{r.get('message', '')}»")
    if c.get("email_capture"):
        e = c["email_capture"]
        say(f"{step()}. tap «{e['button']}»: «{e.get('ask', '')}» → they type an email → «{e.get('thanks', '')}»"
            + (" → newsletter" if (cfg.get("newsletter") or {}).get("webhook_url") else " → saved for `emails`"))
    say("")
    live = live_by_name(cfg)
    fails, warns = check_campaign(cfg, c, live, net=not a.offline)
    print_checks(fails, warns)
    if a.json:
        say(json.dumps(redact(body), ensure_ascii=False, indent=2))


def preview_or_go(a, what):
    if not a.yes:
        say(f"\nPREVIEW ONLY. Nothing was created. To {what}, run the same command with --yes")
        return False
    return True


def cmd_create(a):
    cfg = load_config()
    c = campaign(cfg, a.name)
    live = live_by_name(cfg)
    if c["name"] in live:
        die(f"{c['name']} is already live. Use `update {c['name']}` to change it.")
    a.offline, a.json = False, False
    cmd_show(a)
    fails, _ = check_campaign(cfg, c, live, net=False)
    if fails:
        die("fix the ✗ lines in config.json first. Nothing was created.")
    if not preview_or_go(a, "create it"):
        return
    body = to_zernio(cfg, c)
    if a.paused:
        body["isActive"] = False
    data = ok(call("POST", "/comment-automations", body), "create campaign")
    auto = data.get("automation", data)
    c["_id"] = oid(auto)
    save_config(cfg)
    say(f"✓ live: {c['name']} ({c['_id']})"
        + (" · PAUSED" if body.get("isActive") is False else ""))
    nxt = [f"remind {c['name']}" for _ in [1] if c.get("remind")] + [f"email {c['name']}" for _ in [1] if c.get("email_capture")]
    if nxt:
        say("its buttons need their flows too: " + " · ".join(nxt))
    say("now test it from a DIFFERENT Instagram account (see SKILL.md, Testing)")


def archive_logs(auto, why):
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    st, data = call("GET", f"/comment-automations/{oid(auto)}/logs?limit=100")
    logs = items(data, "logs", "data") if 200 <= st < 300 else []
    out = ARCHIVE / f"{auto.get('name', 'campaign')}-{why}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"automation": redact(auto), "logs": logs}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out, len(logs)


def cmd_update(a):
    cfg = load_config()
    c = campaign(cfg, a.name)
    live = live_by_name(cfg)
    cur = live.get(c["name"])
    if not cur:
        die(f"{c['name']} is not live. Use `create {c['name']}`.")
    a.offline, a.json = False, False
    cmd_show(a)
    fails, _ = check_campaign(cfg, c, live, net=False)
    if fails:
        die("fix the ✗ lines first. Nothing was changed.")
    body = to_zernio(cfg, c)
    immutable = str(cur.get("accountId") or "") != str(body["accountId"] or "")
    if not preview_or_go(a, "apply it"):
        return
    if not immutable:
        patch = {k: v for k, v in body.items() if k not in ("profileId", "accountId")}
        st, data = call("PATCH", f"/comment-automations/{oid(cur)}", patch)
        if 200 <= st < 300:
            say(f"✓ updated in place. Numbers and logs kept.")
            return
        if st not in (404, 405):
            die(f"update failed [{st}]: {short(data)}")
        say("this Zernio version cannot edit in place; rebuilding (logs are archived first)")
    path, n = archive_logs(cur, "before-rebuild")
    say(f"  archived {n} log lines → {path}")
    ok(call("DELETE", f"/comment-automations/{oid(cur)}"), "delete old version")
    data = ok(call("POST", "/comment-automations", body), "create new version")
    c["_id"] = oid(data.get("automation", data))
    save_config(cfg)
    say(f"✓ rebuilt: {c['name']} ({c['_id']}). Its counters start from zero.")


def set_active(a, on):
    cfg = load_config()
    c = campaign(cfg, a.name)
    cur = live_by_name(cfg).get(c["name"])
    if not cur:
        die(f"{c['name']} is not live.")
    st, data = call("PATCH", f"/comment-automations/{oid(cur)}", {"isActive": on})
    if not 200 <= st < 300:
        die(f"could not {'resume' if on else 'pause'} [{st}]: {short(data)}. "
            f"Use the switch on the automation in Zernio's dashboard instead.")
    say(f"✓ {c['name']} is {'ON' if on else 'paused'}")


def cmd_pause(a):
    set_active(a, False)


def cmd_resume(a):
    set_active(a, True)


def cmd_delete(a):
    cfg = load_config(required=False) or {}
    cur = next((x for x in live_automations(cfg) if x.get("name") == a.name or oid(x) == a.name), None)
    if not cur:
        die(f"no live campaign named {a.name!r}")
    say(f"will delete {cur.get('name')} · {fmt_stats(cur)}. Its logs are archived first.")
    if not preview_or_go(a, "delete it"):
        return
    path, n = archive_logs(cur, "deleted")
    ok(call("DELETE", f"/comment-automations/{oid(cur)}"), "delete")
    for c in cfg.get("campaigns", []):
        if c.get("name") == cur.get("name"):
            c.pop("_id", None)
    if cfg:
        save_config(cfg)
    say(f"✓ deleted. {n} log lines kept in {path}")


def mask_name(name, table):
    if name not in table:
        table[name] = f"עוקב/ת {len(table) + 1}"
    return table[name]


def cmd_logs(a):
    cfg = load_config(required=False) or {}
    cur = next((x for x in live_automations(cfg) if x.get("name") == a.name or oid(x) == a.name), None)
    if not cur:
        die(f"no live campaign named {a.name!r}")
    logs = items(ok(call("GET", f"/comment-automations/{oid(cur)}/logs?limit={a.limit}"), "logs"), "logs", "data")
    say(f"{cur.get('name')} · {fmt_stats(cur)} · last {len(logs)}:")
    names = {}
    for l in logs:
        who = l.get("commenterUsername") or l.get("commenterName") or "?"
        if a.mask:
            who = mask_name(who, names)
        text = (l.get("commentText") or "").replace("\n", " ")[:60]
        if a.mask:
            text = "…"
        err = l.get("error") or l.get("platformError") or ""
        say(f"{(l.get('createdAt') or '')[:16].replace('T', ' ')}  {l.get('status', '?'):<9} {who:<22} {text}"
            + (f"  ERR {str(err)[:80]}" if err else ""))


# ------------------------------------------------------------ workflows

def send_node(cfg, node_id, message, buttons=None, x=0, y=0):
    """Instagram workflows can only push plain text with send_message; anything with
    buttons goes out through a webhook node that calls Zernio's own send endpoint.
    bodyTemplate must be a JSON *string*: the engine fills {{vars}} into it as text."""
    payload = {"accountId": cfg["instagram"]["accountId"], "message": message}
    if buttons:
        payload["buttons"] = buttons
    return {"id": node_id, "type": "webhook", "position": {"x": x, "y": y},
            "config": {"url": f"{BASE}/inbox/conversations/{{{{conversationId}}}}/messages", "method": "POST",
                       "headers": {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
                       "bodyTemplate": json.dumps(payload, ensure_ascii=False), "saveAs": f"sent_{node_id}"}}


def text_node(node_id, text, x=0, y=0):
    return {"id": node_id, "type": "send_message", "position": {"x": x, "y": y},
            "config": {"messageType": "text", "text": text}}


def trigger_node(words):
    # A button tap arrives as an inbound message carrying the button title.
    # cooldownHours stops a double tap from running the flow twice.
    return {"id": "t1", "type": "trigger", "position": {"x": 0, "y": 0},
            "config": {"triggerType": "inbound_message", "keywords": words,
                       "matchType": "contains", "cooldownHours": 24}}


def button_core(title):
    """The part of a button title a tap will surely contain: no emoji, no edges."""
    core = re.sub(r"[^\w\s֐-׿'״׳-]", "", title).strip()
    return core or title


def workflow_body(cfg, c, kind, nodes, edges):
    return {"profileId": c.get("profileId") or cfg["profileId"],
            "accountId": c.get("accountId") or cfg["instagram"]["accountId"],
            "platform": "instagram", "name": f"{c['name']} · {kind}",
            "description": f"ezra {VERSION}: {kind} for campaign {c['name']}",
            "nodes": nodes, "edges": edges, "entryNodeId": "t1"}


def first_url_button(c):
    """The campaign's link, re-sent by the reminder, tagged so you can tell the two apart."""
    utm = c.get("utm", "")
    if utm:
        src, _, rest = utm.partition("/")
        utm = f"{src}/dm-reminder/{rest.split('/')[-1] if rest else ''}"
    for b in c.get("buttons", []):
        if b.get("type") == "url":
            return {"type": "url", "title": b["title"], "url": add_utm(b["url"], utm)}
    return None


def create_workflow(a, cfg, c, kind, body):
    block = "remind" if kind == "remind" else "email_capture"
    for o in cfg.get("campaigns", []):
        if o is not c and (o.get(block) or {}).get("button") == (c.get(block) or {}).get("button") \
                and (o.get("_workflows") or {}).get(kind):
            die(f"the {kind} flow of {o['name']} already answers this exact button, for both campaigns. "
                f"Creating a second one would send everything twice.")
    exist = [w for w in live_workflows() if w.get("name") == body["name"]]
    if exist:
        die(f"workflow '{body['name']}' already exists ({oid(exist[0])}, {exist[0].get('status')}). "
            f"Pause or delete it in Zernio first.")
    say(f"━━ flow: {body['name']} ━━")
    for n in body["nodes"]:
        cf, t = n["config"], n["type"]
        if t == "trigger":
            say(f"  ▶ starts when a message contains: {' / '.join(cf['keywords'])}  (that is the button tap; once per 24h per person)")
        elif t == "send_message":
            say(f"  ✉ [{n['id']}] sends: «{cf['text']}»")
        elif t == "delay":
            say(f"  ⏳ waits {cf['delayMinutes'] / 60:g} hours")
        elif t == "wait_for_reply":
            say(f"  ⌛ [{n['id']}] waits up to {cf['timeoutMinutes'] // 60}h for their answer → {cf['saveAs']}")
        elif t == "condition":
            r = cf["rules"][0]
            say(f"  ? [{n['id']}] does {r['variable']} {r['operator']} '{r['value']}'?")
        elif t == "webhook" and "{{conversationId}}" in cf["url"]:
            sent = json.loads(cf["bodyTemplate"])
            btns = " ".join(f"[{b['title']}]" for b in sent.get("buttons", []))
            say(f"  ✉ [{n['id']}] sends: «{sent.get('message')}» {btns}")
        elif t == "webhook":
            say(f"  ↗ [{n['id']}] passes the email to {urllib.parse.urlparse(cf['url']).netloc}")
    if not preview_or_go(a, f"create the {kind} flow"):
        return
    data = ok(call("POST", "/workflows", body), f"create {kind} workflow")
    wf = data.get("workflow", data)
    ok(call("POST", f"/workflows/{oid(wf)}/activate"), "activate workflow")
    c.setdefault("_workflows", {})[kind] = oid(wf)
    save_config(cfg)
    say(f"✓ {kind} flow live ({oid(wf)})")


def cmd_remind(a):
    cfg = load_config()
    c = campaign(cfg, a.name)
    r = c.get("remind") or die(f"campaign {c['name']} has no \"remind\" block")
    link = first_url_button(c) or die("the reminder re-sends the campaign's link button, and it has none")
    hours = float(r.get("hours", 4))
    nodes = [trigger_node([button_core(r["button"])]),
             text_node("s0", r.get("confirm") or f"סגור 👌 אזכיר לך בעוד {hours:g} שעות.", 220),
             {"id": "d1", "type": "delay", "config": {"delayMinutes": int(hours * 60)}, "position": {"x": 440, "y": 0}},
             send_node(cfg, "s1", r.get("message") or "⏰ תזכורת, כמו שביקשת 👇", [link], 660),
             {"id": "end", "type": "end", "config": {}, "position": {"x": 880, "y": 0}}]
    edges = [{"id": "e1", "source": "t1", "target": "s0"}, {"id": "e2", "source": "s0", "target": "d1"},
             {"id": "e3", "source": "d1", "target": "s1"}, {"id": "e4", "source": "s1", "target": "end"}]
    if hours > 23:
        die("a reminder must land inside Meta's 24-hour window, counted from the tap. Keep hours ≤ 23")
    create_workflow(a, cfg, c, "remind", workflow_body(cfg, c, "remind", nodes, edges))


def newsletter_node(cfg, c, x, y):
    nl = cfg.get("newsletter") or {}
    url = nl.get("webhook_url")
    if not url:
        return None
    body = nl.get("webhook_body") or {"email": "{{email_reply}}", "source": "instagram-dm", "campaign": c["name"]}
    tmpl = json.dumps(body, ensure_ascii=False).replace("__CAMPAIGN__", c["name"])
    return {"id": "nl", "type": "webhook", "position": {"x": x, "y": y},
            "config": {"url": url, "method": "POST", "headers": {"Content-Type": "application/json", **(nl.get("headers") or {})},
                       "bodyTemplate": tmpl, "saveAs": "newsletter_result"}}


def cmd_email(a):
    cfg = load_config()
    c = campaign(cfg, a.name)
    e = c.get("email_capture") or die(f"campaign {c['name']} has no \"email_capture\" block")
    nl = newsletter_node(cfg, c, 880, 0)
    nodes = [trigger_node([button_core(e["button"])]),
             text_node("ask", e.get("ask") or "בכיף! כתבו לי כאן את המייל שלכם 👇", 220),
             {"id": "w1", "type": "wait_for_reply", "config": {"timeoutMinutes": 1440, "saveAs": "email_reply"},
              "position": {"x": 440, "y": 0}},
             {"id": "c1", "type": "condition", "position": {"x": 660, "y": 0},
              "config": {"rules": [{"id": "has_at", "variable": "email_reply", "operator": "contains", "value": "@"}]}},
             text_node("thanks", e.get("thanks") or "קיבלתי ✅ זה בדרך למייל שלכם.", 1100),
             text_node("retry", e.get("retry") or "נראה לי שזה לא מייל 🙂 אפשר לכתוב שוב, למשל name@gmail.com", 880, 180),
             {"id": "w2", "type": "wait_for_reply", "config": {"timeoutMinutes": 1440, "saveAs": "email_reply"},
              "position": {"x": 1100, "y": 180}},
             {"id": "c2", "type": "condition", "position": {"x": 1320, "y": 180},
              "config": {"rules": [{"id": "has_at", "variable": "email_reply", "operator": "contains", "value": "@"}]}},
             {"id": "end", "type": "end", "config": {}, "position": {"x": 1540, "y": 0}}]
    edges = [{"id": "e1", "source": "t1", "target": "ask"}, {"id": "e2", "source": "ask", "target": "w1"},
             {"id": "e3", "source": "w1", "target": "c1", "sourceHandle": "reply"},
             {"id": "e4", "source": "w1", "target": "end", "sourceHandle": "timeout"},
             {"id": "e5", "source": "c1", "target": "nl" if nl else "thanks", "sourceHandle": "has_at"},
             {"id": "e6", "source": "c1", "target": "retry", "sourceHandle": "default"},
             {"id": "e7", "source": "retry", "target": "w2"},
             {"id": "e8", "source": "w2", "target": "c2", "sourceHandle": "reply"},
             {"id": "e9", "source": "w2", "target": "end", "sourceHandle": "timeout"},
             {"id": "e10", "source": "c2", "target": "nl" if nl else "thanks", "sourceHandle": "has_at"},
             {"id": "e11", "source": "c2", "target": "end", "sourceHandle": "default"},
             {"id": "e12", "source": "thanks", "target": "end"}]
    if nl:
        nodes.append(nl)
        # Whatever the newsletter answers, the person still gets their thank-you.
        edges += [{"id": "e13", "source": "nl", "target": "thanks", "sourceHandle": "success"},
                  {"id": "e14", "source": "nl", "target": "thanks", "sourceHandle": "error"}]
    else:
        say("no newsletter.webhook_url in config.json: emails are kept in Zernio, export them with `emails`")
    create_workflow(a, cfg, c, "email", workflow_body(cfg, c, "email", nodes, edges))


EMAIL_RE = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def cmd_emails(a):
    cfg = load_config()
    rows, seen = [], set()
    for w in live_workflows():
        if not (w.get("name") or "").endswith("· email"):
            continue
        execs = items(ok(call("GET", f"/workflows/{oid(w)}/executions?limit=100"), "read runs"), "executions", "data")
        for e in execs:  # the API ignores offset; one page of 100, deduped by execution id
            if oid(e) in seen:
                continue
            seen.add(oid(e))
            v = e.get("variables") or {}
            m = EMAIL_RE.search(str(v.get("email_reply") or ""))
            if m:
                rows.append({"email": m.group(0).lower(), "date": (e.get("createdAt") or "")[:10],
                             "campaign": w["name"].split(" · ")[0],
                             "instagram": (v.get("contact") or {}).get("username", "") if isinstance(v.get("contact"), dict) else v.get("contact.username", ""),
                             "newsletter": "sent" if v.get("newsletter_result") else ""})
    uniq = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        uniq[r["email"]] = r
    out = HOME / "emails.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=["email", "date", "campaign", "instagram", "newsletter"])
        wr.writeheader()
        wr.writerows(uniq.values())
    say(f"✓ {len(uniq)} emails → {out}  (import it into your newsletter: Rav Messer, Mailchimp, anything)")


# ---------------------------------------------------------------- audit

def cmd_audit(a):
    cfg = load_config(required=False) or {}
    live = live_automations(cfg)
    by = {x.get("name"): x for x in live}
    fails, warns = [], []
    for x in live:
        n = x.get("name", "?")
        on = x.get("isActive", True)
        if not on:
            continue
        if x.get("linkTracking"):
            fails.append(f"{n}: link tracking is on (redirect links read as spam in DMs)")
        if x.get("trigger", "comment") == "comment" and not x.get("platformPostId"):
            fails.append(f"{n}: answers its word on EVERY post you ever published. Scope it to one post")
        for k in x.get("keywords") or []:
            if x.get("matchMode") == "contains" and len(k.strip()) <= 4:
                (warns if x.get("platformPostId") else fails).append(
                    f"{n}: '{k}' is short and matched anywhere inside a comment"
                    + (" (one post only, so lower risk)" if x.get("platformPostId") else ""))
        if x.get("trigger") == "story_reply" and on:
            if not x.get("platformPostId") and any(k in COMMON_WORDS for k in x.get("keywords") or []):
                fails.append(f"{n}: catches everyday words in replies to ALL your stories "
                             f"({', '.join(k for k in x['keywords'] if k in COMMON_WORDS)}). Pause it when the story is gone")
            if not x.get("keywords") and not x.get("platformPostId"):
                fails.append(f"{n}: answers EVERY reply to EVERY story")
        s = x.get("stats") or {}
        if s.get("dmsFailed", 0) and s.get("dmsFailed", 0) >= max(3, 0.2 * max(1, s.get("triggered", 0))):
            warns.append(f"{n}: {s['dmsFailed']} failed DMs of {s.get('triggered', 0)}. Read `logs {n}`")
    for c in cfg.get("campaigns", []):
        x = by.get(c["name"])
        if not x:
            continue
        if set(c.get("keywords", [])) != set(x.get("keywords") or []):
            warns.append(f"{c['name']}: words in config.json differ from the live ones. Run `update {c['name']}`")
    say(f"{len(live)} live campaign(s) checked")
    for f in fails:
        say(f"  ✗ {f}")
    for w in warns:
        say(f"  ! {w}")
    if not fails:
        say("  ✓ nothing dangerous")
    sys.exit(1 if fails else 0)


# ---------------------------------------------------------------- panel

def parse_ts(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def cmd_panel(a):
    cfg = load_config(required=False) or {}
    live = live_automations(cfg)
    wfs = live_workflows()
    now = datetime.now(timezone.utc)
    days = [(now - timedelta(days=i)).date() for i in range(13, -1, -1)]
    names, people, feed = {}, set(), []
    camps = []
    for x in live:
        logs = []
        if not a.fast:
            st, data = call("GET", f"/comment-automations/{oid(x)}/logs?limit=100")
            logs = items(data, "logs", "data") if 200 <= st < 300 else []
        per_day = Counter()
        last = None
        for l in logs:
            t = parse_ts(l.get("createdAt"))
            if not t:
                continue
            last = max(last, t) if last else t
            per_day[t.date()] += 1
            who = l.get("commenterUsername") or l.get("commenterName") or "?"
            people.add(who)
            feed.append({"t": t.isoformat(), "campaign": x.get("name"), "who": who,
                         "text": "" if a.mask else (l.get("commentText") or "")[:90],
                         "status": l.get("status") or "", "source": l.get("source") or x.get("trigger", "comment"),
                         "err": "" if not (l.get("error") or l.get("platformError")) else str(l.get("error") or l.get("platformError"))[:120]})
        s = x.get("stats") or {}
        camps.append({"name": x.get("name"), "id": oid(x), "active": x.get("isActive", True),
                      "trigger": x.get("trigger", "comment"), "keywords": x.get("keywords") or [],
                      "match": x.get("matchMode"), "post": x.get("platformPostId") or "",
                      "triggered": s.get("triggered", 0), "sent": s.get("dmsSent", 0), "failed": s.get("dmsFailed", 0),
                      "read": s.get("read", 0), "unique": s.get("uniqueContacts", 0), "clicks": s.get("linkClicks", 0),
                      "gate": bool(x.get("followGate")), "gate_sent": s.get("followGateSent", 0),
                      "gate_passed": s.get("followGatePassed", 0),
                      "buttons": [b.get("title") for b in x.get("buttons") or []],
                      "created": (x.get("createdAt") or "")[:10], "last": last.isoformat() if last else "",
                      "series": [per_day.get(d, 0) for d in days]})
    camps.sort(key=lambda c: (c["active"], c["last"] or c["created"]), reverse=True)
    feed.sort(key=lambda f: f["t"], reverse=True)
    if a.mask:  # aliases numbered in the order the feed shows them
        for f in feed:
            f["who"] = mask_name(f["who"], names)
    # The audit, reused in-process so the panel shows the same warnings as the CLI.
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            cmd_audit(a)
        except SystemExit:
            pass
    alerts = [l.strip() for l in buf.getvalue().splitlines() if l.strip().startswith(("✗", "!"))]
    flows = [{"name": w.get("name"), "status": w.get("status"), "started": w.get("totalStarted", 0),
              "completed": w.get("totalCompleted", 0), "id": oid(w)} for w in wfs]
    ig = cfg.get("instagram", {})
    data = {
        "generated": now.isoformat(), "mask": bool(a.mask), "version": VERSION,
        "account": "@חשבון_הדגמה" if a.mask else ("@" + ig.get("username", "") if ig.get("username") else ""),
        "days": [d.isoformat() for d in days],
        "totals": {"triggered": sum(c["triggered"] for c in camps), "sent": sum(c["sent"] for c in camps),
                   "failed": sum(c["failed"] for c in camps), "read": sum(c["read"] for c in camps),
                   "unique": sum(c["unique"] for c in camps), "live": sum(1 for c in camps if c["active"]),
                   "campaigns": len(camps), "people": len(people),
                   "series": [sum(c["series"][i] for c in camps) for i in range(len(days))]},
        "campaigns": camps, "feed": feed[:60], "flows": flows, "alerts": alerts,
        "emails": count_emails_file(),
    }
    tpl = (TEMPLATES / "panel.html").read_text(encoding="utf-8")
    out = HOME / "panel.html"
    HOME.mkdir(parents=True, exist_ok=True)
    out.write_text(tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")
    say(f"✓ panel → {out}  ({len(camps)} campaigns, {data['totals']['sent']} DMs sent"
        + (", recording mode: names hidden" if a.mask else "") + ")")
    if a.open:
        open_file(out)


def count_emails_file():
    f = HOME / "emails.csv"
    if not f.exists():
        return 0
    with open(f, encoding="utf-8-sig") as fh:
        return max(0, sum(1 for _ in fh) - 1)


def open_file(p):
    if sys.platform == "darwin":
        subprocess.run(["open", str(p)])
    elif os.name == "nt":
        os.startfile(str(p))  # noqa
    else:
        say(f"open {p}")


def cmd_builder(a):
    src = TEMPLATES / "builder.html"
    out = HOME / "builder.html"
    HOME.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out)
    say(f"✓ builder → {out}")
    if a.open:
        open_file(out)


# ------------------------------------------------------------------ main

def main():
    p = argparse.ArgumentParser(prog="ezra", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *pos, yes=False, **kw):
        sp = sub.add_parser(name)
        for x in pos:
            sp.add_argument(x)
        if yes:
            sp.add_argument("--yes", action="store_true", help="really do it (without it: preview only)")
        for k, v in kw.items():
            sp.add_argument("--" + k.replace("_", "-"), dest=k, **v)
        sp.set_defaults(fn=fn)
        return sp

    flag = {"action": "store_true"}
    add("key", cmd_key, no_open=flag)
    add("check", cmd_check, account={"default": ""})
    add("posts", cmd_posts, limit={"type": int, "default": 12}, platform={"default": "instagram"})
    add("list", cmd_list)
    add("show", cmd_show, "name", json=flag, offline=flag)
    add("create", cmd_create, "name", yes=True, paused=flag)
    add("update", cmd_update, "name", yes=True)
    add("pause", cmd_pause, "name")
    add("resume", cmd_resume, "name")
    add("delete", cmd_delete, "name", yes=True)
    add("logs", cmd_logs, "name", limit={"type": int, "default": 30}, mask=flag)
    add("remind", cmd_remind, "name", yes=True)
    add("email", cmd_email, "name", yes=True)
    add("emails", cmd_emails)
    add("audit", cmd_audit)
    add("panel", cmd_panel, open=flag, mask=flag, fast={"action": "store_true", "help": "skip the logs (numbers only)"})
    add("builder", cmd_builder, open=flag)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
