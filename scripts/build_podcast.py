#!/usr/bin/env python3
"""Create a source-faithful Chinese audio briefing transcript from the published RSS.

No model improvisation: all substantive statements come from published article descriptions.
Optionally synthesize MP3 via Alibaba Cloud CosyVoice when credentials are provided.
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
        # Audio edition: two lead stories per category, with bounded narration.
        if i%5 < 2:
            segments.append({"type":"story","category":category,"title":title,"source_url":url,"text":title+"。"+desc[:360]})
        sources.append({"title":title,"url":url,"category":category})
    segments.append({"type":"closing","text":"以上是今天的新闻简报。详细报道与原始来源，请在每日噪音网站查看。感谢收听。"})
    total_chars=sum(len(x["text"]) for x in segments)
    if total_chars > 5500:
        raise ValueError(f"Podcast exceeds 5500-character budget: {total_chars}")
    print(f"Podcast character budget: {total_chars}/5500; {len(segments)} segments")
    transcript="\n\n".join(x["text"] for x in segments)
    digest=hashlib.sha256((date+"\n"+transcript).encode()).hexdigest()[:16]
    return {"date":date,"edition_id":digest,"status":"transcript_ready","title":f"THE DAILY NOISE · {date}","segments":segments,"sources":sources,"transcript":transcript}

def synthesize(data):
    """Use Alibaba Cloud Model Studio CosyVoice only when explicitly configured."""
    key=os.getenv("DASHSCOPE_API_KEY","").strip()
    workspace=os.getenv("DASHSCOPE_WORKSPACE_ID","").strip()
    if not key or not workspace:
        print("Alibaba Cloud CosyVoice not configured; transcript only.")
        return
    if not re.fullmatch(r"[a-zA-Z0-9_-]{4,128}",workspace):
        raise ValueError("Invalid DashScope workspace ID")
    model=os.getenv("DASHSCOPE_TTS_MODEL","cosyvoice-v3-flash")
    if model not in {"cosyvoice-v3-flash","cosyvoice-v3-plus"}:
        raise ValueError("Unsupported CosyVoice model")
    voice=os.getenv("DASHSCOPE_TTS_VOICE","longanyang")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{3,80}",voice):
        raise ValueError("Invalid CosyVoice voice")
    try:
        import dashscope
    except ImportError as exc:
        raise RuntimeError("Install dashscope>=2.0.1 to synthesize audio") from exc
    client=dashscope.Client(api_key=key,workspace=workspace,region="cn-beijing")
    # The official SDK supports 20k characters per call. Each story is
    # synthesized separately for reliable retries and source traceability.
    audio_parts=[]
    import time
    started=time.monotonic()
    for index,segment in enumerate(data["segments"]):
        if time.monotonic()-started > 600:
            raise TimeoutError("Podcast TTS exceeded 10-minute budget; stopping additional calls")
        text=segment["text"]
        print(f"Synthesizing segment {index+1}/{len(data['segments'])}: {len(text)} chars",flush=True)
        if len(text)>20000:
            raise ValueError("TTS segment exceeds official 20000-character limit")
        part=client.audio.tts.synthesize(text,model=model,voice=voice)
        if not isinstance(part,bytes) or not part.startswith((b"ID3",b"\xff\xfb",b"\xff\xf3",b"\xff\xf2")):
            raise ValueError("CosyVoice returned invalid MP3 bytes")
        audio_parts.append(part)
    # MP3 streams can be joined, but frame and duration correctness must be
    # verified with ffprobe before making the output public.
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        files=[]
        for i,part in enumerate(audio_parts):
            p=Path(tmp)/f"segment_{i:03d}.mp3"
            p.write_bytes(part)
            files.append(p)
        concat=Path(tmp)/"concat.txt"
        concat.write_text("".join(f"file '{p}'\n" for p in files),encoding="utf-8")
        target=OUT/(data["edition_id"]+".mp3")
        subprocess.run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-f","concat","-safe","0","-i",str(concat),"-c","copy","-y",str(target)],check=True,timeout=180)
        if target.stat().st_size>24_000_000 or target.stat().st_size<1000:
            target.unlink(missing_ok=True)
            raise ValueError("MP3 file size outside supported limits")
        subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1",str(target)],check=True,capture_output=True,timeout=30)
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
