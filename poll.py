import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text("utf-8"))
STATE_FILE = ROOT / "state" / "seen.json"
BASE = "https://sakurazaka46.com"
RSSHUB = (os.environ.get("RSSHUB_BASE") or CFG["rsshub_base"]).rstrip("/")
TIMEOUT = 20
KEEP = 300          # remembered ids per source
WARN_AFTER = 12     # consecutive failed runs before a warning (~2h at 10 min)
JST = dt.timezone(dt.timedelta(hours=9))

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (compatible; S46FeedBot/1.0)"

LABEL = {"blog": "📝 Member blog", "news": "📰 Official news", "youtube": "▶️ YouTube",
         "tiktok": "🎵 TikTok", "x": "𝕏 Post", "instagram": "📸 Instagram",
         "ticket": "🎫 Ticket", "fcnews": "💗 Fan club"}
BIG_IMAGE = {"youtube", "tiktok", "x", "instagram"}
HUB = {"tiktok": ["/tiktok/user/@sakurazaka46.officialtk"],
       "x": ["/twitter/user/sakurazaka46"],
       "instagram": ["/instagram/user/sakurazaka46jp", "/instagram/user/sakurazaka46_info_official"]}

# Roster as listed on the official site (blog/schedule pages). Update when it changes.
ROSTER = ["浅井恋乃未", "石森璃花", "稲熊ひな", "遠藤光莉", "遠藤理子", "大園玲", "大沼晶保", "小田倉麗奈",
          "勝又春", "小池美波", "幸阪茉里乃", "小島凪紗", "佐藤愛桜", "谷口愛季", "田村保乃", "中川智尋",
          "中嶋優月", "藤吉夏鈴", "松田里奈", "松本和子", "的野美青", "向井純葉", "村井優", "村山美羽",
          "目黒陽色", "森田ひかる", "守屋麗奈", "山川宇衣", "山﨑天", "山下瞳月", "山田桃実", "増本綺良"]
# Optional romaji aliases so config can use English names.
ROMAJI = {"Matsuda Rina": "松田里奈", "Tamura Hono": "田村保乃", "Yamasaki Ten": "山﨑天",
          "Morita Hikaru": "森田ひかる", "Fujiyoshi Karin": "藤吉夏鈴", "Ozono Rei": "大園玲",
          "Onuma Akiho": "大沼晶保", "Moriya Rena": "守屋麗奈", "Endo Hikari": "遠藤光莉",
          "Ishimori Rika": "石森璃花", "Katsumata Haru": "勝又春", "Odakura Reina": "小田倉麗奈",
          "Kojima Nagisa": "小島凪紗", "Mukai Itoha": "向井純葉", "Murayama Miu": "村山美羽",
          "Masumoto Kira": "増本綺良"}


def norm(s):
    return s.replace("﨑", "崎").replace("\u3000", "").replace(" ", "").lower()


KNOWN = {norm(n) for n in ROSTER}


def resolve(name):
    n = norm(name)
    for r, k in ROMAJI.items():
        if n in (norm(r), norm(k)):
            return k
    return name.strip()


def now():
    return dt.datetime.now(JST)


def get(url):
    r = S.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def item(src, id_, title, url, text=None, thumb=None, author=None, desc=None, tag=None):
    return {"source": src, "id": id_, "title": title[:256], "url": url, "text": text or title,
            "thumb": thumb, "author": author, "desc": desc, "tag": tag}


# ---- Official site ---------------------------------------------------------
DATE_SLASH = re.compile(r"(\d{4}/\d{2}/\d{2})")
NEWS_RE = re.compile(r"^(?P<cat>\S+)\s+(?P<date>\d{4}\.\d{2}\.\d{2})\s+(?P<title>.+)$", re.S)


def fetch_blog():
    soup = BeautifulSoup(get(BASE + CFG["site"]["blog"]), "html.parser")
    out = {}
    for a in soup.select('a[href*="/diary/detail/"]'):
        m_id = re.search(r"/diary/detail/(\d+)", a["href"])
        raw = a.get_text("\n", strip=True)
        flat = " ".join(raw.split())
        m = DATE_SLASH.search(flat)
        if not m_id or not m or m_id.group(1) in out:
            continue
        name = flat[:m.start()].strip()
        rest = re.sub(r"\s*MORE$", "", flat[m.end():].strip())
        lines = [x for x in raw.split("\n") if x.strip() and x.strip() != "MORE"]
        k = next((n for n, x in enumerate(lines) if m.group(1) in x), None)
        after = lines[k + 1:] if k is not None else []
        title, desc = (after[0], after[1]) if len(after) >= 2 else (rest[:60], rest)
        box = a.find_parent("li") or a
        img = box.find("img")
        out[m_id.group(1)] = item(
            "blog", m_id.group(1), f"{name}: {title}", urljoin(BASE, a["href"]), name, 
            urljoin(BASE, img["src"]) if img and img.get("src") else None,
            author=name, desc=desc[:200], tag=m.group(1))
    if not out:
        raise RuntimeError("0 blog posts found; page layout may have changed")
    return list(out.values())


def fetch_month_list(kind, frag, id_re):
    """News-style lists: 'category YYYY.MM.DD title', one page per month (dy=YYYYMM)."""
    t = now()
    months = [t.strftime("%Y%m")]
    if t.day <= 3:  # early in the month the list may still be empty
        months.append((t.replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m"))
    out = {}
    for ym in months:
        soup = BeautifulSoup(get(BASE + CFG["site"][kind].format(ym=ym)), "html.parser")
        for a in soup.select(f'a[href*="{frag}"]'):
            m_id = re.search(id_re, a["href"])
            if not m_id or m_id.group(1) in out:
                continue
            flat = " ".join(a.get_text(" ", strip=True).split())
            m = NEWS_RE.match(flat)
            cat, date, title = (m["cat"], m["date"], m["title"]) if m else (None, None, flat)
            out[m_id.group(1)] = item(kind, m_id.group(1), title, urljoin(BASE, a["href"]),
                                      tag=" · ".join(x for x in (cat, date) if x))
    if not out:
        raise RuntimeError(f"0 {kind} items found; page layout may have changed")
    return list(out.values())


def fetch_news():
    return fetch_month_list("news", "/news/detail/", r"/news/detail/([A-Za-z0-9]+)")


def fetch_fcnews():
    return fetch_month_list("fcnews", "/group/detail/", r"/group/detail/([A-Za-z0-9]+)")


TICKET_RE = re.compile(r"^(?P<date>\d{4}\.\d{2}\.\d{2})\s*(?P<title>.+)$", re.S)


def fetch_ticket():
    soup = BeautifulSoup(get(BASE + CFG["site"]["ticket"]), "html.parser")
    out = {}
    for a in soup.select('a[href*="/ticket/detail/"]'):
        m_id = re.search(r"/ticket/detail/([^/?#]+)", a["href"])
        if not m_id or m_id.group(1) in out:
            continue
        flat = " ".join(a.get_text(" ", strip=True).split())
        m = TICKET_RE.match(flat)
        date, title = (m["date"], m["title"]) if m else (None, flat)
        out[m_id.group(1)] = item("ticket", m_id.group(1), title, urljoin(BASE, a["href"]), tag=date)
    if not out:
        raise RuntimeError("0 ticket items found; page layout may have changed")
    return list(out.values())


# ---- Schedule (daily digest) ----------------------------------------------
SCHED_DATE = re.compile(r"^(\d{4}\.\d{2}\.\d{2})(?:\s+(\d{1,2}:\d{2}.*))?$")
TIME_LINE = re.compile(r"^\d{1,2}:\d{2}")


def schedule_entries(t):
    html = get(BASE + CFG["site"]["schedule"].format(ymd=t.strftime("%Y%m%d")))
    lines = [x.strip() for x in BeautifulSoup(html, "html.parser").get_text("\n").split("\n") if x.strip()]
    entries, i = [], 0
    while i < len(lines):
        m = SCHED_DATE.match(lines[i])
        if not m:
            i += 1
            continue
        date, tm, j = m.group(1), m.group(2), i + 1
        if not tm and j < len(lines) and TIME_LINE.match(lines[j]):
            tm, j = lines[j], j + 1
        if j + 1 >= len(lines):
            break
        cat, title, k, members = lines[j], lines[j + 1], j + 2, []
        if k < len(lines) and lines[k] == "メンバー":
            k += 1
            while k < len(lines) and (norm(lines[k]) in KNOWN or lines[k] == "櫻坂46"):
                members.append(lines[k])
                k += 1
        entries.append({"date": date, "time": tm, "cat": cat, "title": title, "members": members})
        i = k
    return entries


def maybe_digest(state):
    cfg = CFG.get("schedule_digest", {})
    t = now()
    today = t.strftime("%Y-%m-%d")
    if not cfg.get("enabled") or t.hour < int(cfg.get("hour_jst", 8)) or state.get("digest_date") == today:
        return
    url = webhook_for("schedule")
    if not url:
        return
    try:
        todays = [e for e in schedule_entries(t) if e["date"] == t.strftime("%Y.%m.%d")]
        if todays:
            todays.sort(key=lambda e: (e["time"] is not None, (e["time"] or "").zfill(5)))
            rows = []
            for e in todays:
                who = f" — {', '.join(e['members'])}" if e["members"] else ""
                rows.append(f"`{e['time'] or '終日'}` [{e['cat']}] **{e['title']}**{who}")
            desc = "\n".join(rows)[:4000]
            send(url, None, {"title": f"📅 Today's schedule · {t.strftime('%m/%d')}", "description": desc,
                             "url": BASE + CFG["site"]["schedule"].format(ymd=t.strftime("%Y%m%d")),
                             "color": 0xF19DB5})
        state["digest_date"] = today
        print(f"[schedule] digest: {len(todays)} entries")
    except Exception as ex:
        print(f"[schedule] FAILED: {ex}")


# ---- YouTube / social ------------------------------------------------------
def get_retry(url, tries=3, wait=4):
    """YouTube's RSS endpoint sometimes returns a temporary 404/5xx, so retry before giving up."""
    for n in range(tries):
        try:
            return get(url)
        except requests.HTTPError as ex:
            code = ex.response.status_code if ex.response is not None else 0
            if n == tries - 1 or code not in (404, 429, 500, 502, 503, 504):
                raise
            time.sleep(wait * (n + 1))


def fetch_youtube(state):
    ids = state.setdefault("yt_ids", {})
    out, errors = [], []
    for label, handle in CFG["youtube_handles"].items():
        try:  # one failing channel should not hide the other
            if handle not in ids:
                html = get(f"https://www.youtube.com/@{handle}")
                m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(r"channel_id=(UC[\w-]{22})", html)
                if not m:
                    raise RuntimeError(f"channel id not found for @{handle}")
                ids[handle] = m.group(1)
            feed = feedparser.parse(get_retry(f"https://www.youtube.com/feeds/videos.xml?channel_id={ids[handle]}"))
            for e in feed.entries[:10]:
                th = e.media_thumbnail[0]["url"] if e.get("media_thumbnail") else None
                out.append(item("youtube", e.id, f"[{label}] {e.title}", e.link, e.title, th))
        except Exception as ex:
            errors.append(f"{label}: {ex}")
            print(f"[youtube] {label} failed: {ex}")
    if not out:
        raise RuntimeError("; ".join(errors)[:150] or "no videos returned")
    return out


def fetch_hub(src):
    out, errors = [], []
    for p in HUB[src]:
        try:
            feed = feedparser.parse(get(RSSHUB + p))
            if not feed.entries:
                raise RuntimeError("empty feed")
            for e in feed.entries[:10]:
                summ = e.get("summary", "")
                m = re.search(r'<img[^>]+src="([^"]+)"', summ)
                title = BeautifulSoup(e.get("title") or summ, "html.parser").get_text(" ", strip=True)[:200]
                out.append(item(src, e.get("id") or e.link, title, e.link, title, m.group(1) if m else None))
        except Exception as ex:
            errors.append(f"{p}: {ex}")
    if not out:
        raise RuntimeError("; ".join(errors)[:150])
    return out


def fetch(src, state):
    if src == "blog":
        return fetch_blog()
    if src == "news":
        return fetch_news()
    if src == "fcnews":
        return fetch_fcnews()
    if src == "ticket":
        return fetch_ticket()
    if src == "youtube":
        return fetch_youtube(state)
    return fetch_hub(src)


# ---- Discord ---------------------------------------------------------------
def webhook_for(src):
    return os.environ.get(f"WEBHOOK_{src.upper()}") or os.environ.get("DISCORD_WEBHOOK_URL")


def send(url, content, embed=None):
    body = {"username": "SakuBot", "content": content or None,
            "allowed_mentions": {"parse": ["users", "roles"]}}
    if embed:
        body["embeds"] = [embed]
    for _ in range(3):
        r = S.post(url, json=body, timeout=TIMEOUT)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        r.raise_for_status()
        return
    raise RuntimeError("rate limited")


def build_embed(i):
    label = LABEL[i["source"]] + (f" · {i['tag']}" if i.get("tag") else "")
    e = {"title": i["title"] or "New post", "url": i["url"], "color": 0xF19DB5, "author": {"name": label}}
    if i.get("desc"):
        e["description"] = i["desc"]
    if i["thumb"]:
        e["image" if i["source"] in BIG_IMAGE else "thumbnail"] = {"url": i["thumb"]}
    return e


def pings_for(i):
    p = []
    if CFG.get("ping_role_id"):
        p.append(f"<@&{CFG['ping_role_id']}>")
    if i["source"] == "blog" and i.get("author"):
        for member, users in CFG.get("member_pings", {}).items():
            if norm(resolve(member)) == norm(i["author"]):
                p += [f"<@{u}>" for u in users]
    return " ".join(dict.fromkeys(p))


# ---- Main ------------------------------------------------------------------
def main():
    if not os.environ.get("DISCORD_WEBHOOK_URL"):
        sys.exit("DISCORD_WEBHOOK_URL is not set")
    state = json.loads(STATE_FILE.read_text("utf-8")) if STATE_FILE.exists() else {}
    seen, fails = state.setdefault("seen", {}), state.setdefault("fails", {})
    limit = int(CFG.get("max_posts_per_run", 5))

    for src, enabled in CFG["sources"].items():
        if not enabled or not webhook_for(src):
            continue
        try:
            items = fetch(src, state)
        except Exception as ex:
            fails[src] = fails.get(src, 0) + 1
            print(f"[{src}] FAILED ({fails[src]}): {ex}")
            if fails[src] == WARN_AFTER and src not in CFG.get("quiet_sources", []):
                try:
                    send(os.environ["DISCORD_WEBHOOK_URL"],
                         f"⚠️ **{src}** has failed {WARN_AFTER} runs in a row: {str(ex)[:150]}")
                except Exception:
                    pass
            continue
        fails[src] = 0
        known = seen.get(src)
        if known is None:  # first run: remember what exists, post nothing
            seen[src] = [i["id"] for i in items][:KEEP]
            print(f"[{src}] seeded {len(items)} items")
            continue
        known_set = set(known)
        new = [i for i in items if i["id"] not in known_set]
        added = [i["id"] for i in new[limit:]]  # overflow is marked seen, not posted
        for i in reversed(new[:limit]):
            try:
                send(webhook_for(src), pings_for(i), build_embed(i))
                added.append(i["id"])
                time.sleep(1)
            except Exception as ex:
                print(f"[{src}] post failed, will retry next run: {ex}")
        seen[src] = (known + added)[-KEEP:]
        print(f"[{src}] {len(new)} new")

    maybe_digest(state)
    state["heartbeat"] = now().strftime("%Y-%m")  # monthly commit keeps the repo active
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")


if __name__ == "__main__":
    main()
