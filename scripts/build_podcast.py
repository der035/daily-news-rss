#!/usr/bin/env python3
"""Create a source-faithful Chinese audio briefing transcript from the published RSS.

No model improvisation: all substantive statements come from published article descriptions.
Optionally synthesize MP3 via Alibaba Cloud CosyVoice when credentials are provided.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
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
VOICE_CONFIG=ROOT/"scripts"/"cosyvoice-v3.5-flash.voice"
CATEGORIES=("国内新闻","国际政治","娱乐文化","消费科技","Apple")
def spoken_summary(description, limit=190):
    """Use only complete source-grounded sentences."""
    description=re.sub(r"\n来源：[^\n]*$", "", description)
    description=re.sub(r"^(?:来龙去脉|背景与影响|摘要)[:：]\s*", "", description.strip())
    description=re.sub(r"\s+", " ", description).strip()
    sentences=re.split(r"(?<=[。！？!?])\s*", description)
    chosen=[]
    for sentence in sentences:
        if not sentence:
            continue
        if len("".join(chosen))+len(sentence)>limit:
            break
        chosen.append(sentence)
    if not chosen:
        match=re.search(r"^.*?[。！？!?]", description)
        if not match:
            raise ValueError("Article has no complete sentence for narration")
        chosen=[match.group(0)]
    return "".join(chosen)

def build():
    root=ET.parse(DOCS/"feed.xml").getroot()
    channel=root.find("channel")
    items=channel.findall("item")
    if len(items)!=25:
        raise ValueError("Refusing incomplete edition: expected 25 articles")
    stamp=email.utils.parsedate_to_datetime(channel.findtext("lastBuildDate"))
    date=stamp.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    segments=[{"type":"opening","text":f"欢迎收听每日噪音。今天是{date}。咱们来看看今天有哪些值得关注的事。"}]
    sources=[]
    for i,item in enumerate(items):
        title=(item.findtext("title") or "").strip()
        desc=(item.findtext("description") or "").strip()
        url=(item.findtext("link") or "").strip()
        if not title or not desc or not url.startswith("https://"):
            raise ValueError(f"Invalid article {i+1}")
        category=CATEGORIES[i//5]
        spoken=spoken_summary(desc)
        intro="先说" if i%5==0 else "再来看"
        segments.append({"type":"story","article_index":i,"category":category,"title":title,"source_url":url,"text":f"{intro}这条。{title}。{spoken}"})
        sources.append({"title":title,"url":url,"category":category})
    segments.append({"type":"closing","text":"以上就是今天的每日噪音。想看更完整的报道和来源，可以打开网站。明天见。"})
    total_chars=sum(len(x["text"]) for x in segments)
    if total_chars > 7000:
        raise ValueError(f"Podcast exceeds 7000-character budget: {total_chars}")
    print(f"Podcast character budget: {total_chars}/7000; {len(segments)} segments")
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
    if model not in {"cosyvoice-v3-flash","cosyvoice-v3-plus","cosyvoice-v3.5-flash"}:
        raise ValueError("Unsupported CosyVoice model")
    voice=os.getenv("DASHSCOPE_TTS_VOICE","").strip()
    if model=="cosyvoice-v3.5-flash":
        if not voice and VOICE_CONFIG.exists():
            voice=VOICE_CONFIG.read_text(encoding="utf-8").strip()
    else:
        voice=voice or "longanyang"
    if voice and not re.fullmatch(r"[a-zA-Z0-9_.-]{3,128}",voice):
        raise ValueError("Invalid CosyVoice voice")
    try:
        import dashscope
    except ImportError as exc:
        raise RuntimeError("Install dashscope>=2.0.1 to synthesize audio") from exc
    # Use a separate SDK client per worker; shared client thread safety is unknown.
    # Preserve segment order when collecting futures, regardless of completion order.
    import time
    import random
    started=time.monotonic()
    segments=data["segments"]
    workers=int(os.getenv("PODCAST_TTS_WORKERS","4"))
    if not 1 <= workers <= 6:
        raise ValueError("PODCAST_TTS_WORKERS must be between 1 and 6")
    if model=="cosyvoice-v3.5-flash":
        if not voice:
            client=dashscope.Client(api_key=key,workspace=workspace,region="cn-beijing")
            voice=client.audio.voice_design.create(
                target_model=model,
                voice_prompt="青年男性新闻播音员，普通话吐字清晰，音调适中，语速平稳，读英文品牌名时自然，像在给朋友讲新闻。",
                preview_text="欢迎收听每日噪音。今天我们关注国际新闻、文化和科技。",
                prefix="dailynews",
                language_hints=["zh"],
            ).voice_id
            if not voice.startswith(model+"-vd-"):
                raise ValueError("Unexpected voice ID for CosyVoice 3.5 Flash")
            VOICE_CONFIG.write_text(voice+"\n",encoding="utf-8")
        if not voice.startswith(model+"-"):
            raise ValueError("CosyVoice 3.5 Flash requires a custom voice bound to this model")
        # Keep previously published audio URLs intact when regenerating an edition.
        edition_key=f"{data['edition_id']}:{model}:{voice}"
        data["edition_id"]=hashlib.sha256(edition_key.encode()).hexdigest()[:16]

    import unicodedata
    billed_chars=sum(
        1+unicodedata.name(char,"").startswith(("CJK UNIFIED IDEOGRAPH","CJK COMPATIBILITY IDEOGRAPH"))
        for segment in segments for char in segment["text"]
    )
    print(f"TTS model: {model}; estimated billable characters for one pass: {billed_chars}",flush=True)

    def generate(index, segment):
        content=segment["text"]
        if len(content)>20000:
            raise ValueError("TTS segment exceeds official 20000-character limit")
        client=dashscope.Client(api_key=key,workspace=workspace,region="cn-beijing")
        for attempt in range(4):
            if time.monotonic()-started > 1500:
                raise TimeoutError("Podcast TTS exceeded 25-minute budget")
            try:
                print(f"Synthesizing segment {index+1}/{len(segments)} (attempt {attempt+1}): {len(content)} chars",flush=True)
                part=client.audio.tts.synthesize(content,model=model,voice=voice)
                if not isinstance(part,bytes) or not part.startswith((b"ID3",b"\xff\xfb",b"\xff\xf3",b"\xff\xf2")):
                    raise ValueError("CosyVoice returned invalid MP3 bytes")
                return index,part
            except Exception as exc:
                if attempt==3:
                    raise
                delay=min(2**attempt*3+random.uniform(0,2),20)
                print(f"TTS segment {index+1} failed ({type(exc).__name__}); retry in {delay:.1f}s",flush=True)
                time.sleep(delay)
    audio_parts=[None]*len(segments)
    print(f"Concurrent TTS: {workers} workers, {len(segments)} segments",flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(generate,i,segment) for i,segment in enumerate(segments)]
        for future in as_completed(futures):
            index,part=future.result()
            audio_parts[index]=part
            print(f"Completed segment {index+1}/{len(segments)}",flush=True)
    story_audio={segment["article_index"]:audio_parts[i] for i,segment in enumerate(segments) if segment["type"]=="story"}
    # MP3 streams can be joined, but frame and duration correctness must be
    # verified with ffprobe before making the output public.
    import subprocess
    import tempfile
    edition_dir=OUT/data['edition_id']
    edition_dir.mkdir(parents=True,exist_ok=True)
    for article_index,part in story_audio.items():
        (edition_dir/f'article-{article_index+1:02d}.mp3').write_bytes(part)
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
    data["article_audio"]={str(i):f"podcast/{data['edition_id']}/article-{i+1:02d}.mp3" for i in story_audio}
    data["status"]="audio_ready"
    data["tts_model"]=model
    print(f"TTS and MP3 assembly completed in {time.monotonic()-started:.1f}s",flush=True)

def main():
    data=build()
    OUT.mkdir(exist_ok=True)
    synthesize(data)
    (OUT/"latest.json").write_text(json.dumps({k:v for k,v in data.items() if k!="transcript"},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT/"latest.txt").write_text(data["transcript"]+"\n",encoding="utf-8")
    print("Podcast prepared:",data["date"],data["edition_id"],data["status"],len(data["segments"]),"segments")

if __name__=="__main__":
    main()
