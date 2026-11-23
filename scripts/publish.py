#!/usr/bin/env python3
"""Source-grounded daily digest using RSS plus article body; fails closed."""
import datetime as dt
import email.utils
import html
import json
import os
import pathlib
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CATEGORIES = ("国内新闻", "国际政治", "娱乐文化", "消费科技", "Apple")
STORIES_PER_CATEGORY = 5
SOURCES = [
    ("Apple", "MacRumors", "https://feeds.macrumors.com/MacRumors-All"),
    ("Apple", "9to5Mac", "https://9to5mac.com/feed/"),
    ("Apple", "AppleInsider", "https://appleinsider.com/rss/news/"),
    ("国内新闻", "中国新闻网·时政", "https://www.chinanews.com.cn/rss/china.xml"),
    ("国内新闻", "中国新闻网·财经", "https://www.chinanews.com.cn/rss/finance.xml"),
    ("国内新闻", "中国新闻网·社会", "https://www.chinanews.com.cn/rss/society.xml"),
    ("国内新闻", "新华网·时政", "https://www.xinhuanet.com/politics/news_politics.xml"),
    ("国内新闻", "BBC 中文", "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"),
    ("国内新闻", "The Guardian China", "https://www.theguardian.com/world/china/rss"),
    ("国内新闻", "SCMP China", "https://www.scmp.com/rss/4/feed"),
    # AnyFeeder catalog: optional mirrors; failures are skipped by collect().
    ("国内新闻", "AnyFeeder·人民网国内", "https://plink.anyfeeder.com/people/politics"),
    ("国内新闻", "AnyFeeder·澎湃新闻", "https://plink.anyfeeder.com/thepaper"),
    ("国内新闻", "AnyFeeder·经济日报", "https://plink.anyfeeder.com/jingjiribao"),
    ("国内新闻", "Google News·财新", "https://news.google.com/rss/search?q=site%3Acaixin.com+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"),
    ("国内新闻", "Google News·第一财经", "https://news.google.com/rss/search?q=site%3Ayicai.com+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"),
    ("国内新闻", "Google News·澎湃新闻", "https://news.google.com/rss/search?q=site%3Athepaper.cn+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"),
    ("国内新闻", "Google News·新京报", "https://news.google.com/rss/search?q=site%3Abjnews.com.cn+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"),
    ("国内新闻", "Google News·新浪新闻", "https://news.google.com/rss/search?q=site%3Anews.sina.com.cn+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"),
    ("国内新闻", "Google News·搜狐新闻", "https://news.google.com/rss/search?q=site%3Anews.sohu.com+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"),
    ("国内新闻", "Google News·网易新闻", "https://news.google.com/rss/search?q=site%3A163.com%2Fnews+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"),
    ("国内新闻", "Google News·腾讯新闻", "https://news.google.com/rss/search?q=site%3Anews.qq.com+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"),
    ("国内新闻", "Google News·界面新闻", "https://news.google.com/rss/search?q=site%3Ajiemian.com+when%3A1d&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"),
    ("国际政治", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("国际政治", "The Guardian World", "https://www.theguardian.com/world/rss"),
    ("国际政治", "NPR World", "https://feeds.npr.org/1004/rss.xml"),
    ("国际政治", "DW", "https://rss.dw.com/rdf/rss-en-all"),
    ("国际政治", "France 24", "https://www.france24.com/en/rss"),
    ("国际政治", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("娱乐文化", "The Guardian Culture", "https://www.theguardian.com/culture/rss"),
    ("娱乐文化", "Variety", "https://variety.com/feed/"),
    ("娱乐文化", "Deadline", "https://deadline.com/feed/"),
    ("娱乐文化", "The Hollywood Reporter", "https://www.hollywoodreporter.com/feed/"),
    ("消费科技", "The Guardian Technology", "https://www.theguardian.com/uk/technology/rss"),
    ("消费科技", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("消费科技", "The Verge", "https://www.theverge.com/rss/index.xml"),
    ("消费科技", "Wired", "https://www.wired.com/feed/rss"),
    ("消费科技", "TechCrunch", "https://techcrunch.com/feed/"),
    ("消费科技", "Engadget", "https://www.engadget.com/rss.xml"),
    ("消费科技", "AnyFeeder·IT之家", "https://plink.anyfeeder.com/ithome/it"),
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
    if parsed.path.lower().endswith((".svg", ".gif", ".html", ".htm", ".shtml", ".php", ".asp", ".aspx")) or "/article/" in parsed.path.lower() and not re.search(r"\.(?:jpe?g|png|webp|avif)$", parsed.path, re.I):
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
    for item in items:
        try:
            raw = fetch(item["url"])
            parser = ArticleText()
            parser.feed(raw.decode("utf-8", errors="replace"))
            body = "\n".join(parser.paragraphs)
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
            if not entries:
                entries = root.findall(".//{http://purl.org/rss/1.0/}item")
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
                title = html.unescape(re.sub("<[^>]+>", "", field("title", "{http://www.w3.org/2005/Atom}title", "{http://purl.org/rss/1.0/}title")))
                link = field("link", "{http://www.w3.org/2005/Atom}link", "{http://purl.org/rss/1.0/}link")
                description = html.unescape(re.sub("<[^>]+>", "", field("description", "summary", "{http://www.w3.org/2005/Atom}summary", "{http://purl.org/rss/1.0/}description")))
                date_text = field("pubDate", "{http://www.w3.org/2005/Atom}updated", "{http://purl.org/dc/elements/1.1/}date", "{http://www.w3.org/2005/Atom}published")
                try:
                    date = email.utils.parsedate_to_datetime(date_text) if not re.match(r"^\d{4}-", date_text) else dt.datetime.fromisoformat(date_text.replace("Z", "+00:00"))
                    if date.tzinfo is None: date = date.replace(tzinfo=dt.timezone.utc)
                    if date > now + dt.timedelta(minutes=10) or now - date > dt.timedelta(hours=26): continue
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
    # Allocate a separate candidate budget to every category. A global
    # newest-first [:110] cut used to starve later categories (notably tech)
    # whenever domestic/Apple feeds published more frequently.
    per_category = {}
    for category in CATEGORIES:
        selected, per_source, seen_urls = [], {}, set()
        candidates = sorted((x for x in items if x["category"] == category),
                            key=lambda x: x["published"], reverse=True)
        for item in candidates:
            pub = item["publisher"]
            if item["url"] in seen_urls or per_source.get(pub, 0) >= (5 if category == "国内新闻" else 10):
                continue
            selected.append(item)
            seen_urls.add(item["url"])
            per_source[pub] = per_source.get(pub, 0) + 1
            if len(selected) >= 24:
                break
        per_category[category] = selected
        print("Fresh candidates:", category, len(selected), "publishers:", len(per_source), flush=True)
    return [item for category in CATEGORIES for item in per_category[category]]

def generate(items):
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is missing; keeping previous edition.")
    if any(sum(item["category"] == category for item in items) < STORIES_PER_CATEGORY for category in CATEGORIES):
        raise RuntimeError("Insufficient recent sourced coverage; keeping previous edition.")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    numbered = [dict(item, source_id="S" + str(i + 1)) for i, item in enumerate(items)]
    lookup = {item["source_id"]: item for item in numbered}
    instructions = (
        "你是严谨的中文新闻编辑。每次只编辑指定的一个栏目，从过去约24小时的RSS素材中选出恰好5个最重要、互不重复的新闻事件，按重要性排序。"
        "优先考虑公共影响范围、重大政策或社会影响、实质性新进展和可核实程度，而非媒体发稿数量、轰动标题或名人热度。国内新闻应覆盖政策、经济、社会等领域，尽量选择不同独立媒体的事件，五篇新闻尽可能来自至少三家不同媒体；Google News是聚合入口，不代表原始报道媒体；新浪、搜狐、网易、腾讯等门户转载的稿件应尽量追溯原始报道，不得把转载当作独立信源；微博热搜只可作为发现新闻线索，不得将未经独立核实的热搜或用户发帖当作已证实事实；外媒报道必须聚焦中国大陆国内事务。"
        "同一事件来自不同媒体的素材必须合并成一篇，source_ids列出实际用到的1至5个来源；不同事件不得合并，不得复用素材编号。"
        "国内新闻只选中国大陆的国内政策、社会、经济与公共事务；跨国事件若主要焦点是国际外交则归国际政治。Apple栏目只选苹果公司产品、操作系统、Apple Intelligence、供应链、服务和公司重大动向；消费科技优先选择其他厂商与行业事件，避免跨栏目重复。"
        "每篇summary用100至170字解释已核实的事实，context用100至200字解释背景与影响。"
        "区分事实、当事方说法与预测；不编造引语、原因或结果。"
        "entities最多4项，优先冷门但重要的人名、作品、机构、地名；name必须在summary或context中，"
        "definition为8至65字中文解释，evidence为输入素材里逐字存在的至少12字连续证据；证据不足不标注。"
        "只返回JSON对象："
        "{\"articles\":[{\"source_ids\":[\"S1\",\"S2\"],\"title\":\"中文标题\","
        "\"summary\":\"事实概述\",\"context\":\"背景与影响\","
        "\"entities\":[{\"name\":\"名词\",\"definition\":\"释义\",\"evidence\":\"原文连续证据\"}]}]}。"
        "标题不超过32字，不得创造source_ids。"
    )
    def validate(articles):
        clean = []
        seen = set()
        seen_events = set()
        for a in articles:
            if not isinstance(a, dict):
                continue
            ids = a.get("source_ids")
            if not isinstance(ids, list) or not ids:
                ids = [a.get("source_id", "")]
            ids = list(dict.fromkeys(str(x).strip() for x in ids))[:5]
            sources = [lookup[x] for x in ids if x in lookup]
            if not sources or len(sources) != len(ids) or any(x in seen for x in ids):
                print("Skipped invalid or reused sources:", ids)
                continue
            source = sources[0]
            if any(other["category"] != source["category"] for other in sources):
                print("Skipped mixed-category event:", ids)
                continue
            event_key = re.sub(r"[^\w\u4e00-\u9fff]", "", str(a.get("title", "")).lower())[:40]
            if event_key in seen_events:
                print("Skipped duplicate event:", event_key)
                continue
            if not all(isinstance(a.get(k), str) and a[k].strip() for k in ("title", "summary", "context")):
                print("Skipped incomplete article:", ids)
                continue
            context = a["context"].strip()
            if any(term in context for term in ("现有资料不足", "素材仅", "未说明", "无法判断更深层", "没有足够信息")) or len(context) < 55:
                print("Skipped low-information background:", ids)
                continue
            # Entity explanations require a verbatim supporting span from the input source.
            source_text = json.dumps(sources, ensure_ascii=False)
            valid_entities = []
            for entry in a.get("entities", []) if isinstance(a.get("entities"), list) else []:
                if not isinstance(entry, dict):
                    continue
                name, definition, evidence = (str(entry.get(k, "")).strip() for k in ("name", "definition", "evidence"))
                if (2 <= len(name) <= 24 and 8 <= len(definition) <= 65 and
                    12 <= len(evidence) <= 250 and evidence in source_text and
                    name in a["summary"] + context and name not in ("特朗普", "习近平", "普京", "拜登", "泽连斯基") and
                    name not in {e["name"] for e in valid_entities}):
                    valid_entities.append({"name": name, "definition": definition})
                if len(valid_entities) >= 4:
                    break
            seen.update(ids)
            seen_events.add(event_key)
            clean.append({
                "title": a["title"].strip(), "summary": a["summary"].strip(),
                "context": context, "category": source["category"],
                "source_url": source["url"], "publisher": source["publisher"],
                "sources": [{"url": x["url"], "publisher": x["publisher"]} for x in sources],
                "published": source["published"], "image": source.get("image", ""),
                "entities": valid_entities,
            })
        return clean
    def ask(messages):
        payload = {"model": model, "temperature": 0.15,
                   "response_format": {"type": "json_object"}, "messages": messages}
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            method="POST",
        )
        # A model may occasionally return truncated or malformed JSON even in
        # json_object mode. Retry the *same* editorial request; never publish
        # guessed/repaired article data.
        for json_attempt in range(3):
            retry_messages = messages if json_attempt == 0 else messages + [
                {"role": "user", "content": (
                    "上一轮输出无法解析为 JSON。请重新完成同一任务，"
                    "只返回严格合法的 JSON 对象，键名必须用英文双引号，"
                    "不得使用单引号、注释、尾随逗号或 Markdown 代码块。"
                    "确保完整输出 articles 数组。"
                )}
            ]
            retry_payload = dict(payload, messages=retry_messages)
            retry_req = urllib.request.Request(
                "https://api.deepseek.com/chat/completions",
                data=json.dumps(retry_payload, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(retry_req, timeout=120) as response:
                result = json.load(response)
            choice = result["choices"][0]
            content = choice.get("message", {}).get("content", "")
            try:
                data = json.loads(content)
                if not isinstance(data, dict) or not isinstance(data.get("articles"), list):
                    raise ValueError("Expected JSON object containing articles array")
                return data
            except (json.JSONDecodeError, ValueError) as error:
                print("Invalid model JSON; retry", json_attempt + 1,
                      "of 3; finish_reason:", choice.get("finish_reason"),
                      "length:", len(content), "error:", str(error)[:160],
                      flush=True)
                if json_attempt == 2:
                    raise RuntimeError("Model returned invalid article JSON after 3 attempts; previous edition preserved") from error
                time.sleep(2 * (json_attempt + 1))

    # Independent editorial ranking prevents large newsrooms and categories from
    # crowding one another out. Never silently publish fewer than five per tab.
    output = []
    for category in CATEGORIES:
        candidates = [item for item in numbered if item["category"] == category][:32]
        if len(candidates) < STORIES_PER_CATEGORY:
            raise ValueError("Insufficient fresh stories for " + category)
        category_output = []
        for attempt in range(3):
            used = {src["url"] for article in category_output for src in article["sources"]}
            remaining = [item for item in candidates if item["url"] not in used]
            needed = STORIES_PER_CATEGORY - len(category_output)
            if needed <= 0:
                break
            prompt = (
                "栏目：" + category + "。请选出最重要的" + str(needed) +
                "个不同事件，按重要性排序；同一事件多来源合并。"
                "已入选标题（不能重复同一事件）：" +
                json.dumps([a["title"] for a in category_output], ensure_ascii=False) +
                "\n可选素材：" + json.dumps(remaining, ensure_ascii=False)
            )
            data = ask([{"role": "system", "content": instructions},
                        {"role": "user", "content": prompt}])
            new = validate(data.get("articles", []))
            used_ids = {src["url"] for article in category_output for src in article["sources"]}
            for article in new:
                if article["category"] != category or any(src["url"] in used_ids for src in article["sources"]):
                    continue
                # Exact-title guard supplements the editorial duplicate instruction.
                key_title = re.sub(r"[^\w\u4e00-\u9fff]", "", article["title"])
                if any(re.sub(r"[^\w\u4e00-\u9fff]", "", old["title"]) == key_title for old in category_output):
                    continue
                category_output.append(article)
                used_ids.update(src["url"] for src in article["sources"])
                if len(category_output) == STORIES_PER_CATEGORY:
                    break
            print("Category", category, "attempt", attempt + 1, "valid", len(category_output))
        if len(category_output) != STORIES_PER_CATEGORY:
            raise ValueError("Cannot publish " + category + ": only " + str(len(category_output)) + " verified events")
        output.extend(category_output)
    return output

def render(articles, version):
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
    # Stable, identity-only explanations: avoid time-sensitive offices, disputed claims or invented biographies.
    entities = {
        "特朗普": "唐纳德·特朗普（Donald Trump），美国政治人物、共和党人，曾任及再次担任美国总统。",
        "拜登": "乔·拜登（Joe Biden），美国民主党政治人物，2021年至2025年担任美国总统。",
        "习近平": "习近平，中国政治人物，中共中央总书记、中华人民共和国主席。",
        "普京": "弗拉基米尔·普京（Vladimir Putin），俄罗斯政治人物，长期担任俄罗斯总统或总理。",
        "泽连斯基": "弗拉基米尔·泽连斯基（Volodymyr Zelenskyy），乌克兰政治人物，2019年当选总统。",
        "马斯克": "埃隆·马斯克（Elon Musk），企业家，与特斯拉、SpaceX及xAI等企业有关。",
        "欧盟": "欧洲联盟（EU），由欧洲国家组成的政治与经济联盟；并非单一国家。",
        "欧洲委员会": "欧洲委员会（Council of Europe），独立于欧盟的国际组织，主要关注人权、民主和法治。",
        "欧盟委员会": "欧盟委员会（European Commission），欧盟主要执行机构，负责提出立法建议等事务。",
        "欧洲央行": "欧洲中央银行（ECB），负责欧元区货币政策的中央银行。",
        "美联储": "美国联邦储备系统（Federal Reserve），美国中央银行体系，负责货币政策等职能。",
        "白宫": "美国总统的官邸和主要办公场所，也常用来代指美国总统行政团队。",
        "国会": "立法机构的常见名称；在美国语境中指由众议院和参议院组成的联邦立法机关。",
        "联合国": "联合国（UN），1945年成立的国际组织，主要处理国际和平、安全、发展与合作事务。",
        "安理会": "联合国安全理事会，负责维护国际和平与安全；设五个常任理事国。",
        "北约": "北大西洋公约组织（NATO），以集体防务为核心的跨大西洋政治与军事联盟。",
        "世贸组织": "世界贸易组织（WTO），制定并管理多边贸易规则、处理成员贸易争端的国际组织。",
        "国际货币基金组织": "国际货币基金组织（IMF），关注全球货币合作、金融稳定和成员国经济政策的国际组织。",
        "世界银行": "世界银行（World Bank），主要通过融资与专业支持推动发展及减贫的国际机构。",
        "英伟达": "NVIDIA，美国半导体企业，主要开发GPU及相关计算软硬件。",
        "苹果公司": "Apple，美国消费电子及软件服务企业，产品包括iPhone、Mac等。",
        "谷歌": "Google，美国科技企业，提供搜索、广告、云计算及人工智能等产品和服务。",
        "微软": "Microsoft，美国科技企业，主要业务涉及软件、云服务与人工智能。",
        "OpenAI": "OpenAI，人工智能研究与产品开发机构，开发ChatGPT等人工智能系统。",
        "台积电": "台湾积体电路制造股份有限公司（TSMC），主要从事半导体晶圆代工。",
        "华纳兄弟": "华纳兄弟（Warner Bros.），美国影视制作与发行品牌。",
        "乌克兰": "东欧国家，首都基辅；与俄罗斯、波兰等国接壤。",
        "俄罗斯": "横跨东欧与北亚的国家，首都莫斯科。",
        "以色列": "位于西亚地中海东岸的国家。",
        "加沙地带": "位于地中海东岸、与以色列和埃及接壤的巴勒斯坦地区。",
        "台湾": "位于东亚的岛屿及周边地区；其政治地位涉及两岸争议。",
        "硅谷": "美国加利福尼亚州旧金山湾区南部的科技产业聚集地，并非行政区。",
        "华盛顿": "美国首都华盛顿哥伦比亚特区；也常被用于代指美国联邦政府。",
        "布鲁塞尔": "比利时首都，也是欧盟多家重要机构的所在地。",
    }
    glossary.update(entities)
    # Common names are intentionally not annotated; prioritize unfamiliar entities.
    for familiar in ("特朗普", "拜登", "习近平", "普京", "泽连斯基", "马斯克", "美国", "俄罗斯", "中国", "欧盟", "联合国", "谷歌", "微软", "苹果公司"):
        glossary.pop(familiar, None)
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
    def focus_text(value, article_context=None, article_entities=None, seen_terms=None):
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

        # Rare, source-supported entities take priority over the static glossary.
        definitions = dict(glossary)
        definitions.update(article_entities or {})
        pattern = re.compile("|".join(re.escape(t) for t in sorted(definitions, key=len, reverse=True)))
        for match in pattern.finditer(value):
            term = match.group()
            if seen_terms is not None and term in seen_terms:
                continue
            mark(match.start(), match.end(), "term")
            if seen_terms is not None:
                seen_terms.add(term)
        # Facts and outcomes should be noticeable without painting entire paragraphs.
        for match in list(number_pattern.finditer(value))[:3]:
            mark(match.start(), match.end(), "fact")
        for match in list(outcome_pattern.finditer(value))[:2]:
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
                result.append('<span role="button" tabindex="0" class="term" data-definition="' +
                              esc(definitions[value[first:last]] + ("\n\n在这篇新闻中：" + article_context[value[first:last]] if article_context and value[first:last] in article_context else "")) + '" aria-label="解释术语：' +
                              fragment + '">' + fragment + '</span>')
            else:
                result.append('<strong class="focus-' + kind + '">' + fragment + '</strong>')
            cursor = last
        result.append(esc(value[cursor:]))
        return ''.join(result)
    cards = {category: [] for category in CATEGORIES}
    for i, a in enumerate(articles, 1):
        headline = a["title"]
        summary = a["summary"].strip()
        context = a["context"].strip()
        # Derive entity relevance only from sentences already present in the published story.
        # Do not invent a causal explanation or a new biographical claim.
        article_context = {}
        article_entities = {e["name"]: e["definition"] for e in a.get("entities", [])}
        seen_terms = set()
        for entity in entities:
            for sentence in re.split(r"(?<=[。！？])", summary + "。" + context):
                sentence = sentence.strip()
                if entity in sentence and 12 <= len(sentence) <= 120:
                    article_context[entity] = sentence
                    break
        takeaway = re.split(r"(?<=[。！？])", summary, maxsplit=1)[0].strip()
        if len(takeaway) > 90:
            takeaway = takeaway[:87] + "…"
        image = safe_image(a.get("image", ""))
        photo = ('<figure><img src="' + esc(image) + '" alt="' + esc(headline) + '" loading="lazy" onerror="this.parentElement.hidden=true"><figcaption>图片来源：' + esc(a["publisher"]) + '</figcaption></figure>') if image else ""
        sources = a.get("sources") or [{"url": a["source_url"], "publisher": a["publisher"]}]
        source_links = ' · '.join(
            '<a href="' + esc(x["url"]) + '" target="_blank" rel="noopener noreferrer">' +
            esc(x["publisher"]) +
            ' <svg class="ui-icon source-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M8 7h9v9"/></svg></a>'
            for x in sources
        )
        cards[a["category"]].append(
            '<article class="story" id="story-' + str(i) + '" data-story="' + esc(a["source_url"]) + '">'
            '<h2>' + esc(headline) + '</h2>' + photo +
            '<div class="takeaway"><span class="micro"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m13 2-9 12h7l-1 8 10-12h-7z"/></svg> 10 秒看懂</span><p>' + focus_text(takeaway, article_context, article_entities, seen_terms) + '</p></div>'
            '<div class="standard-block"><h3>发生了什么？</h3><p>' + focus_text(summary, article_context, article_entities, seen_terms) + '</p></div>'
            '<div class="deep-block"><h3>背景与影响</h3><p>' + focus_text(context, article_context, article_entities, seen_terms) + '</p>'
            '<p class="source-note">背景解读依据已获取的新闻材料整理，不代表对未来结果的确定预测。</p></div>'
            '<div class="story-bottom"><div class="source-links"><span>核对原始报道：</span>' + source_links + '</div>'
            '<button type="button" class="share-story" aria-label="分享这篇新闻的文字内容"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V3m0 0L7 8m5-5 5 5M5 14v6h14v-6"/></svg> 分享文章</button></div></article>'
        )
    category_names = CATEGORIES
    sections = ''.join(
        '<section class="category-panel" id="panel-' + str(j) + '" aria-labelledby="tab-' + str(j) + '" role="tabpanel">'
        + ''.join(cards[category]) + '</section>'
        for j, category in enumerate(category_names)
    )
    style = """*{box-sizing:border-box}html{scroll-behavior:smooth;background:#0639f5}body{margin:0;background:#0639f5;color:#111;font-family:Arial,'PingFang SC','Microsoft YaHei',sans-serif}.paper{max-width:980px;margin:20px auto 60px;background:#f5f3ed;padding:clamp(24px,6vw,70px)}header{border-bottom:4px solid #111;padding-bottom:18px;display:flex;justify-content:space-between;gap:12px;font-size:12px;font-weight:900}header a,.story a{color:#0639f5}.hero h1{font-family:Impact,'Arial Black',sans-serif;font-size:clamp(64px,12vw,148px);line-height:.82;letter-spacing:-.05em;margin:80px 0 28px}.hero h1 em{font-family:Georgia,serif;font-weight:400}.sticker{background:#ff9cce;display:inline-block;padding:12px;transform:rotate(-7deg);border:2px solid}.lede{font-size:21px;font-weight:700;padding-bottom:25px}.reader-tools{position:relative;top:auto;z-index:10;background:#f5f3ed;border-top:3px solid;border-bottom:3px solid;padding:14px 0;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.reader-tools label{font-size:12px;font-weight:900}.modes{display:flex;gap:5px;flex-wrap:wrap}.modes button,.save{border:2px solid #111;background:transparent;color:#111;padding:9px 12px;font-weight:800;cursor:pointer}.modes button[aria-pressed=true]{background:#111;color:#fff}.progress{height:4px;position:fixed;top:env(safe-area-inset-top,0px);left:0;right:0;background:#ddd;z-index:11}.progress span{display:block;height:100%;width:0;background:#ff7e45}.story{border-bottom:3px solid;padding:42px 0;scroll-margin-top:100px}.story-meta,.story-bottom{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.kicker{font-size:12px;font-weight:900;background:#ff7e45;padding:7px}.reading-time,.micro,.source-note{font-size:12px;color:#555}.story h2{font-size:clamp(29px,5vw,52px);line-height:1.15;letter-spacing:-.03em}.story h3{font-size:20px;margin:25px 0 8px}.story p{font-size:17px;line-height:1.8}.story figure{margin:20px 0}.story figure img{display:block;width:100%;max-height:490px;object-fit:cover;background:#ddd}.story figcaption{font-size:12px;color:#555;margin-top:8px}.takeaway{background:#ffdfeb;border-left:6px solid #111;padding:18px 20px}.takeaway .micro{font-weight:900;color:#111}.takeaway p{font-weight:800;font-size:20px;line-height:1.5;margin:10px 0 0}.deep-block{background:#e9e9e4;padding:2px 20px 15px;margin:18px 0}.story-bottom{margin-top:22px}.story-bottom a{font-weight:800}.save[aria-pressed=true]{background:#ff9cce}.reading-guide{font-size:13px;line-height:1.6;color:#555}footer{padding:30px 0;font-size:13px}button:focus-visible,a:focus-visible{outline:4px solid #0639f5;outline-offset:3px}@media(max-width:600px){.paper{margin:8px;padding:22px}.hero h1{margin-top:65px}.reader-tools{top:auto}.story{padding:30px 0}.story h2{font-size:32px}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}"""
    style += """.category-nav{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;margin:20px 0 12px;padding:4px 0 10px}.category-nav::-webkit-scrollbar{display:none}.category-nav button{flex:1 0 auto;min-height:48px;border:2px solid #111;background:#f5f3ed;color:#111;font-size:15px;font-weight:850;padding:10px 14px;cursor:pointer}.category-nav button[aria-selected=true]{background:#0639f5;color:#fff}.category-rail{display:flex;align-items:flex-start;overflow-x:auto;overscroll-behavior-x:contain;scroll-snap-type:x mandatory;scrollbar-width:none;gap:0;touch-action:pan-x pan-y}.category-rail::-webkit-scrollbar{display:none}.category-panel{flex:0 0 100%;width:100%;min-width:0;scroll-snap-align:start;scroll-snap-stop:normal}.section-heading{border-bottom:4px solid #111;padding:20px 0 16px;display:flex;flex-wrap:wrap;align-items:baseline;gap:12px}.section-heading h2{font-family:Georgia,'Songti SC','Noto Serif CJK SC',serif;font-size:clamp(30px,5vw,44px);margin:0;font-weight:800}.section-index,.section-heading>span:last-child{font-size:11px;font-weight:900;letter-spacing:.07em}.story h2{font-family:'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif;font-weight:800;line-height:1.27;letter-spacing:-.015em}.story p{font-family:'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif;font-size:18px;line-height:1.85;font-weight:400;letter-spacing:.012em;overflow-wrap:anywhere}.story .takeaway p{font-size:clamp(19px,3.6vw,23px);line-height:1.62;font-weight:750}.story h3{font-family:'PingFang SC','Noto Sans CJK SC',sans-serif;font-weight:800;font-size:21px}.reading-guide{font-size:14px}.story .source-note{font-size:12px}.category-hint{font-size:12px;font-weight:700;color:#555}@media(max-width:600px){.category-nav button{font-size:14px;padding:10px 12px}.story p{font-size:17px;line-height:1.85}.story h2{font-size:30px;line-height:1.3}}@media(prefers-reduced-motion:reduce){.category-rail{scroll-behavior:auto}}"""
    style += """:root{color-scheme:light;--paper:#f5f3ed;--ink:#111;--muted:#555;--blue:#0639f5;--pink:#ffdfeb;--soft:#e9e9e4;--accent:#ff7e45}body{color:var(--ink)}.paper,.reader-tools{background:var(--paper)}.story a,header a{color:var(--blue)}.reading-time,.micro,.source-note,.category-hint,.reading-guide{color:var(--muted)}.takeaway{background:var(--pink);border-left-color:var(--ink)}.deep-block{background:var(--soft)}.kicker{background:var(--accent);color:#111}.category-nav button{background:var(--paper);color:var(--ink);border-color:var(--ink)}.category-nav button[aria-selected=true]{background:var(--blue);color:#fff}.modes button,.save{color:var(--ink);border-color:var(--ink)}.modes button[aria-pressed=true]{background:var(--ink);color:var(--paper)}.story,.section-heading,header,.reader-tools{border-color:var(--ink)}.focus-lead{font-weight:800;color:var(--ink)}.focus-fact{font-weight:800;color:var(--blue);font-size:1.045em}.takeaway .focus-fact{color:#0639f5}.story p{font-weight:400}.story p strong{letter-spacing:0}.theme-toggle{border:2px solid var(--ink);background:var(--paper);color:var(--ink);font-weight:800;min-height:42px;padding:8px 12px;cursor:pointer}.reading-header{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:space-between}.reading-progress{height:5px;background:var(--soft);margin:12px 0 0;overflow:hidden}.reading-progress span{display:block;height:100%;width:0;background:var(--accent);transition:width .1s linear}.progress{display:none!important}.category-rail{transition:height .18s ease;overflow-y:hidden}.category-panel{align-self:flex-start}.theme-dark{--paper:#171b25;--ink:#f4f1e8;--muted:#b9c1d0;--blue:#9fb4ff;--pink:#392b43;--soft:#252c39;--accent:#ff9c79;background:#0b1020;color-scheme:dark}.theme-dark .paper,.theme-dark .reader-tools{background:var(--paper)}.theme-dark .takeaway .micro{color:var(--ink)}.theme-dark .takeaway .focus-fact{color:#c6d0ff}.theme-dark .category-nav button[aria-selected=true]{background:#9fb4ff;color:#10131d}.theme-dark .modes button[aria-pressed=true]{background:#f4f1e8;color:#171b25}.theme-dark .save[aria-pressed=true]{background:#59405b}.theme-dark .story figure img{background:#343c4a}.theme-dark .sticker{color:#111}.theme-dark .kicker{color:#111}@media(prefers-reduced-motion:reduce){.category-rail{transition:none}.reading-progress span{transition:none}}"""
    style += """.term{display:inline;color:inherit;background:transparent;border:0;border-bottom:2px dotted var(--blue);padding:0 1px;font:inherit;font-weight:750;cursor:pointer;text-decoration:none;vertical-align:baseline}.term:focus-visible{outline:3px solid var(--blue);outline-offset:2px}.term-dialog{border:0;border-radius:22px;padding:0;max-width:min(90vw,520px);width:100%;box-shadow:0 24px 70px #0005;background:var(--paper);color:var(--ink)}.term-dialog::backdrop{background:#0009}.term-dialog-inner{padding:26px 26px 30px}.term-dialog-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.term-dialog h2{font-size:24px;margin:0;font-weight:850}.term-dialog p{font-size:17px;line-height:1.75;margin:18px 0 0}.term-close{border:2px solid var(--ink);background:transparent;color:var(--ink);font-size:24px;width:44px;height:44px;cursor:pointer}.term-dialog .term-hint{font-size:12px;color:var(--muted);margin-top:18px}.focus-lead{font-weight:800}.focus-fact{font-weight:850}.focus-outcome{font-weight:800;color:var(--blue)}.takeaway .focus-outcome{color:#0639f5}.theme-dark .takeaway .focus-outcome{color:#c6d0ff}@media(prefers-reduced-motion:reduce){.term-dialog{scroll-behavior:auto}}"""
    style += """.reader-tools{padding:12px 0;border-top:2px solid var(--ink);border-bottom:2px solid var(--ink);gap:16px}.edition-label{font-size:12px;font-weight:850;letter-spacing:.11em}.edition-label span{color:var(--muted);margin:0 7px}.theme-toggle{font-size:12px;letter-spacing:.03em;min-height:38px;padding:7px 12px}.category-nav{gap:0;border:2px solid var(--ink);padding:0;margin-top:24px;margin-bottom:14px;overflow-x:auto}.category-nav button{border:0;border-right:1px solid var(--ink);display:flex;align-items:center;justify-content:center;gap:9px;min-height:62px;padding:11px 13px;font-size:14px;font-weight:800;letter-spacing:.02em;white-space:nowrap;transition:background .15s,color .15s}.category-nav button:last-child{border-right:0}.category-nav button[aria-selected=true]{background:var(--ink);color:var(--paper)}.theme-dark .category-nav button[aria-selected=true]{background:var(--ink);color:var(--paper)}.nav-index{font-family:Georgia,serif;font-size:10px;font-weight:700;opacity:.55;align-self:flex-start;margin-top:1px}.nav-mark{width:21px;height:21px;display:inline-flex;align-items:center;justify-content:center;flex:none;position:relative;color:currentColor}.nav-world{border:1.8px solid currentColor;border-radius:50%}.nav-world:before{content:'';position:absolute;width:7px;height:17px;border-left:1.4px solid;border-right:1.4px solid;border-radius:50%}.nav-world:after{content:'';position:absolute;width:17px;border-top:1.4px solid}.nav-culture{border:1.8px solid currentColor;border-radius:50%}.nav-culture:before{content:'';width:9px;height:9px;border:1.5px solid currentColor;transform:rotate(45deg)}.nav-culture:after{content:'';position:absolute;width:3px;height:3px;background:currentColor;border-radius:50%}.nav-tech{border:1.8px solid currentColor;border-radius:4px}.nav-tech:before{content:'';width:8px;height:8px;border:1.5px solid currentColor;border-radius:1px}.nav-tech:after{content:'';position:absolute;left:-4px;right:-4px;top:7px;height:4px;border-left:2px solid currentColor;border-right:2px solid currentColor}.reading-progress,.progress,.modes{display:none!important}.reading-guide{margin:15px 0 12px;line-height:1.7}@media(max-width:600px){.category-nav button{flex:1 0 auto;min-height:58px;gap:7px;padding:9px 11px;font-size:13px}.nav-index{display:none}.nav-mark{width:19px;height:19px}.edition-label{font-size:11px}}@media(prefers-reduced-motion:reduce){.category-nav button{transition:none}}"""
    style += """.paper{padding-top:18px}.paper>header{border-bottom:0;padding-bottom:7px;font-size:10px;font-weight:750;color:var(--muted)}.masthead{display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:2px solid var(--ink);padding:4px 0 14px}.masthead-brand{display:flex;flex-direction:column;gap:4px;min-width:0}.masthead-name{font-family:Impact,'Arial Black',sans-serif;font-size:clamp(28px,6vw,52px);font-weight:900;line-height:1;letter-spacing:-.045em;white-space:nowrap}.masthead-name em{font-family:Georgia,serif;font-weight:400}.masthead-date{font-size:10px;letter-spacing:.11em;color:var(--muted);font-weight:750}.masthead .theme-toggle{flex:none}.category-nav{margin:12px 0 4px}.category-rail .category-panel>.story:first-child{padding-top:18px}.section-heading,.category-hint,.reader-tools,.reading-guide{display:none!important}@media(max-width:600px){.paper{padding-top:14px}.masthead-name{font-size:clamp(27px,7.5vw,38px)}.category-nav{margin-top:12px}.category-nav button{min-height:50px}.category-rail .category-panel>.story:first-child{padding-top:14px}}"""
    style += """.story p{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif;font-size:clamp(17px,1.5vw,19px);font-weight:400;line-height:1.88;letter-spacing:.013em}.story p .focus-lead{font-weight:850;color:var(--ink);font-size:1.045em;letter-spacing:-.012em}.story p .focus-outcome{font-weight:850;color:var(--blue);font-size:1.09em;line-height:1.45;box-decoration-break:clone;-webkit-box-decoration-break:clone}.story p .focus-fact{font-weight:900;color:var(--blue);font-size:1.17em;font-variant-numeric:tabular-nums;letter-spacing:-.025em}.story .takeaway p{font-size:clamp(19px,2.5vw,23px);line-height:1.72;font-weight:550}.story .takeaway .focus-outcome{font-size:1.08em}.story .takeaway .focus-fact{font-size:1.14em}.story .term{font-weight:750;text-decoration-thickness:2px;text-underline-offset:3px}.theme-dark .story p .focus-outcome,.theme-dark .story p .focus-fact{color:#b3c5ff}.theme-dark .story .takeaway .focus-outcome,.theme-dark .story .takeaway .focus-fact{color:#c6d0ff}@media(max-width:600px){.story p{font-size:17px;line-height:1.84;letter-spacing:.008em}.story p .focus-outcome{font-size:1.065em}.story p .focus-fact{font-size:1.12em}}"""
    style += """.type-lab-link{font:inherit;color:var(--blue);border:0;background:none;text-decoration:underline;text-underline-offset:3px;cursor:pointer;padding:6px}.type-lab{border:0;border-radius:18px;padding:0;max-width:min(92vw,520px);width:100%;background:var(--paper);color:var(--ink);box-shadow:0 22px 65px #0006}.type-lab::backdrop{background:#0009}.type-lab-inner{padding:24px}.type-lab-head{display:flex;justify-content:space-between;gap:12px;align-items:center}.type-lab h2{font-size:22px;margin:0}.type-lab p{font-size:14px;line-height:1.7;color:var(--muted)}.type-lab-options{display:grid;gap:8px;margin:20px 0}.type-lab-options button{padding:13px;text-align:left;background:var(--paper);color:var(--ink);border:2px solid var(--muted);font:inherit;cursor:pointer}.type-lab-options button[aria-pressed=true]{border-color:var(--blue);box-shadow:inset 4px 0 var(--blue);font-weight:800}.type-lab-close{background:transparent;color:var(--ink);border:2px solid var(--ink);font-size:24px;width:40px;height:40px;cursor:pointer}.type-lab-note{font-size:12px!important}.type-b .story p:not(.takeaway p){font-family:'Songti SC','Noto Serif CJK SC','Source Han Serif SC',serif;line-height:1.92;letter-spacing:.006em}.type-b .story h2{font-family:'PingFang SC','Noto Sans CJK SC',sans-serif}.type-c .story p .focus-outcome,.type-c .story p .focus-lead{font-size:1em;font-weight:700;color:var(--ink)}.type-c .story p .focus-fact{font-size:1.035em;font-weight:750;color:var(--blue)}.type-c .story .takeaway p{font-weight:500}.type-c .story .term{font-weight:650}@media(max-width:600px){.type-lab-inner{padding:20px}}"""
    style += """.story .term{color:var(--blue);border-bottom:1px dashed currentColor;text-decoration:none;cursor:help}.story .term:focus-visible{outline:2px solid var(--blue);outline-offset:3px}.theme-dark .story .term{color:#b3c5ff}"""
    style += """html{background:#e8e7e3}body{background:#e8e7e3}.paper{margin-top:0}.theme-dark{background:#0e121b}.theme-dark .paper{box-shadow:0 0 0 1px #303643}html:has(body.theme-dark){background:#0e121b}body.theme-dark{background:#0e121b}.header-actions{display:flex;align-items:center;gap:16px}.toc-open{border:0;background:none;color:var(--blue);font:inherit;font-size:12px;font-weight:850;padding:4px 0;cursor:pointer}.toc-dialog{border:0;border-radius:18px;padding:0;width:min(92vw,600px);max-height:min(78dvh,750px);background:var(--paper);color:var(--ink);box-shadow:0 22px 70px #0008}.toc-dialog::backdrop{background:#000a}.toc-inner{padding:22px}.toc-head{display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:2px solid var(--ink);padding-bottom:12px}.toc-head h2{font-size:22px;margin:0}.toc-close{width:38px;height:38px;border:1px solid var(--ink);background:transparent;color:var(--ink);font-size:24px;cursor:pointer}.toc-group{margin-top:16px}.toc-group h3{font-size:12px;color:var(--muted);letter-spacing:.08em;margin:0 0 6px}.toc-item{display:block;width:100%;text-align:left;background:transparent;color:var(--ink);border:0;border-bottom:1px solid var(--soft);font:inherit;font-size:15px;font-weight:650;line-height:1.45;padding:12px 3px;cursor:pointer}.toc-item:hover,.toc-item:focus-visible{color:var(--blue)}.story-meta .kicker{background:transparent;color:var(--muted);padding:0;font-size:11px;font-weight:750}.theme-dark .story-meta .kicker{color:var(--muted)}@media(max-width:600px){.paper{margin-top:0}.toc-inner{padding:18px}.header-actions{gap:12px}}"""
    style += """.toc-open{display:inline-flex;align-items:center;gap:8px;font-size:13px!important;font-weight:900!important;color:var(--ink)!important;padding:8px 10px!important;border:1.5px solid var(--ink)!important;border-radius:8px;background:transparent!important;letter-spacing:.01em}.toc-open::before{content:"";width:17px;height:16px;flex:none;background:linear-gradient(var(--ink),var(--ink)) 0 1px/17px 2.5px no-repeat,linear-gradient(var(--ink),var(--ink)) 0 7px/17px 2.5px no-repeat,linear-gradient(var(--ink),var(--ink)) 0 13px/12px 2.5px no-repeat}.toc-open:hover,.toc-open:focus-visible{background:var(--soft)!important}.toc-dialog{overscroll-behavior:contain;overflow:hidden;max-height:min(82dvh,760px)}.toc-inner{max-height:min(82dvh,760px);overflow-y:auto;overscroll-behavior:contain;-webkit-overflow-scrolling:touch}.toc-head{position:sticky;top:-22px;background:var(--paper);z-index:2}.story-meta .kicker{display:none!important}.story-meta{justify-content:flex-end}.story{scroll-margin-top:18px}@media(max-width:600px){.toc-head{top:-18px}.toc-open{min-height:36px}}"""
    style += """.story>.story-meta{display:none!important}.story>h2{margin-top:0}.deep-block h3,.standard-block h3{letter-spacing:.015em}"""
    style += """.ui-icon{display:inline-block;width:1.05em;height:1.05em;vertical-align:-.15em;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;flex:none}.takeaway .micro,.theme-toggle,.save{display:inline-flex;align-items:center;gap:6px}.save[aria-pressed=true] .ui-icon{fill:currentColor}"""
    style += """.share-story{display:inline-flex;align-items:center;gap:7px;border:1.5px solid var(--ink);background:transparent;color:var(--ink);padding:9px 12px;font:inherit;font-size:13px;font-weight:800;cursor:pointer;border-radius:6px}.share-story:hover,.share-story:focus-visible{background:var(--soft)}"""
    style += """.toc-open{border-radius:0!important;border:1.5px solid var(--ink)!important;padding:9px 12px!important;min-height:40px}.theme-toggle{border:0!important;border-radius:0!important;background:transparent!important;padding:6px 0!important;min-height:32px!important;font-size:12px;font-weight:700!important;color:var(--muted)!important;display:inline-flex;align-items:center;gap:5px}.theme-toggle:hover,.theme-toggle:focus-visible{color:var(--ink)!important;text-decoration:underline;text-underline-offset:4px}.header-actions{gap:10px}.masthead>.toc-open{flex-shrink:0}.story-bottom a{display:inline-flex;align-items:center;gap:4px}.source-arrow{width:.9em;height:.9em}@media(max-width:600px){.masthead>.toc-open{padding:8px!important;font-size:12px!important}.theme-toggle{font-size:11px}}"""
    style += """header>.header-actions{order:0}header>span:not(.header-actions){order:1}header .theme-toggle{justify-content:flex-start;text-align:left}"""
    style += """/* Visual audit: unified top baseline, mobile rhythm, touch targets and contrast. */
.paper>header{display:flex;align-items:center;justify-content:space-between;min-height:38px;padding:0 0 8px;gap:12px;line-height:1.35}
.paper>header>.header-actions{display:flex;align-items:center;min-height:30px;flex:0 0 auto}
.paper>header>span:not(.header-actions){display:flex;align-items:center;min-height:30px;text-align:right;font-size:11px;font-weight:750;letter-spacing:.015em;line-height:1.35}
.paper>header .theme-toggle{display:inline-flex;align-items:center;justify-content:flex-start;min-height:30px!important;gap:6px;padding:4px 0!important;margin:0;line-height:1.35;font-size:11px!important;font-weight:750!important;white-space:nowrap}
.paper>header .theme-toggle .ui-icon{width:15px;height:15px;vertical-align:0}
.masthead{align-items:center;gap:16px}
.masthead-brand{min-width:0}
.masthead-name{max-width:100%}
.masthead>.toc-open{flex:0 0 auto;white-space:nowrap;min-height:42px}
.story h2{overflow-wrap:anywhere;text-wrap:pretty}
.story figure img{height:auto}
.story-bottom a{min-width:0;overflow-wrap:anywhere;line-height:1.55}
.story-bottom .share-story{min-height:42px}
.term-dialog,.toc-dialog,.type-lab{max-width:calc(100vw - 28px)}
.term-dialog p{overflow-wrap:anywhere;white-space:pre-line}
@media(max-width:600px){.paper{padding-left:clamp(18px,5.4vw,26px);padding-right:clamp(18px,5.4vw,26px)}.paper>header{gap:8px}.paper>header>span:not(.header-actions){font-size:10px}.masthead{gap:10px}.masthead-name{font-size:clamp(25px,7.2vw,38px)}.masthead>.toc-open{min-height:40px}.category-nav button{padding-inline:8px}.story h2{font-size:clamp(29px,7.5vw,38px)}.story .takeaway{padding:16px 17px}.story .deep-block{padding:2px 16px 14px}.story-bottom{align-items:flex-start}.toc-inner{padding:18px}}"""
    style += """/* Brand reference: electric-blue editorial frame, not a blue reading surface. */
:root{--brand-electric:#0639f5}
html:not(:has(body.theme-dark)){background:var(--brand-electric)}
body:not(.theme-dark){background:var(--brand-electric)}
body:not(.theme-dark) .paper{box-shadow:0 0 0 1px rgba(0,0,0,.07)}
.category-nav button[aria-selected=true],.theme-dark .category-nav button[aria-selected=true]{background:var(--brand-electric)!important;color:#fff!important;border-color:var(--brand-electric)!important}
.category-nav button[aria-selected=true] .nav-mark{color:#fff}
.masthead{border-bottom-color:var(--brand-electric)}
.toc-open{border-color:var(--brand-electric)!important}
.toc-open::before{background:linear-gradient(var(--brand-electric),var(--brand-electric)) 0 1px/17px 2.5px no-repeat,linear-gradient(var(--brand-electric),var(--brand-electric)) 0 7px/17px 2.5px no-repeat,linear-gradient(var(--brand-electric),var(--brand-electric)) 0 13px/12px 2.5px no-repeat}
.story .term{color:var(--blue)}
.theme-dark{--brand-electric:#3867ff}
html:has(body.theme-dark),body.theme-dark{background:#0e121b}
.theme-dark .masthead{border-bottom-color:#547aff}
.theme-dark .toc-open{border-color:#547aff!important}
.theme-dark .category-nav button[aria-selected=true]{background:#3867ff!important;border-color:#3867ff!important;color:#fff!important}
@media(min-width:1024px){body:not(.theme-dark) .paper{margin:26px auto 60px}.paper{position:relative}}
@media(max-width:600px){html:not(:has(body.theme-dark)),body:not(.theme-dark){background:var(--paper)}body:not(.theme-dark) .paper{border-top:4px solid var(--brand-electric);margin-top:0}.masthead{border-bottom-width:2px}.category-nav button[aria-selected=true]{box-shadow:inset 0 -3px #fff3}}"""
    style += """/* Quiet source attribution: a recognizable publisher wordmark, not a photo overlay. */
.source-mark{display:inline-flex;align-items:center;gap:8px;max-width:100%;margin:12px 0 15px;color:var(--muted);font-size:11px;line-height:1.3;font-weight:700;letter-spacing:.02em}
.source-mark .source-wordmark{display:inline-flex;align-items:center;gap:2px;color:var(--ink);font-size:13px;font-weight:900;line-height:1;letter-spacing:-.025em}
.source-mark .source-wordmark.bbc span{display:inline-grid;place-items:center;width:18px;height:18px;background:var(--ink);color:var(--paper);font:800 12px/1 Arial,sans-serif}
.source-mark .source-wordmark.guardian{font:700 17px/1 Georgia,serif;letter-spacing:-.055em}
.source-mark .source-wordmark.variety{font:italic 800 17px/1 Georgia,serif;letter-spacing:-.05em}
.source-mark .source-wordmark.ars{font:800 15px/1 Arial,sans-serif;letter-spacing:-.05em}
.source-mark .source-caption{font-size:10px;color:var(--muted);font-weight:600}
.story>.source-mark{opacity:.78}
@media(max-width:600px){.story>.source-mark{margin:10px 0 14px}}"""
    style += """.source-links{display:flex;align-items:center;gap:7px;flex-wrap:wrap;min-width:0;font-size:12px}.source-links>span{color:var(--muted);font-weight:650}.source-links a{display:inline-flex;align-items:center;gap:2px;min-height:30px}.story-bottom{align-items:center}.story>.source-mark{margin-bottom:12px}"""
    style += """/* Editorial hierarchy: neutral outlined navigation, distinct headline panels. */
.toc-open,.theme-dark .toc-open{border:1.5px solid var(--ink)!important;color:var(--ink)!important;background:transparent!important}
.toc-open::before,.theme-dark .toc-open::before{background:linear-gradient(var(--ink),var(--ink)) 0 1px/17px 2.5px no-repeat,linear-gradient(var(--ink),var(--ink)) 0 7px/17px 2.5px no-repeat,linear-gradient(var(--ink),var(--ink)) 0 13px/12px 2.5px no-repeat!important}
.story>h2{background:#e7ebff;color:#111111;border-left:5px solid #0639f5;padding:19px 20px;margin:0 0 18px;line-height:1.27;box-sizing:border-box}
.theme-dark .story>h2{background:#202a42;color:var(--ink);border-left-color:#6686ff}
.story>.source-mark{margin:0 0 16px 5px}
@media(max-width:600px){.story>h2{padding:17px 16px;margin-bottom:16px;border-left-width:4px}}
"""
    style += """/* Consolidated attribution: one linked publisher mark, optional additional reporting. */
.source-mark a{display:inline-flex;align-items:center;gap:8px;color:inherit;text-decoration:none;min-height:30px}
.source-mark a:hover .source-wordmark,.source-mark a:focus-visible .source-wordmark{text-decoration:underline;text-underline-offset:3px}
.source-mark .source-arrow{width:12px;height:12px;opacity:.65}
.story figure figcaption{display:none}
.story-bottom .source-links{display:none}
.story-bottom .source-links.has-additional{display:flex}
.story-bottom .source-links.has-additional>span{font-size:11px}
"""
    style += """/* Mobile interaction regression fixes: remove stray rail edge and stabilize category changes. */
.category-rail{border:0!important;outline:0!important;box-shadow:none!important;scroll-behavior:auto!important;overflow-y:clip!important}
.category-panel{border-left:0!important;border-right:0!important;outline:0!important;box-shadow:none!important}
.category-panel>.story{border-left:0;border-right:0}
.story>h2{border-right:0!important;outline:0!important}
html,body{overflow-x:clip}
button,a,[role="tab"]{touch-action:manipulation}
.category-nav{position:relative;z-index:2}
@media(max-width:600px){.category-rail{scroll-snap-type:none!important}.category-panel{scroll-snap-align:none!important}}
"""
    style += """/* Lightweight reader feedback, no tracking or third-party form embeds. */
.feedback-link{border:0;border-bottom:1px solid currentColor;padding:0;background:none;color:var(--ink);font:inherit;font-weight:800;cursor:pointer}
.feedback-dialog{width:min(92vw,520px);max-height:85dvh;overflow:auto;border:2px solid var(--ink);border-radius:0;padding:0;background:var(--paper);color:var(--ink);box-shadow:12px 12px 0 #0639f5}
.feedback-dialog::backdrop{background:#000a}
.feedback-inner{padding:22px;display:grid;gap:14px}
.feedback-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
.feedback-head h2{margin:0;font-size:23px}
.feedback-close{border:1px solid var(--ink);background:transparent;color:var(--ink);font-size:22px;width:38px;height:38px;cursor:pointer}
.feedback-inner label{display:grid;gap:7px;font-size:13px;font-weight:800}
.feedback-inner select,.feedback-inner textarea{width:100%;border:1px solid var(--ink);background:var(--paper);color:var(--ink);font:inherit;font-size:16px;padding:11px;border-radius:0}
.feedback-inner textarea{min-height:118px;resize:vertical}
.feedback-send{border:2px solid var(--ink);background:#0639f5;color:white;padding:12px;font:inherit;font-weight:800;cursor:pointer}
.feedback-note{font-size:12px;line-height:1.65;color:var(--muted);margin:0}
"""
    style += """.category-nav{overflow-x:auto;scrollbar-width:none}.category-nav button{flex:1 0 auto;min-width:0}.nav-domestic{border:2px solid currentColor;border-radius:2px;transform:rotate(-5deg)}.nav-domestic::before{content:"";display:block;position:absolute;left:4px;right:4px;top:5px;border-top:2px solid currentColor}.nav-domestic::after{content:"";display:block;position:absolute;left:4px;right:4px;bottom:5px;border-top:2px solid currentColor}@media(max-width:700px){.category-nav button{flex:0 0 auto;min-width:29%;padding:11px 13px}.category-nav{scroll-snap-type:x proximity}.category-nav button{scroll-snap-align:start}}"""
    style += """/* Four equal-width editorial tabs; force one complete panel per swipe. */
.category-nav{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr));gap:0!important;overflow:visible!important;width:100%;padding:0!important;scroll-snap-type:none!important}
.category-nav button{min-width:0!important;width:100%;min-height:54px;flex:none!important;padding:10px 4px!important;font-size:clamp(10px,2.7vw,15px)!important;display:flex;align-items:center;justify-content:center;gap:4px;white-space:nowrap}
.category-nav button+button{border-left-width:0}
.category-nav .nav-index,.category-nav .nav-mark{display:none!important}
.category-rail{scroll-snap-type:x mandatory!important;scroll-padding:0!important;overscroll-behavior-x:contain;touch-action:pan-x pan-y}
.category-panel{scroll-snap-align:start!important;scroll-snap-stop:always!important}
@media(max-width:700px){.category-nav{gap:0!important}.category-nav button{min-width:0!important;padding:11px 2px!important;font-size:clamp(10px,2.85vw,13px)!important;letter-spacing:-.025em}}
"""
    style += """/* Safari: never paint the adjacent category inside the active article. */
.category-rail{width:100%;max-width:100%;min-width:0;overflow-x:auto!important;overflow-y:hidden!important;clip-path:inset(0 0 0 0);scroll-snap-type:x mandatory!important;scroll-padding-inline:0!important;gap:0!important}
.category-panel{box-sizing:border-box;flex:0 0 100%!important;width:100%!important;min-width:100%!important;max-width:100%!important;overflow:hidden!important;scroll-snap-align:start!important;scroll-snap-stop:always!important}
.category-panel .story,.category-panel .takeaway,.category-panel .deep-block{max-width:100%;min-width:0;overflow-wrap:anywhere}
.category-panel img{max-width:100%;height:auto}
"""
    style += """/* One visible category only: no adjacent panel can bleed into Safari's viewport. */
.category-rail{display:block!important;width:100%!important;height:auto!important;overflow:visible!important;scroll-snap-type:none!important;clip-path:none!important;touch-action:pan-y!important}
.category-panel{display:block!important;width:100%!important;min-width:0!important;max-width:100%!important;overflow:visible!important;scroll-snap-align:none!important}
.category-panel[hidden]{display:none!important}
.category-panel .story{max-width:100%;overflow-wrap:anywhere}
"""
    style += """/* Final isolation: the reader is a single-column document, never a horizontal scroller. */
.paper{overflow-x:clip!important}
.category-rail{display:block!important;position:relative!important;overflow-x:clip!important;overflow-y:visible!important;max-width:100%!important;min-width:0!important;scroll-snap-type:none!important;scroll-behavior:auto!important;transform:none!important}
.category-panel{display:block!important;position:relative!important;left:auto!important;right:auto!important;transform:none!important;box-sizing:border-box!important;min-width:0!important;width:100%!important;max-width:100%!important;overflow-x:clip!important;overflow-y:visible!important}
.category-panel[hidden],.category-panel[aria-hidden="true"]{display:none!important}
.category-panel .story,.category-panel .story>*,.category-panel figure{box-sizing:border-box;max-width:100%;min-width:0}
.category-panel figure img{display:block;max-width:100%;object-fit:contain}
"""
    style += """.category-nav{gap:0!important;border:2px solid var(--ink)!important}.category-nav button{border:0!important;border-right:2px solid var(--ink)!important;border-radius:0!important}.category-nav button:last-child{border-right:0!important}.category-nav button[aria-selected=true]{box-shadow:inset 0 -3px 0 #ffffff88!important}.story figure[hidden]{display:none!important}"""
    style += """.category-nav button[aria-selected=true],.theme-dark .category-nav button[aria-selected=true]{border-right:2px solid var(--ink)!important}.category-nav button:last-child[aria-selected=true],.theme-dark .category-nav button:last-child[aria-selected=true]{border-right:0!important}"""
    style += """/* Five columns fit the phone viewport, with concise mobile labels. */
.category-nav{display:grid!important;grid-template-columns:repeat(5,minmax(0,1fr))!important;width:100%!important;overflow:hidden!important}
.category-nav button{box-sizing:border-box!important;min-width:0!important;width:100%!important;overflow:hidden!important;padding:10px 1px!important;font-size:clamp(10px,2.7vw,14px)!important;letter-spacing:-.04em!important}
@media(max-width:700px){.category-nav #tab-0 .nav-label{font-size:0}.category-nav #tab-0 .nav-label::after{content:"国内";font-size:clamp(11px,3vw,14px)}.category-nav #tab-1 .nav-label{font-size:0}.category-nav #tab-1 .nav-label::after{content:"国际";font-size:clamp(11px,3vw,14px)}.category-nav #tab-2 .nav-label{font-size:0}.category-nav #tab-2 .nav-label::after{content:"文娱";font-size:clamp(11px,3vw,14px)}.category-nav #tab-3 .nav-label{font-size:0}.category-nav #tab-3 .nav-label::after{content:"科技";font-size:clamp(11px,3vw,14px)}.category-nav #tab-4 .nav-label{font-size:clamp(11px,3vw,14px)}}
"""
    style += """.story .term{display:inline!important;vertical-align:baseline!important;text-align:inherit!important;white-space:normal!important;word-break:normal!important;overflow-wrap:break-word!important;font:inherit;font-weight:750;line-height:inherit;cursor:pointer}
.category-nav button{min-height:38px!important;height:42px!important;padding:5px 1px!important}
@media(max-width:700px){.category-nav button{height:40px!important;min-height:40px!important;padding:4px 1px!important}}
"""
    style += """.site-footer{display:flex;flex-direction:column;gap:12px;padding-top:22px}.footer-main,.footer-signature{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}.footer-signature{padding-top:12px;border-top:1px solid currentColor;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;letter-spacing:.055em}.footer-signature strong{font-weight:900;font-size:1.2em;letter-spacing:.08em}.footer-version{white-space:nowrap}.footer-update{font-size:12px;opacity:.65}@media(max-width:700px){.footer-signature{font-size:11px;gap:8px}}"""
    style += """.audio-entry{display:inline-flex;align-items:center;justify-content:center;align-self:center;padding:10px 12px;border:2px solid var(--ink);color:var(--ink)!important;text-decoration:none;font-size:12px;font-weight:900;white-space:nowrap}.audio-entry:hover,.audio-entry:focus-visible{background:var(--ink);color:var(--paper)!important}@media(max-width:700px){.audio-entry{padding:7px 8px;font-size:11px}}"""
    style += """.header-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.header-actions .audio-entry{font-size:12px;padding:7px 9px;min-height:34px}@media(max-width:700px){.header-actions{gap:7px}.header-actions .audio-entry{font-size:11px;padding:6px 8px}}"""
    style += """.home-podcast{border:3px solid var(--ink,#111);padding:18px;margin:18px 0 22px;background:var(--paper,#f5f3ed)}.home-podcast[hidden]{display:none!important}.home-podcast-heading{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:14px;font-size:12px}.home-podcast-heading span{color:var(--muted,#555)}.home-podcast audio{display:block}.audio-entry{cursor:pointer;background:var(--paper,#f5f3ed);font-family:inherit}.audio-entry[aria-expanded=true]{background:var(--blue,#0639f5);color:#fff!important}"""
    script = r"""(function(){
const root=document.body;
const glossaryDialog=document.querySelector('#term-dialog');
let lastTerm=null;
document.addEventListener('click',e=>{const term=e.target.closest('.term');if(!term)return;lastTerm=term;document.querySelector('#term-title').textContent=term.textContent;document.querySelector('#term-definition').textContent=term.dataset.definition;glossaryDialog.showModal()});
document.addEventListener('keydown',e=>{const term=e.target.closest?.('.term');if(term&&(e.key==='Enter'||e.key===' ')){e.preventDefault();term.click()}});
document.querySelector('.term-close').addEventListener('click',()=>glossaryDialog.close());
glossaryDialog.addEventListener('click',e=>{if(e.target===glossaryDialog)glossaryDialog.close()});
glossaryDialog.addEventListener('close',()=>lastTerm?.focus());

const themeButton=document.querySelector('.theme-toggle');
let savedTheme='auto';try{savedTheme=localStorage.getItem('tdn-theme')||'auto'}catch(e){}
const darkPreference=matchMedia('(prefers-color-scheme: dark)');
function applyTheme(){const dark=savedTheme==='dark'||(savedTheme==='auto'&&darkPreference.matches);root.classList.toggle('theme-dark',dark);themeButton.innerHTML=(dark?`<svg class=\"ui-icon\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><circle cx=\"12\" cy=\"12\" r=\"4\"/><path d=\"M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42\"/></svg>`:`<svg class=\"ui-icon\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M20.5 14.3A8.5 8.5 0 0 1 9.7 3.5 8.5 8.5 0 1 0 20.5 14.3Z\"/></svg>`)+(dark?' 日间':' 午夜');themeButton.setAttribute('aria-label',dark?'切换到日间模式':'切换到午夜模式');document.querySelector('meta[name="theme-color"]').content=dark?'#0b1020':'#0639f5'}
themeButton.addEventListener('click',()=>{savedTheme=root.classList.contains('theme-dark')?'light':'dark';try{localStorage.setItem('tdn-theme',savedTheme)}catch(e){}applyTheme()});
darkPreference.addEventListener?.('change',()=>{if(savedTheme==='auto')applyTheme()});applyTheme();
document.querySelectorAll('.share-story').forEach(button=>{button.addEventListener('click',async()=>{const story=button.closest('.story');const title=story.querySelector('h2')?.textContent.trim()||'新闻';const summary=story.querySelector('.standard-block p')?.textContent.trim()||'';const context=story.querySelector('.deep-block>p')?.textContent.trim()||'';const sources=[...story.querySelectorAll('.story-bottom .source-links a')];const badge=story.querySelector('.source-mark a');const sourceText=[...(badge?[badge]:[]),...sources].map(a=>a.textContent.trim()+'：'+a.href).join('；');const text=[title,'','发生了什么？',summary,'','背景与影响',context,'','原始报道：'+sourceText,'','—— THE DAILY NOISE · 每日中文新闻简报','https://the-daily-noise.pages.dev/'].join('\n');try{if(navigator.share){await navigator.share({title,text});return}if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(text);const old=button.innerHTML;button.textContent='已复制分享文本';setTimeout(()=>button.innerHTML=old,1800);return}throw new Error('Clipboard unavailable')}catch(error){if(error?.name==='AbortError')return;try{await navigator.clipboard.writeText(text);const old=button.innerHTML;button.textContent='已复制分享文本';setTimeout(()=>button.innerHTML=old,1800)}catch(e){const box=document.createElement('textarea');box.value=text;box.setAttribute('readonly','');box.style.cssText='position:fixed;left:-9999px';document.body.append(box);box.select();const ok=document.execCommand('copy');box.remove();if(ok){const old=button.innerHTML;button.textContent='已复制分享文本';setTimeout(()=>button.innerHTML=old,1800)}else alert('无法自动分享，请使用浏览器的分享功能')}}})});
function sourceBadge(publisher){const name=publisher.toLowerCase();let wordmark;if(name.includes('bbc'))wordmark='<span class="source-wordmark bbc"><span>B</span><span>B</span><span>C</span></span>';else if(name.includes('guardian'))wordmark='<span class="source-wordmark guardian">The Guardian</span>';else if(name.includes('variety'))wordmark='<span class="source-wordmark variety">Variety</span>';else if(name.includes('ars technica'))wordmark='<span class="source-wordmark ars">ars technica</span>';else{const el=document.createElement('span');el.className='source-wordmark';el.textContent=publisher;return el.outerHTML}return wordmark}
document.querySelectorAll('.story').forEach(story=>{const source=story.querySelector('.story-bottom .source-links a, .story-bottom a');if(!source)return;const publisher=source.textContent.replace(/^核对原始报道：/,'').trim();if(!publisher)return;const mark=document.createElement('div');mark.className='source-mark';mark.setAttribute('aria-label','新闻来源：'+publisher);mark.innerHTML='<span class="source-caption">SOURCE</span>'+sourceBadge(publisher);story.querySelector('h2')?.insertAdjacentElement('afterend',mark)});
/* A source badge is the primary link; do not repeat it below the article. */
document.querySelectorAll('.story').forEach(story=>{
 const links=[...story.querySelectorAll('.story-bottom .source-links a')];
 const mark=story.querySelector('.source-mark');
 const primary=links[0];
 if(mark&&primary){
   const a=document.createElement('a');a.href=primary.href;a.target='_blank';a.rel='noopener noreferrer';a.setAttribute('aria-label','阅读原始报道：'+primary.textContent.trim());
   while(mark.firstChild)a.append(mark.firstChild);
   const arrow=document.createElementNS('http://www.w3.org/2000/svg','svg');arrow.setAttribute('class','ui-icon source-arrow');arrow.setAttribute('viewBox','0 0 24 24');arrow.setAttribute('aria-hidden','true');
   const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M7 17 17 7M8 7h9v9');arrow.append(path);a.append(arrow);mark.append(a);
 }
 const group=story.querySelector('.story-bottom .source-links');
 if(group){if(links.length>1){links[0].remove();group.classList.add('has-additional');const label=group.querySelector('span');if(label)label.textContent='其他参考报道：'}else group.remove()}
 story.querySelectorAll('figure figcaption').forEach(c=>{if(/^图片来源：/.test(c.textContent.trim()))c.remove()});
});
const feedbackDialog=document.querySelector('#feedback-dialog');document.querySelector('.feedback-link')?.addEventListener('click',()=>feedbackDialog.showModal());feedbackDialog.querySelector('.feedback-close').addEventListener('click',()=>feedbackDialog.close());feedbackDialog.addEventListener('click',e=>{if(e.target===feedbackDialog)feedbackDialog.close()});document.querySelector('#feedback-form').addEventListener('submit',e=>{e.preventDefault();const form=e.currentTarget;if(!form.reportValidity())return;const kind=form.elements.kind.value;const detail=form.elements.detail.value.trim();if(!detail)return;const title='['+kind+'] '+detail.split('\n')[0].slice(0,55);const body='### 反馈类型\n'+kind+'\n\n### 反馈内容\n'+detail+'\n\n### 网站\nhttps://the-daily-noise.pages.dev/';const url='https://github.com/der035/daily-news-rss/issues/new?title='+encodeURIComponent(title)+'&body='+encodeURIComponent(body);window.open(url,'_blank','noopener,noreferrer')});
const rail=document.querySelector('.category-rail'),tabs=[...document.querySelectorAll('.category-nav button')];
const panels=[...rail.querySelectorAll('.category-panel')];let currentPanel=0;
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
function syncHeight(){rail.style.height='auto';if(rail.scrollLeft)rail.scrollLeft=0}
function goToPanel(index,smooth){
  const i=Math.max(0,Math.min(panels.length-1,index));
  currentPanel=i;
  panels.forEach((panel,j)=>{panel.hidden=j!==i;panel.setAttribute('aria-hidden',String(j!==i));});
  tabs.forEach((button,j)=>{button.setAttribute('aria-selected',String(j===i));button.tabIndex=j===i?0:-1;});
  syncHeight();
}
goToPanel(0,false);
tabs.forEach((button,i)=>{
  button.addEventListener('click',()=>{
    goToPanel(i,false);
    const top=document.querySelector('.category-nav').getBoundingClientRect().top;
    if(top<0)window.scrollTo({top:window.scrollY+top-12,behavior:reducedMotion.matches?'instant':'smooth'});
  });
  button.addEventListener('keydown',event=>{
    if(event.key==='ArrowRight'||event.key==='ArrowLeft'){
      event.preventDefault();
      const next=(i+(event.key==='ArrowRight'?1:panels.length-1))%panels.length;
      tabs[next].focus();goToPanel(next,false);
    }
  });
});
let touchStart=null;
rail.addEventListener('touchstart',event=>{
  if(event.touches.length!==1){touchStart=null;return}
  const target=event.target;
  if(target.closest('button,a,input,textarea,select,[role="dialog"],.term')){touchStart=null;return}
  const t=event.touches[0];
  touchStart={x:t.clientX,y:t.clientY};
},{passive:true});
rail.addEventListener('touchend',event=>{
  if(!touchStart||event.changedTouches.length!==1)return;
  const t=event.changedTouches[0],dx=t.clientX-touchStart.x,dy=t.clientY-touchStart.y;
  touchStart=null;
  if(Math.abs(dx)>65&&Math.abs(dx)>Math.abs(dy)*1.5){
    goToPanel(currentPanel+(dx<0?1:-1),false);
  }
},{passive:true});
rail.addEventListener('touchcancel',()=>{touchStart=null},{passive:true});

const tocDialog=document.querySelector('#toc-dialog');const tocList=tocDialog.querySelector('.toc-list');const tocGroups=[...document.querySelectorAll('.category-panel')];const tocNames=['国内新闻','国际政治','娱乐文化','消费科技','Apple'];tocGroups.forEach((panel,categoryIndex)=>{const stories=[...panel.querySelectorAll('.story')];if(!stories.length)return;const group=document.createElement('section');group.className='toc-group';const heading=document.createElement('h3');heading.textContent=tocNames[categoryIndex];group.append(heading);stories.forEach(story=>{const button=document.createElement('button');button.type='button';button.className='toc-item';button.textContent=story.querySelector('h2')?.textContent||'新闻';button.addEventListener('click',()=>{pendingTocJump={category:categoryIndex,story};closeToc()});group.append(button)});tocList.append(group)});let tocLockedY=0,pendingTocJump=null;function openToc(){tocLockedY=window.scrollY;document.body.style.position='fixed';document.body.style.top=-tocLockedY+'px';document.body.style.left='0';document.body.style.right='0';document.body.style.width='100%';tocDialog.showModal()}function closeToc(){tocDialog.close()}tocDialog.addEventListener('close',()=>{document.body.style.position='';document.body.style.top='';document.body.style.left='';document.body.style.right='';document.body.style.width='';window.scrollTo(0,tocLockedY);if(pendingTocJump){const jump=pendingTocJump;pendingTocJump=null;requestAnimationFrame(()=>{goToPanel(jump.category,false);requestAnimationFrame(()=>requestAnimationFrame(()=>jump.story.scrollIntoView({behavior:reducedMotion.matches?'instant':'smooth',block:'start'})))})}});document.querySelector('.toc-open').addEventListener('click',openToc);tocDialog.querySelector('.toc-close').addEventListener('click',closeToc);tocDialog.addEventListener('click',e=>{if(e.target===tocDialog)closeToc()});
const resizeObserver=new ResizeObserver(()=>syncHeight());panels.forEach(p=>resizeObserver.observe(p));
window.addEventListener('load',()=>{goToPanel(currentPanel,false)});
syncHeight();
addEventListener('resize',syncHeight);

const podcastToggle=document.getElementById('podcast-toggle');
const podcastPanel=document.getElementById('home-podcast');
const podcastAudio=document.getElementById('home-podcast-audio');
const podcastStatus=document.getElementById('home-podcast-status');
if(podcastToggle&&podcastPanel&&podcastAudio){
 podcastToggle.addEventListener('click',async()=>{
  const opening=podcastPanel.hidden;
  podcastPanel.hidden=!opening;
  podcastToggle.setAttribute('aria-expanded',String(opening));
  if(!opening){podcastAudio.pause();return}
  if(podcastAudio.getAttribute('src'))return;
  try{
   podcastStatus.textContent='正在载入播客…';
   const response=await fetch('./podcast/latest.json',{cache:'no-store'});
   if(!response.ok)throw Error('节目资料暂不可用');
   const data=await response.json();
   if(data.status!=='audio_ready'||!/^podcast\/[a-f0-9]{16}\.mp3$/.test(data.audio_url||''))throw Error('音频尚未准备好');
   podcastAudio.src='./'+data.audio_url;
   podcastStatus.textContent=data.date+' · 播客已就绪，点击下方播放';
  }catch(error){podcastStatus.textContent='加载失败：'+error.message}
 });
}
})();"""
    page = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="theme-color" content="#0639f5"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="DAILY NOISE"><link rel="icon" type="image/svg+xml" href="icon.svg"><link rel="apple-touch-icon" href="apple-touch-icon.png"><title>THE DAILY NOISE — ' + date + '</title>'
            '<link rel="alternate" type="application/rss+xml" href="feed.xml"><style>' + style + '</style></head>'
            '<body><main class="paper">'
            '<header><span class="header-actions"><button class="theme-toggle" type="button" aria-label="切换到午夜模式">午夜模式</button><button class="audio-entry" id="podcast-toggle" type="button" aria-expanded="false" aria-controls="home-podcast">▶ 今日播客</button></span><span>独立中文新闻简报</span></header>'
            '<section id="home-podcast" class="home-podcast" hidden><div class="home-podcast-heading"><strong>THE DAILY NOISE / PODCAST</strong><span id="home-podcast-status">正在检查今日节目…</span></div><audio id="home-podcast-audio" controls preload="metadata" playsinline style="width:100%" aria-label="每日新闻播客"></audio></section>'
            '<div class="masthead"><div class="masthead-brand"><span class="masthead-name">THE DAILY <em>NOISE.</em></span><span class="masthead-date">' + date + '</span></div><button type="button" class="toc-open" aria-haspopup="dialog" aria-controls="toc-dialog">文章目录</button></div>'
            '<nav class="category-nav" role="tablist" aria-label="新闻栏目">'
            '<button id="tab-0" role="tab" aria-controls="panel-0" aria-selected="true" type="button"><span class="nav-mark nav-domestic" aria-hidden="true"></span><span class="nav-label">国内新闻</span></button>'
            '<button id="tab-1" role="tab" aria-controls="panel-1" aria-selected="false" type="button" tabindex="-1"><span class="nav-mark nav-world" aria-hidden="true"><span></span></span><span class="nav-label">国际政治</span></button>'
            '<button id="tab-2" role="tab" aria-controls="panel-2" aria-selected="false" type="button" tabindex="-1"><span class="nav-mark nav-culture" aria-hidden="true"><span></span></span><span class="nav-label">娱乐文化</span></button>'
            '<button id="tab-3" role="tab" aria-controls="panel-3" aria-selected="false" type="button" tabindex="-1"><span class="nav-mark nav-tech" aria-hidden="true"><span></span></span><span class="nav-label">消费科技</span></button><button id="tab-4" role="tab" aria-controls="panel-4" aria-selected="false" type="button" tabindex="-1" aria-label="Apple 专题"><span class="nav-label">APPLE</span></button></nav>'
            '<div class="category-rail">' + sections + '</div>' +
            '<footer class="site-footer"><div class="footer-main"><span>THE DAILY NOISE · 新闻事实请以原始报道为准</span><button class="feedback-link" type="button">反馈与建议</button></div><div class="footer-signature"><span>EDITED &amp; BUILT BY <strong>AA</strong></span><span class="footer-version">VERSION ' + version + '</span></div><div class="footer-update">每日北京时间 08:00 更新（成功生成时）</div></footer>'
            '</main><dialog id="feedback-dialog" class="feedback-dialog" aria-labelledby="feedback-title"><form class="feedback-inner" id="feedback-form"><div class="feedback-head"><h2 id="feedback-title">反馈与建议</h2><button type="button" class="feedback-close" aria-label="关闭反馈">×</button></div><label>反馈类型<select name="kind"><option>内容纠错</option><option>阅读体验</option><option>功能建议</option><option>其他</option></select></label><label>具体内容<textarea name="detail" required maxlength="2500" placeholder="请描述问题或建议，涉及新闻时可附上标题。"></textarea></label><p class="feedback-note">点击下方按钮会前往 GitHub 创建反馈单，需要 GitHub 账号登录并确认提交。本站不会在这一步自动收集或发送文字，请勿填写个人敏感信息。</p><button class="feedback-send" type="submit">前往 GitHub 提交反馈 ↗</button></form></dialog><dialog id="toc-dialog" class="toc-dialog" aria-labelledby="toc-title"><div class="toc-inner"><div class="toc-head"><h2 id="toc-title">跳转到文章</h2><button type="button" class="toc-close" aria-label="关闭目录">×</button></div><div class="toc-list"></div></div></dialog><dialog id="term-dialog" class="term-dialog" aria-labelledby="term-title"><div class="term-dialog-inner"><div class="term-dialog-head"><h2 id="term-title"></h2><button class="term-close" type="button" aria-label="关闭解释">×</button></div><p id="term-definition"></p><p class="term-hint">术语速解 · 点击外部或按 Esc 关闭</p></div></dialog><script>' + script + '</script></body></html>')
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    for tag, value in (("title", "THE DAILY NOISE · 世界每天都很吵"), ("link", BASE), ("description", "国内新闻、国际政治、娱乐文化与消费科技中文新闻简报"), ("language", "zh-CN"), ("lastBuildDate", email.utils.format_datetime(now))):
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

def next_version():
    """Advance the patch version from the last published HTML edition."""
    page = DOCS / "index.html"
    previous = page.read_text(encoding="utf-8") if page.exists() else ""
    match = re.search(r'class="footer-version">VERSION (\d+)\.(\d+)\.(\d+)', previous)
    if not match:
        return "1.5.1"  # First release after the original v1.5.0 footer.
    major, minor, patch = map(int, match.groups())
    return f"{major}.{minor}.{patch + 1}"

def main():
    items = collect()
    print("Recent sourced items:", len(items))
    articles = generate(enrich(items))
    if len(articles) != len(CATEGORIES) * STORIES_PER_CATEGORY:
        raise ValueError("Incomplete edition: expected " + str(len(CATEGORIES) * STORIES_PER_CATEGORY) + " stories")
    version = next_version()
    render(articles, version)
    print("Published articles:", len(articles), "version:", version)

if __name__ == "__main__":
    main()
