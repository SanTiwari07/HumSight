"""Places each scene's narration WAV at its start time and writes one loudness-normalised narration.wav."""
import json, subprocess

T = json.loads(open("timing.js", encoding="utf-8").read()[len("window.TIMING = "):].rstrip().rstrip(";"))
args, filt, labels = ["ffmpeg", "-y", "-loglevel", "error"], [], []
for i, s in enumerate(T["scenes"]):
    args += ["-i", f"vo/{s['id']}.wav"]
    ms = int(round((s["start"] + s["voStart"]) * 1000))
    filt.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=mono,adelay={ms}[a{i}]")
    labels.append(f"[a{i}]")
filt.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,apad=whole_dur={T['total']},"
            f"atrim=0:{T['total']},loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[out]")
args += ["-filter_complex", ";".join(filt), "-map", "[out]", "-ac", "2", "-ar", "48000", "narration.wav"]
subprocess.check_call(args)
print("narration.wav", T["total"], "s")
