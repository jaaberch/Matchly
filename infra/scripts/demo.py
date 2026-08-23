#!/usr/bin/env python3
"""Drive a whole match through a running Matchly stack.

Schedules a match, checks two players in, uploads a generated recording as the
capture agent would, queues processing on the real worker, and prints the clips
that come out. Useful for seeing the product work without a camera or a pitch.

    make demo

Requires the API and a video worker to be running, and ffmpeg on PATH to
generate the stand-in recording.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_API = "http://localhost:8000"
OPERATOR = "+212600000099"
PLAYERS = (("+212600000001", "A", 7), ("+212600000002", "B", 9))


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body=None, headers=None, raw: bytes | None = None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if raw is None and body is not None:
            request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request) as response:
                payload = response.read()
                if payload and response.headers.get("content-type", "").startswith(
                    "application/json"
                ):
                    return response.status, json.loads(payload)
                return response.status, payload
        except urllib.error.HTTPError as error:
            payload = error.read()
            try:
                return error.code, json.loads(payload)
            except json.JSONDecodeError:
                return error.code, payload

    def login(self, phone: str) -> dict[str, str]:
        _, challenge = self.call("POST", "/api/v1/auth/request-otp", {"phone": phone})
        if "dev_code" not in challenge:
            raise SystemExit(
                f"Could not sign in as {phone}: {challenge}. "
                "The mock OTP provider must be enabled (OTP_PROVIDER=mock)."
            )
        _, tokens = self.call(
            "POST", "/api/v1/auth/verify-otp", {"phone": phone, "code": challenge["dev_code"]}
        )
        return {"Authorization": f"Bearer {tokens['access_token']}"}


def die(step: str, payload) -> None:
    raise SystemExit(f"{step} failed: {json.dumps(payload, default=str)[:400]}")


def make_recording(path: Path, seconds: int) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size=640x360:rate=15",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--segments", type=int, default=2)
    parser.add_argument("--seconds", type=int, default=20, help="length of each segment")
    parser.add_argument("--timeout", type=int, default=300, help="seconds to wait for processing")
    args = parser.parse_args()

    api = Api(args.api)
    operator = api.login(OPERATOR)
    print(f"Signed in as the venue operator at {args.api}")

    status, venues = api.call("GET", "/api/v1/venues", headers=operator)
    if status != 200 or not venues.get("items"):
        die("Listing venues", venues)
    venue_id = venues["items"][0]["id"]
    _, venue = api.call("GET", f"/api/v1/venues/{venue_id}", headers=operator)
    field = venue["fields"][0]
    print(f"Venue: {venue['name']} / {field['name']}")

    # A fresh camera token: the agent's credential is shown only at attach time.
    status, camera = api.call(
        "POST", f"/api/v1/fields/{field['id']}/camera", {"name": "Demo camera"}, headers=operator
    )
    if status != 201:
        die("Attaching a camera", camera)
    agent = {"X-Camera-Token": camera["token"]}

    # Somewhere free on the calendar: one field records one match at a time.
    start = dt.datetime.now(dt.UTC) + dt.timedelta(days=random.randint(1, 500), minutes=5)
    status, match = api.call(
        "POST",
        "/api/v1/matches",
        {
            "field_id": field["id"],
            "starts_at": start.isoformat(),
            "ends_at": (start + dt.timedelta(hours=1)).isoformat(),
            "title": "Demo match",
        },
        headers=operator,
    )
    if status != 201:
        die("Creating the match", match)
    match_id = match["id"]
    print(f"Match created. Join code: {match['join_code']}")

    for phone, team, jersey in PLAYERS:
        player = api.login(phone)
        status, joined = api.call(
            "POST",
            f"/api/v1/matches/{match_id}/join",
            {"team": team, "jersey_number": jersey, "consent": True},
            headers=player,
        )
        if status != 201:
            die(f"Checking in {phone}", joined)
        print(f"  checked in: {joined['name']} — team {team}, number {jersey}")

    status, started = api.call("POST", f"/api/v1/matches/{match_id}/start", headers=operator)
    if status != 200:
        die("Starting the match", started)
    print("Recording started")

    with tempfile.TemporaryDirectory(prefix="matchly-demo-") as tmp:
        for index in range(args.segments):
            clip = make_recording(Path(tmp) / f"segment-{index}.mp4", args.seconds)
            status, target = api.call(
                "POST",
                f"/api/v1/matches/{match_id}/video",
                {"kind": "segment", "segment_index": index},
                headers=agent,
            )
            if status != 200:
                die("Requesting an upload target", target)

            body = clip.read_bytes()
            upload = urllib.request.Request(target["upload_url"], data=body, method="PUT")
            with urllib.request.urlopen(upload) as response:
                if response.status not in (200, 201, 204):
                    die("Uploading a segment", response.status)

            status, segment = api.call(
                "POST",
                f"/api/v1/matches/{match_id}/video/segments",
                {"segment_index": index},
                headers=agent,
            )
            if status != 201:
                die("Confirming a segment", segment)
            print(f"  segment {index} uploaded ({len(body):,} bytes)")

    api.call("POST", f"/api/v1/matches/{match_id}/stop", headers=operator)
    status, video = api.call(
        "POST",
        f"/api/v1/matches/{match_id}/video/complete",
        {"expected_segments": args.segments},
        headers=agent,
    )
    if status != 200:
        die("Completing the upload", video)
    print(
        f"Upload complete: {video['size_bytes']:,} bytes across {len(video['segments'])} segments"
    )

    status, queued = api.call("POST", f"/api/v1/matches/{match_id}/process", headers=operator)
    if status != 200:
        die("Queueing processing", queued)
    print(f"Processing queued (task {queued['task_id']}). Waiting…")

    deadline = time.time() + args.timeout
    video = None
    while time.time() < deadline:
        time.sleep(2)
        _, video = api.call("GET", f"/api/v1/matches/{match_id}/video", headers=operator)
        if video.get("status") in ("READY", "FAILED"):
            break
        done = sum(1 for job in video.get("jobs", []) if job["status"] in ("SUCCEEDED", "SKIPPED"))
        print(f"  {video.get('status')} — {done} steps done", end="\r", flush=True)

    print()
    if not video or video.get("status") != "READY":
        for job in sorted(video.get("jobs", []), key=lambda j: j["step"]):
            print(f"  {job['step']:16} {job['status']:10} {job['last_error'] or ''}")
        raise SystemExit(
            f"Processing did not finish: {video.get('status') if video else 'timed out'}"
        )

    print(
        f"Ready: {video['width']}x{video['height']}, {video['duration']:.1f}s, "
        f"audio={video['has_audio']}"
    )

    _, highlights = api.call("GET", f"/api/v1/matches/{match_id}/highlights", headers=operator)
    print(f"\n{highlights['total']} clips:")
    for item in highlights["items"]:
        minutes, seconds = divmod(int(item["start_time"]), 60)
        print(
            f"  {minutes}:{seconds:02d}  {item['duration']:.0f}s  {item['type']:18} "
            f"score {item['score']:.2f}  "
            f"{'16:9' if item['video_url'] else '----'} "
            f"{'9:16' if item['video_url_vertical'] else '----'}"
        )

    print(f"\nWatch it: {args.api.replace(':8000', ':3000')}/match/{match_id}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
