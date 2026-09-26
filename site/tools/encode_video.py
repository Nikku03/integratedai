"""
Encode a clip for the site: WebM (VP9) + MP4 (H.264), a 4:5 phone crop, and posters.

    python3 tools/encode_video.py CLIP.mp4 NAME --scrub [--start 0 --length 12]
    python3 tools/encode_video.py CLIP.mp4 NAME --loop  [--start 2 --length 8]

--scrub  for the walk-in clips that play as you scroll: a keyframe every 8 frames at 24fps,
         so jumping to any point is instant. Keep them under ~14s.
--loop   for ambient loops (muted, autoplaying): normal keyframes, 30fps, smaller files.

Writes assets/video/NAME.webm|.mp4, NAME-sm.webm|.mp4 (4:5 crop, for phones) and
assets/video/posters/NAME-poster.jpg, NAME-sm-poster.jpg. Replacing a clip that already exists
(e.g. cafe-walk) needs no page edits. Requires ffmpeg on the PATH (or FFMPEG=/path/to/ffmpeg).
"""
from __future__ import annotations
import argparse, os, subprocess
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
FF = os.environ.get("FFMPEG", "ffmpeg")
GRADE = "eq=saturation=0.9:contrast=1.03:gamma=0.98"          # the site's gentle, warm grade
CROP45 = "crop=trunc(ih*4/5/2)*2:ih:(iw-trunc(ih*4/5/2)*2)/2:0"


def run(args: list[str]) -> None:
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def encode(src: str, name: str, scrub: bool, start: float | None, length: float | None, grade: bool) -> None:
    vid, post = SITE / "assets/video", SITE / "assets/video/posters"
    post.mkdir(parents=True, exist_ok=True)
    fps, gop = (24, 8) if scrub else (30, 48)
    crf264, crfvp9 = (28, 39) if scrub else (27, 37)
    base = GRADE if grade else "null"
    trim = (["-ss", str(start)] if start is not None else []) + ["-i", src] + (["-t", str(length)] if length else [])
    for suffix, chain in (("", f"{base},scale=1280:-2"), ("-sm", f"{base},{CROP45},scale=640:800")):
        out = vid / f"{name}{suffix}"
        vf = f"{chain},fps={fps},format=yuv420p"
        run(trim + ["-an", "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", str(crf264),
                    "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0", "-movflags", "+faststart", f"{out}.mp4"])
        run(trim + ["-an", "-vf", vf, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crfvp9), "-row-mt", "1",
                    "-g", str(gop), "-keyint_min", str(gop), f"{out}.webm"])
        run((["-ss", str(start)] if start is not None else []) + ["-i", src, "-frames:v", "1", "-vf", chain, "-q:v", "3",
            str(post / f"{name}{suffix}-poster.jpg")])
        print(f"  {out.name}: mp4 {out.with_suffix('.mp4').stat().st_size // 1024} KB · webm {out.with_suffix('.webm').stat().st_size // 1024} KB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip"); ap.add_argument("name")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scrub", action="store_true"); mode.add_argument("--loop", action="store_true")
    ap.add_argument("--start", type=float); ap.add_argument("--length", type=float)
    ap.add_argument("--no-grade", action="store_true", help="skip the site's colour grade")
    a = ap.parse_args()
    encode(a.clip, a.name, a.scrub, a.start, a.length, not a.no_grade)
