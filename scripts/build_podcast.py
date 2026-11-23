#!/usr/bin/env python3
"""Create a source-faithful Chinese audio briefing transcript from the published RSS.

No model improvisation: all substantive statements come from published article descriptions.
Optionally synthesize MP3 via Azure Speech when explicit credentials are provided.
"""
import datetime as dt
import email.utils
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT/"docs"
OUT=DOCS/"podcast"
CATEGORIES=("国内新闻","国际政治","娱乐文化","消费科技","Apple")
def build():
    root=ET.parse(DOCS/"feed.xml").getroot()
    channel=root.find("channel")
    items=channel.findall("item")
    if len(items)!=25:
        raise ValueError("Refusing incomplete edition: expected 25 articles")
    stamp=email.utils.parsedate_to_datetime(channel.findtext("lastBuildDate"))
    date=stamp.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    segments=[]
    segments.append({"type":"opening","text":f"欢迎收听每日噪音。今天是{date}。接下来为你梳理今天的重要新闻。"})
    sources=[]
    for i,item in enumerate(items):
        title=(item.findtext("title") or "").strip()
        desc=(item.findtext("description") or "").strip()
        url=(item.findtext("link") or "").strip()
        if not title or not desc or not url.startswith("https://"):
            raise ValueError(f"Invalid article {i+1}")
        category=CATEGORIES[i//5]
        if i%5==0:
            segments.append({"type":"category","text":f"下面是{category}。"})
        # No LLM rewriting: preserve source-grounded summary and background verbatim.
        desc=re.sub(r"\n来源：[^\n]*$","",desc).replace("来龙去脉：","背景与影响：")
        desc=re.sub(r"\s+"," ",desc).strip()
        segments.append({"type":"story","category":category,"title":title,"source_url":url,"text":title+"。"+desc})
        sources.append({"title":title,"url":url,"category":category})
    segments.append({"type":"closing","text":"以上是今天的新闻简报。详细报道与原始来源，请在每日噪音网站查看。感谢收听。"})
    transcript="\n\n".join(x["text"] for x in segments)
    digest=hashlib.sha256((date+"\n"+transcript).encode()).hexdigest()[:16]
    return {"date":date,"edition_id":digest,"status":"transcript_ready","title":f"THE DAILY NOISE · {date}","segments":segments,"sources":sources,"transcript":transcript}

def synthesize(data):
    key=os.getenv("AZURE_SPEECH_KEY","").strip()
    region=os.getenv("AZURE_SPEECH_REGION","").strip()
    if not key or not region:
        print("No Azure Speech credentials; transcript only.")
        return
    if not re.fullmatch(r"[a-z0-9-]+",region):
        raise ValueError("Invalid Azure Speech region")
    voice=os.getenv("AZURE_SPEECH_VOICE","zh-CN-XiaoxiaoNeural")
    if not re.fullmatch(r"[a-zA-Z0-9-]+",voice):
        raise ValueError("Invalid voice name")
    # Azure TTS REST accepts bounded SSML; synthesize small segments separately.
    pieces=[]
    for segment in data["segments"]:
        text=segment["text"]
        for j in range(0,len(text),650):
            chunk=text[j:j+650]
            ssml=f'<speak version="1.0" xml:lang="zh-CN"><voice name="{voice}">{escape(chunk)}</voice></speak>'
            req=urllib.request.Request(
                f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
                data=ssml.encode("utf-8"),
                headers={"Ocp-Apim-Subscription-Key":key,"Content-Type":"application/ssml+xml","X-Microsoft-OutputFormat":"audio-16khz-128kbitrate-mono-mp3","User-Agent":"DailyNoise/1.0"},
                method="POST")
            with urllib.request.urlopen(req,timeout=45) as resp:
                if resp.headers.get("Content-Type","").split(";")[0]!="audio/mpeg":
                    raise ValueError("TTS response was not MPEG audio")
                part=resp.read(5_000_001)
                if len(part)>5_000_000 or len(part)<100:
                    raise ValueError("Invalid TTS segment size")
                pieces.append(part)
    # MP3 frame streams may be concatenated for sequential playback.
    mp3=b"".join(pieces)
    if len(mp3)>24_000_000:
        raise ValueError("Audio too large for repository publication")
    (OUT/(data["edition_id"]+".mp3")).write_bytes(mp3)
    data["audio_url"]="podcast/"+data["edition_id"]+".mp3"
    data["status"]="audio_ready"

def main():
    data=build()
    OUT.mkdir(exist_ok=True)
    synthesize(data)
    (OUT/"latest.json").write_text(json.dumps({k:v for k,v in data.items() if k!="transcript"},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT/"latest.txt").write_text(data["transcript"]+"\n",encoding="utf-8")
    print("Podcast prepared:",data["date"],data["edition_id"],data["status"],len(data["segments"]),"segments")

if __name__=="__main__":
    main()
