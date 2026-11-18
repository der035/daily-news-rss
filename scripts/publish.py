#!/usr/bin/env python3
"""Source-grounded daily digest using RSS plus article body; fails closed."""
import datetime as dt
import email.utils
import html
import json
import os
import pathlib
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

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
BASE = "https://the-daily-noise.pages.dev/"
UA = "TheDailyNoise/1.0 (+https://github.com/der035/daily-news-rss)"
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=18) as response:
        return response.read(1500000)


def safe_image(url, page_url=""):
    url = html.unescape((url or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    if page_url:
        url = urllib.parse.urljoin(page_url, url)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname in ("localhost", "127.0.0.1"):
        return ""
    if parsed.path.lower().endswith((".svg", ".gif")):
        return ""
    return url

class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.ignore = 0
        self.current = []
        self.paragraphs = []
        self.image = ""
    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            attr = dict(attrs)
            if attr.get("property", "").lower() in ("og:image", "og:image:url") or attr.get("name", "").lower() in ("twitter:image", "twitter:image:src"):
                if not self.image:
                    self.image = attr.get("content", "")
        if tag in ("script", "style", "nav", "footer", "header", "aside"):
            self.ignore += 1
        if tag == "p" and not self.ignore:
            self.depth += 1
            self.current = []
    def handle_data(self, data):
        if self.depth and not self.ignore:
            self.current.append(data)
    def handle_endtag(self, tag):
        if tag == "p" and self.depth:
            value = " ".join("".join(self.current).split())
            if len(value) >= 75:
                self.paragraphs.append(value)
            self.depth = 0
            self.current = []
        if tag in ("script", "style", "nav", "footer", "header", "aside") and self.ignore:
            self.ignore -= 1

def enrich(items):
    """Fetch article pages for additional factual context; never claim full text if blocked."""
    for item in items[:30]:
        try:
            raw = fetch(item["url"])
            parser = ArticleText()
            parser.feed(raw.decode("utf-8", errors="replace"))
            body = "\\n".join(parser.paragraphs)
            item["article_excerpt"] = body[:5000] if len(body) >= 350 else ""
            item["image"] = safe_image(parser.image, item["url"]) or item.get("image", "")
        except Exception as error:
            print("Article body unavailable:", item["publisher"], type(error).__name__)
            item["article_excerpt"] = ""
    return items

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
                image_url = ""
                for name in ("{http://search.yahoo.com/mrss/}content", "{http://search.yahoo.com/mrss/}thumbnail", "enclosure"):
                    node = entry.find(name)
                    if node is not None:
                        candidate = node.attrib.get("url", "")
                        if name == "enclosure" and not node.attrib.get("type", "").startswith("image/"):
                            continue
                        image_url = safe_image(candidate, link)
                        if image_url:
                            break
                if not image_url:
                    match = re.search(r'<img[^>]+src=["\\\']([^"\\\']+)', field("description", "summary"), re.I)
                    if match:
                        image_url = safe_image(match.group(1), link)
                if title and link.startswith("https://"):
                    items.append(dict(category=category, publisher=publisher, title=title, url=link, image=image_url, description=description[:600], published=date.isoformat()))
        except Exception as error:
            print("Source unavailable:", publisher, type(error).__name__)
    return sorted(items, key=lambda item: item["published"], reverse=True)[:55]

def generate(items):
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is missing; keeping previous edition.")
    if len(items) < 8 or len({i["category"] for i in items}) < 3:
        raise RuntimeError("Insufficient recent sourced coverage; keeping previous edition.")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    numbered = [dict(item, source_id="S" + str(i + 1)) for i, item in enumerate(items)]
    lookup = {item["source_id"]: item for item in numbered}
    instructions = (
        "你是严谨的中文新闻编辑。素材包含RSS摘要及可能获取到的原文段落article_excerpt。"
        "选择5至8条不同且重要的新闻，国际政治、娱乐文化、消费科技三类都必须有。"
        "优先选择原文材料足够丰富的新闻。每条summary用100至170字解释发生了什么，"
        "context用100至200字解释有来源支撑的前情、事件机制、意义与影响。"
        "不要编造历史背景、引语或因果关系，不要使用‘素材仅’‘现有资料不足’等套话。"
        "材料不足的新闻请跳过。只返回JSON对象，格式为"
        "{\"articles\":[{\"source_id\":\"S1\",\"title\":\"中文标题\","
        "\"summary\":\"事实概述\",\"context\":\"具体背景解读\"}]}。"
        "source_id必须直接复制输入素材中的编号，不要输出URL或category，"
        "不要创造编号。标题不超过32字。"
    )
    def validate(articles):
        clean = []
        seen = set()
        for a in articles:
            if not isinstance(a, dict):
                continue
            source_id = str(a.get("source_id", "")).strip()
            source = lookup.get(source_id)
            if not source or source_id in seen:
                print("Skipped invalid or duplicate source_id:", source_id[:30])
                continue
            if not all(isinstance(a.get(k), str) and a[k].strip() for k in ("title", "summary", "context")):
                print("Skipped incomplete article:", source_id)
                continue
            context = a["context"].strip()
            if any(term in context for term in ("现有资料不足", "素材仅", "未说明", "无法判断更深层", "没有足够信息")) or len(context) < 55:
                print("Skipped low-information background:", source_id)
                continue
            seen.add(source_id)
            clean.append({
                "title": a["title"].strip(), "summary": a["summary"].strip(),
                "context": context, "category": source["category"],
                "source_url": source["url"], "publisher": source["publisher"],
                "published": source["published"], "image": source.get("image", ""),
            })
        return clean
    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": json.dumps(numbered, ensure_ascii=False)}
    ]
    best = []
    for attempt in range(2):
        payload = {
            "model": model, "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=100) as response:
            result = json.load(response)
        raw = result["choices"][0]["message"]["content"]
        data = json.loads(raw)
        clean = validate(data.get("articles", []))
        if len({a["category"] for a in clean}) > len({a["category"] for a in best}) or (len({a["category"] for a in clean}) == len({a["category"] for a in best}) and len(clean) > len(best)):
            best = clean
        print("Coverage:", {category: sum(a["category"] == category for a in clean) for category in ("国际政治", "娱乐文化", "消费科技")})
        if 5 <= len(clean) <= 8 and len({a["category"] for a in clean}) == 3:
            return clean
        print("Attempt", attempt + 1, "failed coverage validation; valid:", len(clean))
        messages.extend([
            {"role": "assistant", "content": raw},
            {"role": "user", "content": (
                "上一版未满足校验。请重新输出5至8条且三大类别均有的文章，"
                "每条仅使用输入中的source_id；不要重复编号。"
                "确保context具体、信息充分，不要编造事实或使用空洞套话。"
            )},
        ])
    # Repair category coverage without discarding already verified articles.
    # Only ask for one article from a missing category, using that category's original sources.
    required = ("国际政治", "娱乐文化", "消费科技")
    for category in required:
        if any(a["category"] == category for a in best):
            continue
        used_urls = {a["source_url"] for a in best}
        candidates = [
            item for item in numbered
            if item["category"] == category and item["url"] not in used_urls
        ][:12]
        if not candidates:
            print("No available sources for missing category:", category)
            continue
        print("Repairing missing category:", category, "with", len(candidates), "sources")
        repair_messages = [
            {"role": "system", "content": instructions + "本次只写一篇指定栏目的新闻，必须使用提供的source_id，并返回JSON对象articles数组。"},
            {"role": "user", "content": "请只从以下" + category + "素材中选择一条信息充分的新闻，生成一篇完整的中文新闻，不要引用其他类别：\\n" + json.dumps(candidates, ensure_ascii=False)},
        ]
        payload = {
            "model": model, "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": repair_messages,
        }
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=100) as response:
            result = json.load(response)
        additions = validate(json.loads(result["choices"][0]["message"]["content"]).get("articles", []))
        additions = [a for a in additions if a["category"] == category and a["source_url"] not in used_urls]
        if additions:
            if len(best) >= 8:
                counts = {c: sum(a["category"] == c for a in best) for c in required}
                removable = next((i for i in range(len(best) - 1, -1, -1) if counts[best[i]["category"]] > 1), None)
                if removable is not None:
                    best.pop(removable)
            if len(best) < 8:
                best.append(additions[0])
    if 5 <= len(best) <= 8 and len({a["category"] for a in best}) == 3:
        print("Coverage repaired:", {c: sum(a["category"] == c for a in best) for c in required})
        return best
    raise ValueError("Cannot publish: category coverage remains incomplete after targeted repair.")

def render(articles):
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    date = now.strftime("%Y.%m.%d")
    esc = lambda x: html.escape(str(x), quote=True)
    # Curated glossary: only annotate terms with reviewed, reusable definitions.
    glossary = {
        "反垄断": "防止企业通过垄断或限制竞争损害市场竞争的法律与监管措施。",
        "关税": "一国对进口或出口商品征收的税；可能影响商品价格和贸易流向。",
        "通货膨胀": "商品和服务的总体价格水平持续上涨，货币购买力相应下降。",
        "降息": "中央银行降低政策利率，通常会影响借贷成本和金融市场。",
        "加息": "中央银行提高政策利率，通常会提高借贷成本并影响需求。",
        "制裁": "政府或国际组织采取的限制性措施，可能涉及贸易、金融或个人往来。",
        "不信任动议": "议会对政府或官员是否仍获得信任进行表决的程序，具体后果依各国制度而异。",
        "弹劾": "依照法律或宪法程序追究公职人员责任的机制，不等于自动定罪或免职。",
        "议会": "由民意代表组成、通常负责立法和监督政府的机构，权限因国家而异。",
        "众议院": "实行两院制的部分国家中，通常按人口或选区选出的议会一院。",
        "参议院": "实行两院制的部分国家中，另一议会院，其组成与权限因国家而异。",
        "人工智能": "让计算机系统执行通常需要人类智能的任务，例如语言处理、识别与推理。",
        "大语言模型": "通过大量文本等数据训练、能够生成和处理自然语言的人工智能模型。",
        "生成式AI": "能够根据输入生成文本、图像、音频或其他内容的人工智能技术。",
        "芯片制程": "制造半导体芯片时使用的工艺技术体系；名称中的纳米数不直接等于晶体管实际尺寸。",
        "开源": "在相应许可条款下公开源代码，允许他人查看、使用或修改；具体权利取决于许可证。",
        "零日漏洞": "软件漏洞被公开或利用时，开发者尚未有充分时间提供修复措施的安全问题。",
        "供应链": "从原材料、生产、运输到交付产品所涉及的企业和流程网络。",
        "票房": "电影等演出作品售票产生的收入，通常不等于制作方最终利润。",
        "流媒体": "通过网络连续传输并播放视频或音频内容的服务与技术。",
        "版权": "创作者对作品享有的法定权利，包括复制、传播等，具体范围由法律规定。",
    }
    terms = sorted(glossary, key=len, reverse=True)
    term_pattern = re.compile("|".join(re.escape(t) for t in terms))
    number_pattern = re.compile(r"\d+(?:[.,]\d+)?(?:%|％|年|月|日|人|亿|万|席|票|美元|元)?")
    # Conservative semantic cues: emphasize a short outcome, never infer causality.
    outcome_pattern = re.compile(
        r"(?:宣布|确认|通过|否决|批准|达成|签署|赢得|击败|当选|辞职|下台|"
        r"发布|推出|上线|收购|裁员|停产|召回|起诉|判处|禁止|取消|"
        r"上涨|下跌|增长|下降|突破|创下|获得|遭到|导致|引发|"
        r"将于|计划|预计|可能)[^，。；！？：]{2,22}"
    )
    def focus_text(value):
        """Only style spans already present in sourced editorial copy; never invent claims."""
        value = str(value)
        spans = []
        occupied = [False] * len(value)
        def mark(start, end, kind):
            if start >= end or any(occupied[start:end]):
                return
            spans.append((start, end, kind))
            for j in range(start, end):
                occupied[j] = True

        # Definitions take precedence; no automatic AI-generated definitions.
        for match in term_pattern.finditer(value):
            mark(match.start(), match.end(), "term")
        # Facts and outcomes should be noticeable without painting entire paragraphs.
        for match in number_pattern.finditer(value):
            mark(match.start(), match.end(), "fact")
        for match in outcome_pattern.finditer(value):
            if len(match.group()) <= 24:
                mark(match.start(), match.end(), "outcome")
        # Lead emphasis is limited to the opening subject phrase, not the whole sentence.
        opening = re.match(r"[^，。；！？：]{4,36}", value)
        if opening:
            lead = opening.group()
            boundary = re.search(r"(?:宣布|确认|通过|否决|批准|赢得|击败|当选|"
                                 r"发布|推出|收购|裁员|上涨|下跌|增长|下降|导致|引发|"
                                 r"将于|计划|预计|可能)", lead)
            lead_end = boundary.start() if boundary else min(len(lead), 12)
            if 4 <= lead_end <= 16:
                mark(0, lead_end, "lead")

        result = []
        cursor = 0
        for first, last, kind in sorted(spans):
            result.append(esc(value[cursor:first]))
            fragment = esc(value[first:last])
            if kind == "term":
                result.append('<button type="button" class="term" data-definition="' +
                              esc(glossary[value[first:last]]) + '" aria-label="解释术语：' +
                              fragment + '">' + fragment + '</button>')
            else:
                result.append('<strong class="focus-' + kind + '">' + fragment + '</strong>')
            cursor = last
        result.append(esc(value[cursor:]))
        return ''.join(result)
    cards = {category: [] for category in ("国际政治", "娱乐文化", "消费科技")}
    for i, a in enumerate(articles, 1):
        headline = a["title"]
        summary = a["summary"].strip()
        context = a["context"].strip()
        takeaway = re.split(r"(?<=[。！？])", summary, maxsplit=1)[0].strip()
        if len(takeaway) > 90:
            takeaway = takeaway[:87] + "…"
        minutes = max(1, round((len(summary) + len(context)) / 350))
        image = a.get("image", "")
        photo = ('<figure><img src="' + esc(image) + '" alt="' + esc(headline) + '" loading="lazy"><figcaption>图片来源：' + esc(a["publisher"]) + '</figcaption></figure>') if image else ""
        cards[a["category"]].append(
            '<article class="story" id="story-' + str(i) + '" data-story="' + esc(a["source_url"]) + '">'
            '<div class="story-meta"><span class="kicker">' + str(i).zfill(2) + ' / ' + esc(a["category"]) + '</span>'
            '<span class="reading-time">约 ' + str(minutes) + ' 分钟</span></div>'
            '<h2>' + esc(headline) + '</h2>' + photo +
            '<div class="takeaway"><span class="micro">⚡ 10 秒看懂</span><p>' + focus_text(takeaway) + '</p></div>'
            '<div class="standard-block"><h3>📌 发生了什么？</h3><p>' + focus_text(summary) + '</p></div>'
            '<div class="deep-block"><h3>🧩 为什么会这样？</h3><p>' + focus_text(context) + '</p>'
            '<p class="source-note">背景解读依据已获取的新闻材料整理，不代表对未来结果的确定预测。</p></div>'
            '<div class="story-bottom"><a href="' + esc(a["source_url"]) + '" target="_blank" rel="noopener noreferrer">核对原始报道：' + esc(a["publisher"]) + ' ↗</a>'
            '<button type="button" class="save" aria-pressed="false" aria-label="收藏这条新闻">☆ 收藏</button></div></article>'
        )
    category_names = ("国际政治", "娱乐文化", "消费科技")
    sections = ''.join(
        '<section class="category-panel" id="panel-' + str(j) + '" aria-labelledby="tab-' + str(j) + '" role="tabpanel">'
        '<div class="section-heading"><span class="section-index">0' + str(j + 1) + ' / SECTION</span>'
        '<h2>' + esc(category) + '</h2><span>' + str(len(cards[category])) + ' STORIES</span></div>'
        + ''.join(cards[category]) + '</section>'
        for j, category in enumerate(category_names)
    )
    style = """*{box-sizing:border-box}html{scroll-behavior:smooth;background:#0639f5}body{margin:0;background:#0639f5;color:#111;font-family:Arial,'PingFang SC','Microsoft YaHei',sans-serif}.paper{max-width:980px;margin:20px auto 60px;background:#f5f3ed;padding:clamp(24px,6vw,70px)}header{border-bottom:4px solid #111;padding-bottom:18px;display:flex;justify-content:space-between;gap:12px;font-size:12px;font-weight:900}header a,.story a{color:#0639f5}.hero h1{font-family:Impact,'Arial Black',sans-serif;font-size:clamp(64px,12vw,148px);line-height:.82;letter-spacing:-.05em;margin:80px 0 28px}.hero h1 em{font-family:Georgia,serif;font-weight:400}.sticker{background:#ff9cce;display:inline-block;padding:12px;transform:rotate(-7deg);border:2px solid}.lede{font-size:21px;font-weight:700;padding-bottom:25px}.reader-tools{position:relative;top:auto;z-index:10;background:#f5f3ed;border-top:3px solid;border-bottom:3px solid;padding:14px 0;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.reader-tools label{font-size:12px;font-weight:900}.modes{display:flex;gap:5px;flex-wrap:wrap}.modes button,.save{border:2px solid #111;background:transparent;color:#111;padding:9px 12px;font-weight:800;cursor:pointer}.modes button[aria-pressed=true]{background:#111;color:#fff}.progress{height:4px;position:fixed;top:env(safe-area-inset-top,0px);left:0;right:0;background:#ddd;z-index:11}.progress span{display:block;height:100%;width:0;background:#ff7e45}.story{border-bottom:3px solid;padding:42px 0;scroll-margin-top:100px}.story-meta,.story-bottom{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.kicker{font-size:12px;font-weight:900;background:#ff7e45;padding:7px}.reading-time,.micro,.source-note{font-size:12px;color:#555}.story h2{font-size:clamp(29px,5vw,52px);line-height:1.15;letter-spacing:-.03em}.story h3{font-size:20px;margin:25px 0 8px}.story p{font-size:17px;line-height:1.8}.story figure{margin:20px 0}.story figure img{display:block;width:100%;max-height:490px;object-fit:cover;background:#ddd}.story figcaption{font-size:12px;color:#555;margin-top:8px}.takeaway{background:#ffdfeb;border-left:6px solid #111;padding:18px 20px}.takeaway .micro{font-weight:900;color:#111}.takeaway p{font-weight:800;font-size:20px;line-height:1.5;margin:10px 0 0}.deep-block{background:#e9e9e4;padding:2px 20px 15px;margin:18px 0}.story-bottom{margin-top:22px}.story-bottom a{font-weight:800}.save[aria-pressed=true]{background:#ff9cce}.mode-quick .standard-block,.mode-quick .deep-block,.mode-standard .deep-block{display:none}.reading-guide{font-size:13px;line-height:1.6;color:#555}footer{padding:30px 0;font-size:13px}button:focus-visible,a:focus-visible{outline:4px solid #0639f5;outline-offset:3px}@media(max-width:600px){.paper{margin:8px;padding:22px}.hero h1{margin-top:65px}.reader-tools{top:auto}.story{padding:30px 0}.story h2{font-size:32px}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}"""
    style += """.category-nav{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;margin:20px 0 12px;padding:4px 0 10px}.category-nav::-webkit-scrollbar{display:none}.category-nav button{flex:1 0 auto;min-height:48px;border:2px solid #111;background:#f5f3ed;color:#111;font-size:15px;font-weight:850;padding:10px 14px;cursor:pointer}.category-nav button[aria-selected=true]{background:#0639f5;color:#fff}.category-rail{display:flex;align-items:flex-start;overflow-x:auto;overscroll-behavior-x:contain;scroll-snap-type:x mandatory;scrollbar-width:none;gap:0;touch-action:pan-x pan-y}.category-rail::-webkit-scrollbar{display:none}.category-panel{flex:0 0 100%;width:100%;min-width:0;scroll-snap-align:start;scroll-snap-stop:normal}.section-heading{border-bottom:4px solid #111;padding:20px 0 16px;display:flex;flex-wrap:wrap;align-items:baseline;gap:12px}.section-heading h2{font-family:Georgia,'Songti SC','Noto Serif CJK SC',serif;font-size:clamp(30px,5vw,44px);margin:0;font-weight:800}.section-index,.section-heading>span:last-child{font-size:11px;font-weight:900;letter-spacing:.07em}.story h2{font-family:'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif;font-weight:800;line-height:1.27;letter-spacing:-.015em}.story p{font-family:'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif;font-size:18px;line-height:1.85;font-weight:400;letter-spacing:.012em;overflow-wrap:anywhere}.story .takeaway p{font-size:clamp(19px,3.6vw,23px);line-height:1.62;font-weight:750}.story h3{font-family:'PingFang SC','Noto Sans CJK SC',sans-serif;font-weight:800;font-size:21px}.reading-guide{font-size:14px}.story .source-note{font-size:12px}.category-hint{font-size:12px;font-weight:700;color:#555}@media(max-width:600px){.category-nav button{font-size:14px;padding:10px 12px}.story p{font-size:17px;line-height:1.85}.story h2{font-size:30px;line-height:1.3}}@media(prefers-reduced-motion:reduce){.category-rail{scroll-behavior:auto}}"""
    style += """:root{color-scheme:light;--paper:#f5f3ed;--ink:#111;--muted:#555;--blue:#0639f5;--pink:#ffdfeb;--soft:#e9e9e4;--accent:#ff7e45}body{color:var(--ink)}.paper,.reader-tools{background:var(--paper)}.story a,header a{color:var(--blue)}.reading-time,.micro,.source-note,.category-hint,.reading-guide{color:var(--muted)}.takeaway{background:var(--pink);border-left-color:var(--ink)}.deep-block{background:var(--soft)}.kicker{background:var(--accent);color:#111}.category-nav button{background:var(--paper);color:var(--ink);border-color:var(--ink)}.category-nav button[aria-selected=true]{background:var(--blue);color:#fff}.modes button,.save{color:var(--ink);border-color:var(--ink)}.modes button[aria-pressed=true]{background:var(--ink);color:var(--paper)}.story,.section-heading,header,.reader-tools{border-color:var(--ink)}.focus-lead{font-weight:800;color:var(--ink)}.focus-fact{font-weight:800;color:var(--blue);font-size:1.045em}.takeaway .focus-fact{color:#0639f5}.story p{font-weight:400}.story p strong{letter-spacing:0}.theme-toggle{border:2px solid var(--ink);background:var(--paper);color:var(--ink);font-weight:800;min-height:42px;padding:8px 12px;cursor:pointer}.reading-header{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:space-between}.reading-progress{height:5px;background:var(--soft);margin:12px 0 0;overflow:hidden}.reading-progress span{display:block;height:100%;width:0;background:var(--accent);transition:width .1s linear}.progress{display:none!important}.category-rail{transition:height .18s ease;overflow-y:hidden}.category-panel{align-self:flex-start}.theme-dark{--paper:#171b25;--ink:#f4f1e8;--muted:#b9c1d0;--blue:#9fb4ff;--pink:#392b43;--soft:#252c39;--accent:#ff9c79;background:#0b1020;color-scheme:dark}.theme-dark .paper,.theme-dark .reader-tools{background:var(--paper)}.theme-dark .takeaway .micro{color:var(--ink)}.theme-dark .takeaway .focus-fact{color:#c6d0ff}.theme-dark .category-nav button[aria-selected=true]{background:#9fb4ff;color:#10131d}.theme-dark .modes button[aria-pressed=true]{background:#f4f1e8;color:#171b25}.theme-dark .save[aria-pressed=true]{background:#59405b}.theme-dark .story figure img{background:#343c4a}.theme-dark .sticker{color:#111}.theme-dark .kicker{color:#111}@media(prefers-reduced-motion:reduce){.category-rail{transition:none}.reading-progress span{transition:none}}"""
    style += """.term{display:inline;color:inherit;background:transparent;border:0;border-bottom:2px dotted var(--blue);padding:0 1px;font:inherit;font-weight:750;cursor:pointer;text-decoration:none;vertical-align:baseline}.term:focus-visible{outline:3px solid var(--blue);outline-offset:2px}.term-dialog{border:0;border-radius:22px;padding:0;max-width:min(90vw,520px);width:100%;box-shadow:0 24px 70px #0005;background:var(--paper);color:var(--ink)}.term-dialog::backdrop{background:#0009}.term-dialog-inner{padding:26px 26px 30px}.term-dialog-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.term-dialog h2{font-size:24px;margin:0;font-weight:850}.term-dialog p{font-size:17px;line-height:1.75;margin:18px 0 0}.term-close{border:2px solid var(--ink);background:transparent;color:var(--ink);font-size:24px;width:44px;height:44px;cursor:pointer}.term-dialog .term-hint{font-size:12px;color:var(--muted);margin-top:18px}.focus-lead{font-weight:800}.focus-fact{font-weight:850}.focus-outcome{font-weight:800;color:var(--blue)}.takeaway .focus-outcome{color:#0639f5}.theme-dark .takeaway .focus-outcome{color:#c6d0ff}@media(prefers-reduced-motion:reduce){.term-dialog{scroll-behavior:auto}}"""
    script = """(function(){
const root=document.body,buttons=[...document.querySelectorAll('[data-mode]')];
const glossaryDialog=document.querySelector('#term-dialog');
let lastTerm=null;
document.addEventListener('click',e=>{const term=e.target.closest('.term');if(!term)return;lastTerm=term;document.querySelector('#term-title').textContent=term.textContent;document.querySelector('#term-definition').textContent=term.dataset.definition;glossaryDialog.showModal()});
document.querySelector('.term-close').addEventListener('click',()=>glossaryDialog.close());
glossaryDialog.addEventListener('click',e=>{if(e.target===glossaryDialog)glossaryDialog.close()});
glossaryDialog.addEventListener('close',()=>lastTerm?.focus());

const themeButton=document.querySelector('.theme-toggle');
let savedTheme='auto';try{savedTheme=localStorage.getItem('tdn-theme')||'auto'}catch(e){}
const darkPreference=matchMedia('(prefers-color-scheme: dark)');
function applyTheme(){const dark=savedTheme==='dark'||(savedTheme==='auto'&&darkPreference.matches);root.classList.toggle('theme-dark',dark);themeButton.textContent=dark?'☀️ 日间':'🌙 午夜';themeButton.setAttribute('aria-label',dark?'切换到日间模式':'切换到午夜模式');document.querySelector('meta[name="theme-color"]').content=dark?'#0b1020':'#0639f5'}
themeButton.addEventListener('click',()=>{savedTheme=root.classList.contains('theme-dark')?'light':'dark';try{localStorage.setItem('tdn-theme',savedTheme)}catch(e){}applyTheme()});
darkPreference.addEventListener?.('change',()=>{if(savedTheme==='auto')applyTheme()});applyTheme();
function mode(m){if(!['quick','standard','deep'].includes(m))m='standard';root.classList.remove('mode-quick','mode-standard','mode-deep');root.classList.add('mode-'+m);buttons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===m)));try{localStorage.setItem('tdn-mode',m)}catch(e){}}
let stored='standard';try{stored=localStorage.getItem('tdn-mode')||'standard'}catch(e){}mode(stored);
buttons.forEach(b=>b.addEventListener('click',()=>mode(b.dataset.mode)));
document.querySelectorAll('.save').forEach(b=>{const id=b.closest('.story').dataset.story;let saved=false;try{saved=localStorage.getItem('tdn-save:'+id)==='1'}catch(e){}function show(){b.setAttribute('aria-pressed',String(saved));b.textContent=saved?'★ 已收藏':'☆ 收藏'}show();b.addEventListener('click',()=>{saved=!saved;try{localStorage.setItem('tdn-save:'+id,saved?'1':'0')}catch(e){}show()})});
function progress(){const max=document.documentElement.scrollHeight-innerHeight;const pct=max>0?Math.min(100,scrollY/max*100):100;document.querySelector('.reading-progress span').style.width=pct+'%';document.querySelector('.reading-progress').setAttribute('aria-valuenow',String(Math.round(pct)))}
const rail=document.querySelector('.category-rail'),tabs=[...document.querySelectorAll('.category-nav button')];
const panels=[...rail.querySelectorAll('.category-panel')];let currentPanel=0;
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
function panelLeft(i){return panels[i].offsetLeft-panels[0].offsetLeft}
function nearestPanel(){let best=0,dist=Infinity;panels.forEach((p,i)=>{const d=Math.abs(panelLeft(i)-rail.scrollLeft);if(d<dist){best=i;dist=d}});return best}
function syncHeight(){const panel=panels[currentPanel];if(panel)rail.style.height=panel.scrollHeight+'px'}
function selectTab(i){currentPanel=i;tabs.forEach((b,j)=>{b.setAttribute('aria-selected',String(i===j));b.tabIndex=i===j?0:-1});syncHeight()}
function goToPanel(i,smooth){i=Math.max(0,Math.min(panels.length-1,i));selectTab(i);rail.scrollTo({left:panelLeft(i),behavior:smooth&&!reducedMotion.matches?'smooth':'instant'})}
tabs.forEach((b,i)=>{b.addEventListener('click',()=>goToPanel(i,true));b.addEventListener('keydown',e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const j=(i+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length;tabs[j].focus();goToPanel(j,true)}})});
let settleTimer;
function settle(){clearTimeout(settleTimer);const i=nearestPanel();goToPanel(i,false)}
rail.addEventListener('scroll',()=>{clearTimeout(settleTimer);settleTimer=setTimeout(settle,160)},{passive:true});
rail.addEventListener('touchend',()=>{clearTimeout(settleTimer);settleTimer=setTimeout(settle,240)},{passive:true});
rail.addEventListener('scrollend',settle,{passive:true});
const resizeObserver=new ResizeObserver(()=>syncHeight());panels.forEach(p=>resizeObserver.observe(p));
window.addEventListener('load',()=>{goToPanel(currentPanel,false)});
syncHeight();
addEventListener('scroll',progress,{passive:true});addEventListener('resize',()=>{syncHeight();progress()});progress();
})();"""
    page = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="theme-color" content="#0639f5"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="DAILY NOISE"><link rel="icon" type="image/svg+xml" href="icon.svg"><link rel="apple-touch-icon" href="apple-touch-icon.png"><title>THE DAILY NOISE — ' + date + '</title>'
            '<link rel="alternate" type="application/rss+xml" href="feed.xml"><style>' + style + '</style></head>'
            '<body class="mode-standard"><main class="paper">'
            '<header><span>THE DAILY NOISE / ' + date + '</span><a href="feed.xml">RSS ↗</a></header>'
            '<section class="hero"><h1>THE DAILY<br><em>NOISE.</em></h1><span class="sticker">WORLD NEWS!</span>'
            '<p class="lede">世界每天都很吵。10 秒抓重点，3 分钟看懂来龙去脉。</p></section>'
            '<div class="reader-tools"><div class="reading-header"><label>选择阅读密度</label><button class="theme-toggle" type="button" aria-label="切换到午夜模式">🌙 午夜</button></div><div class="modes" role="group" aria-label="阅读模式">'
            '<button type="button" data-mode="quick" aria-pressed="false">⚡ 速览</button>'
            '<button type="button" data-mode="standard" aria-pressed="true">📖 标准</button>'
            '<button type="button" data-mode="deep" aria-pressed="false">🧠 深度</button></div></div><div class="reading-progress" role="progressbar" aria-label="页面阅读进度" aria-valuemin="0" aria-valuemax="100"><span></span></div>'
            '<p class="reading-guide">可以只看粉色重点卡片；想知道原因，切换到「深度」。收藏会保存在当前浏览器。</p>'
            '<nav class="category-nav" role="tablist" aria-label="新闻栏目">'
            '<button id="tab-0" role="tab" aria-controls="panel-0" aria-selected="true" type="button">🌍 国际政治</button>'
            '<button id="tab-1" role="tab" aria-controls="panel-1" aria-selected="false" type="button" tabindex="-1">🎭 娱乐文化</button>'
            '<button id="tab-2" role="tab" aria-controls="panel-2" aria-selected="false" type="button" tabindex="-1">💻 消费科技</button></nav>'
            '<p class="category-hint">← 左右滑动切换栏目，向下阅读当前栏目 ↓</p>'
            '<div class="category-rail">' + sections + '</div>' +
            '<footer>THE DAILY NOISE · 新闻事实请以原始报道为准 · 每日北京时间 08:00 更新（成功生成时）</footer>'
            '</main><dialog id="term-dialog" class="term-dialog" aria-labelledby="term-title"><div class="term-dialog-inner"><div class="term-dialog-head"><h2 id="term-title"></h2><button class="term-close" type="button" aria-label="关闭解释">×</button></div><p id="term-definition"></p><p class="term-hint">术语速解 · 点击外部或按 Esc 关闭</p></div></dialog><script>' + script + '</script></body></html>')
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    for tag, value in (("title", "THE DAILY NOISE · 世界每天都很吵"), ("link", BASE), ("description", "国际政治、娱乐文化与消费科技中文新闻简报"), ("language", "zh-CN"), ("lastBuildDate", email.utils.format_datetime(now))):
        ET.SubElement(channel, tag).text = value
    for a in articles:
        item = ET.SubElement(channel, "item")
        if a.get("image"):
            ET.SubElement(item, "{http://search.yahoo.com/mrss/}content", {"url": a["image"], "medium": "image"})
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
    articles = generate(enrich(items))
    render(articles)
    print("Published articles:", len(articles))

if __name__ == "__main__":
    main()
