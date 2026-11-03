"""
Builds ONE video per run: the first story in stories.json that is not listed in done.txt.
Set env ALL=1 to build every pending story (useful on Colab).
Output: videos/<id>/small.mp4 (under 5 MB, fits Make.com free plan), final.mp4 (full size),
        thumbnail.jpg, meta.json
Needs: ffmpeg, fonts-noto-core, pip packages edge-tts and requests.
"""
import asyncio, json, os, subprocess, time, urllib.parse
import requests, edge_tts

VOICE = "hi-IN-SwaraNeural"   # male option: hi-IN-MadhurNeural
STYLE = ("cute 2D cartoon for small children, bright happy colors, flat vector "
         "illustration, soft rounded shapes, simple background, no text")
CHARS = ("Bruno is a chubby brown bear with a cream belly. "
         "Zig is a small green frog with big round eyes.")
SUB_STYLE = "FontName=Noto Sans Devanagari,FontSize=20,Bold=1,Outline=2,Shadow=1,MarginV=28"
MAX_MB = 4.4   # keep under Make.com free plan's 5 MB file limit

def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(" ".join(cmd[:3]) + "\n" + r.stderr[-1500:])

def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())

def get_image(prompt, seed, path):
    full = f"{STYLE}. {CHARS} Scene: {prompt}"
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(full)
           + f"?width=1280&height=720&seed={seed}&nologo=true")
    for attempt in range(6):
        try:
            r = requests.get(url, timeout=120)
            if r.status_code == 200 and len(r.content) > 5000:
                open(path, "wb").write(r.content)
                return
        except Exception:
            pass
        time.sleep(6 * (attempt + 1))
    raise RuntimeError("Image download failed for: " + prompt)

async def make_voice(text, path):
    await edge_tts.Communicate(text, VOICE, rate="-8%", pitch="+4Hz").save(path)

def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def make_video(story):
    out = os.path.join("videos", story["id"])
    os.makedirs(out, exist_ok=True)
    clips, srt, t = [], [], 0.0
    for i, sc in enumerate(story["scenes"], 1):
        img, aud, clip = f"s{i}.jpg", f"s{i}.mp3", f"c{i}.mp4"
        get_image(sc["img"], 1000 + i, os.path.join(out, img))
        asyncio.run(make_voice(sc["hi"], os.path.join(out, aud)))
        d = duration(os.path.join(out, aud)) + 0.6
        run(["ffmpeg", "-y", "-i", img, "-i", aud, "-t", f"{d:.2f}",
             "-vf", f"scale=1920:1080,zoompan=z='min(zoom+0.0006,1.15)':d={int(d*25)}:s=1280x720:fps=25,format=yuv420p",
             "-af", "apad", "-c:v", "libx264", "-c:a", "aac", "-ar", "44100", "-ac", "2",
             "-shortest", clip], cwd=out)
        clips.append(clip)
        srt.append(f"{i}\n{srt_time(t)} --> {srt_time(t + d - 0.1)}\n{sc['hi']}\n")
        t += d
    open(os.path.join(out, "subs.srt"), "w", encoding="utf-8").write("\n".join(srt))
    open(os.path.join(out, "list.txt"), "w").write("".join(f"file '{c}'\n" for c in clips))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "all.mp4"], cwd=out)
    # full quality
    run(["ffmpeg", "-y", "-i", "all.mp4", "-vf", f"subtitles=subs.srt:force_style='{SUB_STYLE}'",
         "-c:a", "copy", "final.mp4"], cwd=out)
    # small version for Make.com free plan (5 MB limit)
    audio_k = 40
    vk = max(40, int(MAX_MB * 8 * 1024 * 1024 / t / 1000) - audio_k)
    run(["ffmpeg", "-y", "-i", "all.mp4", "-vf",
         f"scale=640:360,subtitles=subs.srt:force_style='{SUB_STYLE}'",
         "-c:v", "libx264", "-b:v", f"{vk}k", "-maxrate", f"{vk}k", "-bufsize", f"{2*vk}k",
         "-preset", "slow", "-c:a", "aac", "-b:a", f"{audio_k}k", "-ac", "1", "small.mp4"], cwd=out)
    mb = os.path.getsize(os.path.join(out, "small.mp4")) / 1024 / 1024
    print(f"{story['id']}: small.mp4 = {mb:.1f} MB, length {t:.0f}s")
    run(["cp", "s1.jpg", "thumbnail.jpg"], cwd=out)
    desc = (story["title"] + "\n\nA funny Hindi cartoon story for kids with Bruno the bear "
            "and Zig the frog.\n\n#हिंदीकहानी #kidsstories #cartoon")
    json.dump({"title": story["title"], "description": desc},
              open(os.path.join(out, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False)

def main():
    stories = json.load(open("stories.json", encoding="utf-8"))
    done = set(open("done.txt").read().split()) if os.path.exists("done.txt") else set()
    todo = [s for s in stories if s["id"] not in done]
    if not todo:
        print("No pending stories. Add more to stories.json.")
        return
    if not os.environ.get("ALL"):
        todo = todo[:1]
    for s in todo:
        make_video(s)
        gh = os.environ.get("GITHUB_OUTPUT")
        if gh:
            open(gh, "a").write(f"story_id={s['id']}\n")

main()
