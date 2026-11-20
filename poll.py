if mc and nm:
            _CT[norm(nm)] = mc.group(1)
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
            "blog", m_id.group(1), f"{name}: {title}", urljoin(BASE, a["href"]), name, None,
            author=name, desc=desc[:BLOG_PREVIEW], tag=fmt_date(m.group(1)))
        out[m_id.group(1)]["title_raw"] = title
        out[m_id.group(1)]["icon"] = urljoin(BASE, img["src"]) if img and img.get("src") else None
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
                who = f" — {', '.join(display_name(m, state) for m in e['members'])}" if e["members"] else ""
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


VIDEO_RE = re.compile(r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\s+UP\s+(.+)$", re.S)


def fetch_site_videos():
    """Official site VIDEO page: lists the latest uploads of both YouTube channels (the page uses the YouTube ID)."""
    soup = BeautifulSoup(get(BASE + CFG["site"]["video"]), "html.parser")
    heading = re.compile(r"櫻坂チャンネル|OFFICIAL YouTube CHANNEL")
    out = {}
    for a in soup.select('a[href*="/contents/"]'):
        m_id = re.search(r"/contents/([\w-]{11})(?:[?#]|$)", a["href"])
        if not m_id or m_id.group(1) in out:
            continue
        flat = " ".join(a.get_text(" ", strip=True).split())
        m = VIDEO_RE.match(flat)
        title = m.group(4) if m else flat
        sect = a.find_previous(string=heading)
        label = "variety" if sect and "チャンネル" in sect else "music"
        vid = m_id.group(1)
        out[vid] = item("youtube", f"yt:video:{vid}", f"[{label}] {title}",
                        f"https://www.youtube.com/watch?v={vid}", title,
                        f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
    if not out:
        raise RuntimeError("0 videos found on the site video page")
    return list(out.values())


def fetch_youtube_rss(state):
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
            print(f"[youtube] RSS {label} failed: {ex}")
    return out, errors


def fetch_youtube(state):
    """YouTube RSS first, plus the official site's video page as a fallback. Both use the same ID format, so nothing posts twice."""
    out, errors = fetch_youtube_rss(state)
    seen_ids = {i["id"] for i in out}
    try:
        for i in fetch_site_videos():
            if i["id"] not in seen_ids:
                out.append(i)
                seen_ids.add(i["id"])
    except Exception as ex:
        errors.append(f"site: {ex}")
        print(f"[youtube] site fallback failed: {ex}")
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


# ---- Translation (free machine translation) --------------------------------
TR = CFG.get("translate", {})
PREVIEW = int(CFG.get("preview_chars", 300))
_ROMAJI_REV = {}
for _r, _k in ROMAJI.items():
    _ROMAJI_REV[_k] = _r
    _ROMAJI_REV[_k.replace("﨑", "崎")] = _r
_tr = {"ok": 0, "fail": 0, "streak": 0, "calls": 0}


def prep_jp(text):
    """Protect names and the group name before machine translation."""
    for kanji, romaji in _ROMAJI_REV.items():
        text = text.replace(kanji, f" {romaji} ")
    return text.replace("櫻坂46", "Sakurazaka46").replace("櫻坂", "Sakurazaka")


def _google(text, tgt):
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source="ja", target=tgt).translate(text)


def _mymemory(text, tgt):
    from deep_translator import MyMemoryTranslator
    return MyMemoryTranslator(source="ja-JP", target={"en": "en-GB", "vi": "vi-VN"}[tgt]).translate(text)


def translate(text, tgt):
    text = (text or "").strip()
    if not text or _tr["streak"] >= 3 or _tr["calls"] >= int(TR.get("max_calls_per_run", 24)):
        return None
    _tr["calls"] += 1
    src_text = prep_jp(text)[:int(TR.get("max_chars", 400))]  # MyMemory accepts ~500 chars
    for fn in (_google, _mymemory):
        try:
            out = fn(src_text, tgt)
            if out and out.strip():
                _tr["ok"] += 1
                _tr["streak"] = 0
                time.sleep(0.4)
                return " ".join(out.split())
        except Exception as ex:
            print(f"[translate] {fn.__name__} {tgt} failed: {str(ex)[:80]}")
    _tr["fail"] += 1
    _tr["streak"] += 1
    return None


def add_translations(i):
    """Only the title is translated. Previews and details stay as they are."""
    if not TR.get("enabled") or i["source"] not in TR.get("sources", []):
        return
    # Skip translating if it's a blog post with no title
    if i["source"] == "blog" and not (i.get("title_raw") or "").strip():
        return
    title = i.get("title_raw") or i["title"]
    for lg in TR.get("languages", ["en", "vi"]):
        t = translate(title, lg)
        if t:
            i["tr"][lg] = (t, None)


# ---- Detail pages: preview, member photo, ticket dates ----------------------
WD = {"月": "Mon", "火": "Tue", "水": "Wed", "木": "Thu", "金": "Fri", "土": "Sat", "日": "Sun", "祝": "Hol"}
GLOSS = [("夕方以降", " evening or later"), ("オフィシャル先行", "Official presale"), ("イオンカード先行", "AEON Card presale"),
         ("ファンクラブ抽選先行", "FC lottery presale"), ("Leminoスペシャルシート", "Lemino Special Seat"),
         ("全席指定", "Reserved seats"), ("親子・女性エリア", "Parent-child / women's area")]
SECTIONS = [("日程", "📅 Dates · Ngày"), ("会場", "📍 Venue · Địa điểm"), ("料金", "💴 Price · Giá vé"),
            ("受付期間", "📝 Application · Đăng ký"), ("先行受付スケジュール", "🎟 Presale · Bán trước"),
            ("チケット一般発売", "🛒 General sale · Bán đại trà")]
STOP_LINE = ("【", "※", "＜", "■", "―", "<", "●", "ファンクラブ", "受付URL", "以下")
BODY_STOP = ("NEW ENTRY", "RECENT TICKET NEWS", "TICKET 一覧へ", "お申し込みは会員のみ")
DATE_LINE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")


def fmt_jp(text):
    """Dates, times and prices are language neutral, so they are reformatted instead of machine translated."""
    text = re.sub(r"(\d{4})年(\d{1,2})月(\d{1,2})日", lambda m: f"{m[1]}/{int(m[2]):02d}/{int(m[3]):02d}", text)
    text = re.sub(r"(?<![\d/])(\d{1,2})月(\d{1,2})日", lambda m: f"{int(m[1]):02d}/{int(m[2]):02d}", text)
    text = re.sub(r"[(（]([月火水木金土日祝][月火水木金土日祝･・]*)[)）]",
                  lambda m: " (" + "/".join(WD[c] for c in re.findall("[月火水木金土日祝]", m[1])) + ")", text)
    text = text.replace("開場", "doors ").replace("開演", "start ").replace("〜", " – ").replace("～", " – ")
    text = re.sub(r"([\d,]+)円(?:[（(]税込[）)])?", lambda m: f"¥{m[1]}" + (" (tax incl.)" if "税込" in m[0] else ""), text)
    for jp, en in GLOSS:
        text = text.replace(jp, en)
    text = re.sub(r"\)(\d)", r") \1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip("– ").strip()


def body_lines(url, title):
    soup = BeautifulSoup(get(url), "html.parser")
    root = soup.body or soup
    for t in root(["script", "style"]):
        t.decompose()
    lines = [x.strip() for x in root.get_text("\n").split("\n") if x.strip()]
    key = norm(title)
    start = next((n for n, x in enumerate(lines) if norm(x) == key), None)
    if start is None:
        start = next((n for n, x in enumerate(lines) if len(key) >= 12 and norm(x).startswith(key[:12])), None)
    if start is None:
        return []
    out = []
    for x in lines[start + 1:]:
        if x.startswith(BODY_STOP):
            break
        out.append(x)
    return out


def preview_from(lines, limit):
    out, n = [], 0
    for x in lines:
        if x.startswith(("―", "<", "＜", "【", "以下ご確認")) or DATE_LINE.match(x):
            break
        if x.startswith(("●", "※", "■")):
            continue
        out.append(x)
        n += len(x)
        if n >= limit:
            break
    return " ".join(out)[:limit]


def extract_sections(lines):
    found = {}
    for n, x in enumerate(lines):
        m = re.match(r"^【(.+?)】\s*(.*)$", x)
        if not m or m.group(1) not in dict(SECTIONS) or m.group(1) in found:
            continue
        label, vals = m.group(1), ([m.group(2)] if m.group(2) else [])
        stops = ("【", "※", "＜") if label == "料金" else STOP_LINE
        for y in lines[n + 1:n + 6]:
            if y.startswith(stops):
                break
            vals.append(y)
            if label == "会場":
                break
        vals = [v for v in vals if v]
        if vals:
            found[label] = vals[:4]
    return found


def enrich_detail(i):
    lines = body_lines(i["url"], i["title"])
    if not lines:
        return
    i["preview"] = preview_from(lines, PREVIEW) or i["preview"]
    sec = extract_sections(lines)
    for jp, name in SECTIONS:
        if jp in sec:
            i["fields"].append((name, "\n".join(fmt_jp(v) for v in sec[jp])))
    m = re.search(r"抽選結果の発表は、(.+?)を予定", "\n".join(lines))
    if m:
        i["fields"].append(("📣 Results · Kết quả", fmt_jp(m.group(1))))


def member_photos(state, want):
    cache = state.setdefault("member_photos", {})
    today = now().strftime("%Y-%m-%d")
    if want in cache or state.get("photos_day") == today:
        return cache
    state["photos_day"] = today
    soup = BeautifulSoup(get(BASE + CFG["site"]["news"].format(ym=now().strftime("%Y%m"))), "html.parser")
    for img in soup.select('img[src*="400_320_102400"]'):
        name = img.find_next(string=lambda s: isinstance(s, str) and s.strip())
        if name:
            cache[norm(name.strip())] = urljoin(BASE, img["src"])
    return cache


def prev_blog(i):
    """Date of the member's blog before this one, read from her own blog list (newest first)."""
    ct = _CT.get(norm(i.get("author") or ""))
    if not ct:
        return None
    soup = BeautifulSoup(get(f"{BASE}/s/s46/diary/blog/list?ima=0000&ct={ct}"), "html.parser")
    cur = int(i["id"])
    for a in soup.select('a[href*="/diary/detail/"]'):
        m_id = re.search(r"/diary/detail/(\d+)", a["href"])
        flat = " ".join(a.get_text(" ", strip=True).split())
        m = DATE_SLASH.search(flat)
        if m_id and m and int(m_id.group(1)) < cur and norm(i["author"]) in norm(flat):
            y, mo, d = (int(x) for x in m.group(1).split("/"))
            return dt.date(y, mo, d)
    return None


def enrich_blog(i, state):
    soup = BeautifulSoup(get(i["url"]), "html.parser")

    # On the detail page, the post title is specifically inside the blog article header (<h1 class="title"> or the <h1> right before the date/body).
    # If the member posted without a title, that <h1> exists on the page with empty text, whereas fetch_blog() fell back to the first body line.
    h1 = soup.select_one("h1.title") or soup.select_one(".box-ttl h1")
    if not h1:
        # Fallback: find the <h1> that is not the site logo ("櫻坂46公式サイト" / empty logo link)
        for cand in soup.find_all("h1"):
            if cand.find("img"):
                continue
            h1 = cand
            break

    if h1 is not None:
        raw_title = " ".join(h1.get_text().split())
        i["title_raw"] = raw_title if raw_title else None
    else:
        i["title_raw"] = None

    texts, img, ts, images, romaji = [], None, None, [], None
    for el in (h1.next_elements if h1 else []):
        if isinstance(el, Comment):
            continue
        if isinstance(el, NavigableString):
            if h1 is not None and el.find_parent("h1") is h1:
                continue  # the heading itself
            if el.parent is not None and el.parent.name in ("script", "style"):
                continue
            s = el.strip()
            if not s:
                continue
            m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2}) (\d{1,2}):(\d{2})$", s)
            if m:
                ts = dt.datetime(*map(int, m.groups()), tzinfo=JST).isoformat()
                break
            if s == "前へ":
                break
            if not texts and re.match(r"^[A-Z][A-Z .'\-]+$", s):  # romaji name line under the title
                parts = s.title().split()
                romaji = " ".join(reversed(parts)) if len(parts) == 2 else s.title()  # family name first
                continue
            texts.append(s)
        elif getattr(el, "name", None) == "img":
            raw = el.get("src") or el.get("data-src") or el.get("data-original") or ""
            if "/files/14/diary/" in raw:  # post photos only, not the member profile picture
                full = urljoin(BASE, raw)
                if full not in images:
                    images.append(full)
                img = img or full
    if texts:
        full = " ".join(texts)
        i["preview"] = full[:BLOG_PREVIEW].rstrip() + ("…" if len(full) > BLOG_PREVIEW else "")
    i["ts"] = ts or i["ts"]
    try:
        pd = prev_blog(i)
        if pd:
            cur = dt.datetime.fromisoformat(i["ts"]).date() if i["ts"] else now().date()
            n = (cur - pd).days
            i["prev"] = (pd.strftime("%Y/%m/%d"), "same day" if n <= 0 else f"{n} day{'s' if n != 1 else ''} earlier")
    except Exception as ex:
        print(f"[blog] previous blog lookup failed: {ex}")
    if romaji and i.get("author"):
        state.setdefault("romaji", {})[norm(i["author"])] = romaji
    if i.get("author"):
        i["romaji"] = romaji or state.get("romaji", {}).get(norm(i["author"]))
        shown = display_name(i["author"], state, i["romaji"])
        title_label = i["title_raw"] or "無題 (Untitled)"
        i["title"] = f"{shown}: {title_label}"[:256]
    i["images"] = images
    if img:
        i["thumb"] = img
    if i.get("author"):
        i["icon"] = member_photos(state, norm(i["author"])).get(norm(i["author"])) or i.get("icon")


def enrich(i, state):
    try:
        if i["source"] == "blog":
            enrich_blog(i, state)
        elif i["source"] in ("news", "ticket"):
            enrich_detail(i)
    except Exception as ex:
        print(f"[{i['source']}] enrich failed: {ex}")


# ---- Discord ---------------------------------------------------------------
def webhook_for(src):
    return os.environ.get(f"WEBHOOK_{src.upper()}") or os.environ.get("DISCORD_WEBHOOK_URL")


def send(url, content, embed=None, embeds=None, files=None):
    body = {"username": "SakuBot", "content": content or None,
            "allowed_mentions": {"parse": ["users", "roles"]}}
    if embeds:
        body["embeds"] = embeds
    elif embed:
        body["embeds"] = [embed]
    for _ in range(3):
        if files:  # files = [(name, bytes, mime), ...]
            r = S.post(url, data={"payload_json": json.dumps(body)},
                       files={f"files[{n}]": f for n, f in enumerate(files)}, timeout=60)
        else:
            r = S.post(url, json=body, timeout=TIMEOUT)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        r.raise_for_status()
        return
    raise RuntimeError("rate limited")


# ---- Blog photos attached to the blog notification --------------------------
BP = CFG.get("blog_photos", {})
MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}


def download(url, n):
    r = S.get(url, timeout=30, headers={"Referer": BASE + "/"})
    r.raise_for_status()
    ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
    ext = ext if ext in MIME else "jpg"
    return (f"{n:02d}.{ext}", r.content, MIME[ext])


def prepare_photos(i):
    """Download the post's photos (upload mode) and split them into Discord-sized groups of at most 10 files."""
    if BP.get("mode", "upload") != "upload" or not i.get("images"):
        return []
    limit = int(BP.get("max_mb_per_message", 9)) * 1024 * 1024
    groups, cur, size = [], [], 0
    for n, u in enumerate(i["images"][:int(BP.get("max", 10))], 1):
        try:
            f = download(u, n)
        except Exception as ex:
            print(f"[blog] photo {n} download failed: {ex}")
            continue
        if len(f[1]) > limit:
            continue
        if cur and (len(cur) >= 10 or size + len(f[1]) > limit):
            groups.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += len(f[1])
    if cur:
        groups.append(cur)
    return groups


def send_post(url, content, embed, groups):
    # Send the notification board (embed) first so attached photos appear underneath it
    send(url, content, embed)
    for g in groups:
        time.sleep(1)
        send(url, None, files=g)


FLAG = {"en": "🇬🇧 English · Title", "vi": "🇻🇳 Tiếng Việt · Tiêu đề"}


def build_embed(i, attach=False):
    label = LABEL[i["source"]] + (f" · {i['tag']}" if i.get("tag") else "")
    e = {
        "title": (i["title"] or "New post")[:256],
        "url": i["url"],
        "color": 0xF19DB5,
        "author": {"name": label[:256]},
    }
    if i.get("icon") and i["source"] != "blog":
        e["author"]["icon_url"] = i["icon"]

    fields = []

    if i["source"] == "blog":
        who = display_name(i["author"], romaji=i.get("romaji")) if i.get("author") else "Sakurazaka46 Member"
        raw_title = (i.get("title_raw") or "").strip()

        # Full-width author header with portrait icon so title & name don't wrap awkwardly on mobile
        e["author"] = {"name": f"🌸 {who} • Blog Update"[:256]}
        if i.get("icon"):
            e["author"]["icon_url"] = i["icon"]

        # Clickable blog title (with untitled fallback)
        e["title"] = f"「{raw_title}」"[:256] if raw_title else "「無題」 (Untitled Post)"

        # Spacious description: larger preview + separated date and last post lines
        desc_parts = []
        if i.get("preview"):
            desc_parts.append(f"### > {i['preview']}")

        if i.get("ts"):
            dt_str = dt.datetime.fromisoformat(i["ts"]).strftime("%Y/%m/%d %H:%M JST")
            desc_parts.append(f"🕒 **{dt_str}**")
        if i.get("prev"):
            prev_date, gap = i["prev"]
            desc_parts.append(f"↩️ Last post: **{prev_date}** ({gap})")

        if desc_parts:
            e["description"] = "\n\n".join(desc_parts)[:2000]

        # Compact translation fields with bold text for higher visual weight
        short_flag = {"en": "🇬🇧 EN", "vi": "🇻🇳 VI"}
        for lg, (t, pv) in i.get("tr", {}).items():
            if t:
                fields.append({"name": short_flag.get(lg, FLAG[lg]), "value": f"**{t}**"[:1024], "inline": True})

        # Fallback image inside embed only when not uploading attached files below
        if i.get("thumb") and not attach:
            e["image"] = {"url": i["thumb"]}

    else:
        if i.get("preview"):
            e["description"] = i["preview"][:1000]
        for lg, (t, pv) in i.get("tr", {}).items():
            val = "\n".join(x for x in (f"**{t}**" if t else None, pv) if x)
            fields.append({"name": FLAG[lg], "value": val[:1024], "inline": pv is None})
        if i["thumb"]:
            e["image" if i["source"] in BIG_IMAGE else "thumbnail"] = {"url": i["thumb"]}

    fields += [{"name": n[:256], "value": v[:1024], "inline": False} for n, v in i.get("fields", [])]

    size = len(e["title"]) + len(e.get("description", "")) + 100
    kept = []
    for f in fields[:25]:
        size += len(f["name"]) + len(f["value"])
        if size > 5500:
            break
        kept.append(f)
    if kept:
        e["fields"] = kept

    photo_count = len(i.get("images") or [])
    footer_bits = ["SakuBot"]
    if i["source"] == "blog" and photo_count:
        footer_bits.append(f"{photo_count} photo{'s' if photo_count != 1 else ''}")
    if i.get("tr"):
        footer_bits.append("auto-translated")

    e["footer"] = {"text": " · ".join(footer_bits)}
    e["timestamp"] = i.get("ts") or dt.datetime.now(dt.timezone.utc).isoformat()
    return e


PH = CFG.get("photos", {})


def send_photos(i):
    """Photo-only posts for a new blog entry. Embeds that share a URL show up as one gallery (up to 4 images)."""
    url = os.environ.get("WEBHOOK_PHOTOS")
    imgs = i.get("images") or []
    if not (PH.get("enabled") and url and imgs):
        return 0
    imgs = imgs[:int(PH.get("max_photos", 8))]
    per = max(1, min(4, int(PH.get("per_message", 4))))
    for n in range(0, len(imgs), per):
        embeds = []
        for k, src in enumerate(imgs[n:n + per]):
            e = {"url": i["url"], "color": 0xF19DB5, "image": {"url": src}}
            if n == 0 and k == 0:
                title_lbl = i.get("title_raw") or "無題 (Untitled)"
                e["title"] = f"📷 {title_lbl}"[:256]
                e["author"] = {"name": display_name(i["author"], romaji=i.get("romaji")) if i.get("author") else "Member blog"}
                if i.get("icon"):
                    e["author"]["icon_url"] = i["icon"]
                e["footer"] = {"text": f"SakuBot · {len(imgs)} photo(s)"}
                e["timestamp"] = i.get("ts") or dt.datetime.now(dt.timezone.utc).isoformat()
            embeds.append(e)
        send(url, None, embeds=embeds)
        time.sleep(1)
    return len(imgs)


def post_status(report, state):
    """One status message in its own channel, edited in place after every run (no spam)."""
    url = os.environ.get("WEBHOOK_STATUS")
    if not url:
        return
    fields, bad = [], False
    for src, r in report["src"].items():
        if r.get("ok"):
            val = f"{r['items']} items · {r['new']} new" + (f" · {r['posted']} sent" if r["new"] else "")
            if r.get("seeded"):
                val = f"seeded {r['items']} items"
        else:
            bad = True
            val = f"failed ×{r['fails']}: {r['err']}"
        fields.append({"name": ("✅ " if r.get("ok") else "⚠️ ") + src, "value": val[:200], "inline": True})
    if PH.get("enabled") and os.environ.get("WEBHOOK_PHOTOS"):
        fields.append({"name": "📷 Photos", "value": f"{report.get('photos', 0)} sent", "inline": True})
    if TR.get("enabled"):
        fields.append({"name": "🌐 Translation",
                       "value": f"{_tr['ok']} ok · {_tr['fail']} failed" if _tr["calls"] else "idle", "inline": True})
    embed = {"title": "SakuBot status", "color": 0xE67E22 if bad else 0x2ECC71, "fields": fields[:25],
             "description": f"Last run <t:{int(time.time())}:R> · took {time.time() - report['t0']:.0f}s",
             "timestamp": dt.datetime.now(dt.timezone.utc).isoformat()}
    mid = state.get("status_msg")
    if mid:
        r = S.patch(f"{url}/messages/{mid}", json={"embeds": [embed]}, timeout=TIMEOUT)
        if r.ok:
            return
    r = S.post(url + ("&" if "?" in url else "?") + "wait=true",
               json={"username": "SakuBot", "embeds": [embed]}, timeout=TIMEOUT)
    r.raise_for_status()
    state["status_msg"] = r.json()["id"]


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
    report = {"t0": time.time(), "src": {}}

    for src, enabled in CFG["sources"].items():
        if not enabled or not webhook_for(src):
            continue
        try:
            items = fetch(src, state)
        except Exception as ex:
            fails[src] = fails.get(src, 0) + 1
            report["src"][src] = {"ok": False, "err": str(ex)[:100], "fails": fails[src]}
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
            report["src"][src] = {"ok": True, "items": len(items), "new": 0, "posted": 0, "seeded": True}
            print(f"[{src}] seeded {len(items)} items")
            continue
        known_set = set(known)
        new = [i for i in items if i["id"] not in known_set]
        added = [i["id"] for i in new[limit:]]  # overflow is marked seen, not posted
        posted = 0
        for i in reversed(new[:limit]):
            if time.time() - report["t0"] > RUN_BUDGET:
                print(f"[{src}] time budget reached, remaining posts wait for the next run")
                break
            try:
                enrich(i, state)
                add_translations(i)
                groups = prepare_photos(i) if src == "blog" else []
                send_post(webhook_for(src), pings_for(i), build_embed(i, attach=bool(groups)), groups)
                added.append(i["id"])
                posted += 1
                time.sleep(1)
                if src == "blog":
                    try:
                        report["photos"] = report.get("photos", 0) + send_photos(i)
                    except Exception as ex:
                        print(f"[photos] failed: {ex}")
            except Exception as ex:
                print(f"[{src}] post failed, will retry next run: {ex}")
        seen[src] = (known + added)[-KEEP:]
        report["src"][src] = {"ok": True, "items": len(items), "new": len(new), "posted": posted}
        print(f"[{src}] {len(new)} new")

    maybe_digest(state)
    try:
        post_status(report, state)
    except Exception as ex:
        print(f"[status] failed: {ex}")
    state["heartbeat"] = now().strftime("%Y-%m")  # monthly commit keeps the repo active
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")


if __name__ == "__main__":
    main()
