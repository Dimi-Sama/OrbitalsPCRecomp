"""Measure FFmpeg-compatible video decoding without writing media."""

import argparse
import json
import re
import statistics
import struct
import subprocess
import time
from fractions import Fraction
from pathlib import Path


CPU_TIMES = re.compile(r"utime=([\d.]+)s stime=([\d.]+)s rtime=([\d.]+)s")
HW_FORMATS = {"d3d11va": "d3d11", "vaapi": "vaapi", "cuda": "cuda", "vulkan": "vulkan"}
SEEK_WINDOW = 3


def bink_reference(path):
    with path.open("rb") as stream:
        header = stream.read(44)
    if len(header) != 44 or header[:3] != b"KB2":
        raise ValueError(f"{path}: expected a Bink 2 header")
    tag, size, frames, _, _, width, height, rate, scale, flags, audio_tracks = struct.unpack(
        "<4s10I", header
    )
    if size + 8 != path.stat().st_size or not all((frames, width, height, rate, scale)):
        raise ValueError(f"{path}: invalid Bink 2 header or file size")
    fps = Fraction(rate, scale)
    return {
        "tag": tag.decode("ascii"), "width": width, "height": height, "frames": frames,
        "fps": str(fps), "duration_s": float(frames / fps),
        "flags": flags, "audio_tracks": audio_tracks,
    }


def decode(command, expected_frames, first_only):
    args = command + (["-frames:v", "1"] if first_only else []) + ["-f", "null", "-"]
    start = time.perf_counter()
    result = subprocess.run(args, capture_output=True, text=True, errors="replace", check=False)
    wall_s = time.perf_counter() - start
    if result.returncode:
        raise ValueError(f"FFmpeg exited with code {result.returncode}\n{result.stderr[-4000:]}")
    progress = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    expected = 1 if first_only else expected_frames
    frames = int(progress.get("frame", "0"))
    if progress.get("progress") != "end" or frames != expected:
        raise ValueError(f"Expected {expected} frames, received {frames}\n{result.stderr[-2000:]}")
    timings = CPU_TIMES.search(result.stderr)
    if timings is None:
        raise ValueError("FFmpeg did not emit its benchmark CPU timings")
    user_s, sys_s, decode_wall_s = map(float, timings.groups())
    return {
        "wall_s": wall_s, "ffmpeg_wall_s": decode_wall_s, "cpu_s": user_s + sys_s,
        "frames": frames, "output_duration_s": int(progress["out_time_us"]) / 1_000_000,
        "frames_per_wall_s": frames / wall_s,
    }


def frame_fingerprints(ffmpeg, path, threads, fps, frame_count, *, seek=None, select=None):
    command = [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-xerror",
        "-protocol_whitelist", "file,pipe", "-threads", str(threads), "-copyts",
    ]
    if seek is not None:
        command += ["-ss", f"{float(seek / fps):.6f}"]
    command += ["-i", str(path.resolve()), "-map", "0:v:0", "-an"]
    if select is not None:
        command += ["-vf", f"select={select}"]
    command += [
        "-fps_mode", "passthrough", "-c:v", "rawvideo", "-threads:v", "1",
        "-frames:v", str(frame_count), "-f", "framehash", "-hash", "sha256", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    if result.returncode:
        raise ValueError(f"FFmpeg exited with code {result.returncode}\n{result.stderr[-2000:]}")
    time_base = None
    frames = []
    for line in result.stdout.splitlines():
        if line.startswith("#tb 0: "):
            time_base = Fraction(line.removeprefix("#tb 0: "))
        elif line and not line.startswith("#"):
            _, _, pts, duration, size, digest = (field.strip() for field in line.split(","))
            if time_base is None:
                raise ValueError("Missing time base in FFmpeg frame hashes")
            frames.append((int(pts) * time_base, int(duration) * time_base, int(size), digest))
    return frames


def validate_seek(ffmpeg, path, threads, reference):
    fps = Fraction(reference["fps"])
    total = reference["frames"]
    window = min(SEEK_WINDOW, total)
    last_start = total - window
    starts = sorted({0, min(total // 2, last_start), last_start})
    indices = sorted({frame for start in starts for frame in range(start, start + window)})
    select = "+".join(fr"eq(n\,{frame})" for frame in indices)
    sequential = frame_fingerprints(ffmpeg, path, threads, fps, len(indices), select=select)
    if len(sequential) != len(indices) or any(
        pts != frame / fps or duration != 1 / fps
        for frame, (pts, duration, _, _) in zip(indices, sequential)
    ):
        raise ValueError("Sequential decode did not match the Bink frame timestamps and durations")

    expected = dict(zip(indices, sequential))
    checks = []
    for start in starts:
        started = time.perf_counter()
        actual = frame_fingerprints(ffmpeg, path, threads, fps, window, seek=start)
        seek_ms = (time.perf_counter() - started) * 1000
        wanted = [expected[frame] for frame in range(start, start + window)]
        check = {"start_frame": start, "frames": len(actual), "match": actual == wanted, "process_ms": seek_ms}
        if not check["match"]:
            check["expected_pts_s"] = [str(pts) for pts, _, _, _ in wanted]
            check["actual_pts_s"] = [str(pts) for pts, _, _, _ in actual]
            check["matching_frame_hashes"] = sum(result[2:] == target[2:] for result, target in zip(actual, wanted))
        checks.append(check)
    return {"decoded_bytes_per_frame": sequential[0][2], "seek_windows": checks}


def validate_audio(ffmpeg, path, threads, track_count):
    command = [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-xerror",
        "-progress", "pipe:1", "-protocol_whitelist", "file,pipe", "-threads", str(threads),
        "-i", str(path.resolve()), "-vn",
    ]
    for track in range(track_count):
        command += ["-map", f"0:a:{track}"]
    command += ["-c:a", "pcm_s16le", "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    progress = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    duration_us = progress.get("out_time_us", "N/A")
    passed = (result.returncode == 0 and progress.get("progress") == "end"
              and duration_us.isdigit() and int(duration_us) > 0)
    audio = {"ok": passed, "exit_code": result.returncode}
    if duration_us.isdigit():
        audio["output_duration_s"] = int(duration_us) / 1_000_000
    if not passed:
        audio["error"] = result.stderr[-2000:] or "FFmpeg did not produce audio samples"
    return audio


def compatibility_report(ffmpeg, version, path, threads, *, seek, audio):
    paths = sorted(path.rglob("*.bk2")) if path.is_dir() else [path]
    if not paths:
        raise ValueError(f"{path}: no BK2 files found")
    clips = []
    failed = 0
    for clip in paths:
        row = {"input": str(clip.resolve())}
        try:
            row["reference"] = bink_reference(clip)
        except (OSError, ValueError) as exc:
            row["error"] = str(exc)
        else:
            if seek:
                try:
                    row.update(validate_seek(ffmpeg, clip, threads, row["reference"]))
                except (OSError, ValueError) as exc:
                    row["seek_error"] = str(exc)
            tracks = row["reference"]["audio_tracks"]
            if audio and tracks:
                row["audio_decode"] = validate_audio(ffmpeg, clip, threads, tracks)
        clips.append(row)
        clean_video = "seek_error" not in row and all(check["match"] for check in row.get("seek_windows", []))
        clean_audio = row.get("audio_decode", {}).get("ok", True)
        passed = "error" not in row and clean_video and clean_audio
        failed += not passed
    return {"ffmpeg": version, "threads": threads, "failed_clips": failed, "clips": clips}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ffmpeg", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("--reference-bk2", type=Path, help="source BK2 when testing a local transcode")
    parser.add_argument("--hwaccel", choices=HW_FORMATS)
    parser.add_argument("--threads", type=int, default=1, help="decoder thread count (0 = auto)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--seek-check", action="store_true", help=(
        "compare frames and timestamps after seeking against sequential software decoding; "
        "accepts one native BK2 file or a directory of BK2 files"
    ))
    parser.add_argument("--audio-check", action="store_true", help=(
        "try decoding every embedded audio track in one native BK2 file or a directory of BK2 files"
    ))
    args = parser.parse_args()
    if args.runs < 1 or args.threads < 0:
        parser.error("runs must be positive and threads must be nonnegative")
    if (args.seek_check or args.audio_check) and (args.hwaccel or args.reference_bk2):
        parser.error("compatibility checks require native BK2 input and software decoding")

    ffmpeg = str(args.ffmpeg.resolve())
    try:
        version = subprocess.check_output([ffmpeg, "-version"], text=True, errors="replace")
        if args.seek_check or args.audio_check:
            report = compatibility_report(ffmpeg, version.splitlines()[0], args.input, args.threads,
                                          seek=args.seek_check, audio=args.audio_check)
            print(json.dumps(report, indent=2))
            return bool(report["failed_clips"])
        reference = bink_reference(args.reference_bk2 or args.input)
        command = [
            ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-xerror", "-benchmark",
            "-progress", "pipe:1", "-protocol_whitelist", "file,pipe", "-threads", str(args.threads),
        ]
        if args.hwaccel:
            command += ["-hwaccel", args.hwaccel, "-hwaccel_output_format", HW_FORMATS[args.hwaccel]]
        command += ["-i", str(args.input.resolve()), "-map", "0:v:0", "-an", "-fps_mode", "passthrough"]
        startup = [decode(command, reference["frames"], first_only=True) for _ in range(args.runs)]
        throughput = [decode(command, reference["frames"], first_only=False) for _ in range(args.runs)]
        max_pts_error_s = float(1 / Fraction(reference["fps"]))
        for trial in throughput:
            if abs(trial["output_duration_s"] - reference["duration_s"]) > max_pts_error_s:
                raise ValueError(f"Output timestamps differ by more than one source frame: {trial}")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")

    report = {
        "ffmpeg": version.splitlines()[0], "configuration": version.splitlines(),
        "input": str(args.input.resolve()), "reference": reference, "threads": args.threads,
        "hwaccel": args.hwaccel, "first_frame": startup, "full_decode": throughput,
        "median_first_frame_process_ms": 1000 * statistics.median(r["wall_s"] for r in startup),
        "median_full_decode_wall_s": statistics.median(r["wall_s"] for r in throughput),
        "median_full_decode_cpu_s": statistics.median(r["cpu_s"] for r in throughput),
        "median_decode_fps": statistics.median(r["frames_per_wall_s"] for r in throughput),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
