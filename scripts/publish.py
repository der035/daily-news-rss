#!/usr/bin/env python3
"""Source-grounded daily digest. Requires OPENAI_API_KEY; fails closed."""
import datetime as dt
import email.utils
import html
import json
import os
import pathlib
import re
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SOURCES = [
    ("国际政治", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("国际政治", "The Guardian World", "https://www.theguardian.com/world/rss"),
    ("娱乐文化", "The Guardian Culture", "https://www.theguardian.com/culture/rss"),
    ("娱乐文化", "Variety", "https://variety.com/feed/"),
    ("消费科技", "The Guardian Technology", "https://www.theguardian.com/uk/technology/rss"),
    ("消费科技", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
]
BASE = "https://der035.github.io/daily-news-rss/"
UA = "TheDailyNoise/1.0 (+https://github.com/der035/daily-news-rss)"
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=18) as response:
        return response.read(1500000)

def collect():
    items = []
    now = dt.datetime.now(dt.timezone.utc)
    for category, publisher, url in SOURCES:
        try:
            root = ET.fromstring(fetch(url))
            entries = root.findall(".//item")
            if not entries:
                entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for entry in entries[:15]:
                def field(*names):
                    for name in names:
                        element = entry.find(name)
                        if element is not None:
                            if element.text:
                                return element.text.strip()
                            if element.attrib.get("href"):
                                return element.attrib["href"]
                    return ""
                title = html.unescape(re.sub("<[^>]+>", "", field("title", "{http://www.w3.org/2005/Atom}title")))
                link = field("link", "{http://www.w3.org/2005/Atom}link")
                description = html.unescape(re.sub("<[^>]+>", "", field("description", "summary", "{http://www.w3.org/2005/Atom}summary")))
                date_text = field("pubDate", "{http://www.w3.org/2005/Atom}updated")
                try:
                    date = email.utils.parsedate_to_datetime(date_text)
                    if date.tzinfo is None: date = date.replace(tzinfo=dt.timezone.utc)
                    if now - date > dt.timedelta(hours=48): continue
                except Exception:
                    continue
                if title and link.startswith("https://"):
                    items.append(dict(category=category, publisher=publisher, title=title, url=link, description=description[:600], published=date.isoformat()))
        except Exception as error:
            print("Source unavailable:", publisher, type(error).__name__)
    return sorted(items, key=lambda item: item["published"], reverse=True)[:55]

def generate(items):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing; keeping previous edition.")
    if len(items) < 8 or len({i["category"] for i in items}) < 3:
        raise RuntimeError("Insufficient recent sourced coverage; keeping previous edition.")
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    instructions = (
        "你是严谨的中文新闻编辑。只能使用提供的新闻标题、摘要、日期与URL，不得假装已阅读原文。"
        "选择5至8条重要且不同的新闻，三大类别各至少一条。不要编造事实、引语、背景或影响。"
        "每条中文标题不超过32字，摘要100至170字，背景解读70至130字。"
        "背景若无法由素材证实，明确写‘现有资料不足以判断更深层原因’。"
        "输出一个JSON对象，只有 articles 数组。每条必须有 category,title,summary,context,source_url。"
        "source_url 必须与输入URL完全相同。不要添加未经提供的新闻。"
    )
    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(items, ensure_ascii=False)}
        ]
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=100) as response:
        result = json.load(response)
    articles = json.loads(result["choices"][0]["message"]["content"])["articles"]
    lookup = {item["url"]: item for item in items}
    clean = []
    for a in articles:
        source = lookup.get(a.get("source_url"))
        if not source or a.get("category") != source["category"]:
            raise ValueError("Generated article has an invalid source/category.")
        if not all(isinstance(a.get(k), str) and a[k].strip() for k in ("title", "summary", "context")):
            raise ValueError("Incomplete generated article.")
        clean.append({**a, "publisher": source["publisher"], "published": source["published"]})
    if not 5 <= len(clean) <= 8 or len({a["category"] for a in clean}) < 3:
        raise ValueError("Coverage validation failed.")
    if len({a["source_url"] for a in clean}) != len(clean):
        raise ValueError("Duplicate source URLs.")
    return clean

def render(articles):
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    date = now.strftime("%Y.%m.%d")
    esc = lambda x: html.escape(str(x), quote=True)
    cards = []
    for i, a in enumerate(articles, 1):
        cards.append(
            '<article class="story"><span class="kicker">' + str(i).zfill(2) + ' / ' + esc(a["category"]) + '</span>'
            + '<h2>' + esc(a["title"]) + '</h2><p>' + esc(a["summary"]) + '</p>'
            + '<p class="context"><strong>来龙去脉 / </strong>' + esc(a["context"]) + '</p>'
            + '<a href="' + esc(a["source_url"]) + '" target="_blank" rel="noopener noreferrer">来源：' + esc(a["publisher"]) + ' ↗</a></article>'
        )
    style = """body{margin:0;background:#0639f5;color:#111;font-family:Arial,'PingFang SC',sans-serif}.paper{max-width:980px;margin:20px auto 60px;background:#f5f3ed;padding:clamp(24px,6vw,70px)}header{border-bottom:4px solid #111;padding-bottom:18px;display:flex;justify-content:space-between;font-size:12px;font-weight:900}h1{font-family:Impact,'Arial Black',sans-serif;font-size:clamp(64px,12vw,148px);line-height:.82;letter-spacing:-.05em;margin:90px 0 28px}h1 em{font-family:Georgia,serif;font-weight:400}.sticker{background:#ff9cce;display:inline-block;padding:12px;transform:rotate(-7deg);border:2px solid} .lede{font-size:21px;font-weight:700;border-bottom:4px solid;padding-bottom:55px}.story{border-bottom:2px solid;padding:38px 0}.kicker{font-size:12px;font-weight:900;background:#ff7e45;padding:7px}.story h2{font-size:clamp(29px,5vw,52px);line-height:1.15}.story p{font-size:17px;line-height:1.85}.context{background:#e8e8e4;padding:18px}.story a{color:#0639f5;font-weight:700}footer{padding:30px 0;font-size:13px}@media(max-width:600px){.paper{margin:8px;padding:22px}h1{margin-top:65px}}"""
    page = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>THE DAILY NOISE — '+date+'</title><link rel="alternate" type="application/rss+xml" href="feed.xml"><style>'+style+'</style></head><body><main class="paper"><header><span>THE DAILY NOISE / '+date+'</span><a href="feed.xml">RSS ↗</a></header><h1>THE DAILY<br><em>NOISE.</em></h1><span class="sticker">WORLD NEWS!</span><p class="lede">世界每天都很吵。今天这些事，值得了解。</p>'+''.join(cards)+'<footer>THE DAILY NOISE · 来源链接见各篇文章 · 每日北京时间 08:00 更新（成功生成时）</footer></main></body></html>'
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    for tag, value in (("title", "THE DAILY NOISE · 世界每天都很吵"), ("link", BASE), ("description", "国际政治、娱乐文化与消费科技中文新闻简报"), ("language", "zh-CN"), ("lastBuildDate", email.utils.format_datetime(now))):
        ET.SubElement(channel, tag).text = value
    for a in articles:
        item = ET.SubElement(channel, "item")
        for tag, value in (("title", a["title"]), ("link", a["source_url"]), ("guid", a["source_url"]), ("pubDate", email.utils.format_datetime(dt.datetime.fromisoformat(a["published"]))), ("description", a["summary"] + "\n\n来龙去脉：" + a["context"] + "\n来源：" + a["publisher"])):
            node = ET.SubElement(item, tag)
            node.text = value
            if tag == "guid": node.set("isPermaLink", "false")
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    ET.ElementTree(rss).write(DOCS / "feed.xml", encoding="utf-8", xml_declaration=True)

def main():
    items = collect()
    print("Recent sourced items:", len(items))
    articles = generate(items)
    render(articles)
    print("Published articles:", len(articles))

if __name__ == "__main__":
    main()
