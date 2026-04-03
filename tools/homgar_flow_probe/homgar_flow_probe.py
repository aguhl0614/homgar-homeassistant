#!/usr/bin/env python3
"""Probe HTV145FRF status payloads for hidden flow or history fields."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API_BASE_URL = "https://region3.homgarus.com"
LOGIN_PATH = "/auth/basic/app/login"
HOMES_PATH = "/app/member/appHome/list"
DEVICES_PATH = "/app/device/getDeviceByHid"
STATUS_PATH = "/app/device/getDeviceStatus"


def build_headers(app_code: str, token: str | None = None, hid: str | None = None) -> dict[str, str]:
    headers = {
        "lang": "en",
        "version": "2.21.2075",
        "appCode": app_code,
        "sceneType": "1",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "okhttp/4.9.2",
    }
    if token:
        headers["auth"] = token
    if hid:
        headers["hid"] = str(hid)
    return headers


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Poll the HomGar/RainPoint API for HTV145FRF status snapshots. "
            "Use this while manually watering to discover hidden flow-meter fields."
        )
    )
    parser.add_argument("--email", help="Account e-mail / username.")
    parser.add_argument("--password", help="Account password.")
    parser.add_argument("--app-code", default="2", help="App code. Default: 2 (RainPoint)")
    parser.add_argument("--area-code", default="1", help="Phone country code. Default: 1")
    parser.add_argument("--base-url", default=API_BASE_URL, help=f"API base URL. Default: {API_BASE_URL}")
    parser.add_argument("--hid", help="Optional home id. Auto-discovered if omitted.")
    parser.add_argument("--mid", help="Optional device network mid. Auto-discovered if omitted.")
    parser.add_argument("--did", help="Optional device did. Auto-discovered if omitted.")
    parser.add_argument("--model-code", default="302", help="Target model code. Default: 302")
    parser.add_argument("--label", help="Optional label for this run, for example 30s_test_1.")
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds. Default: 5")
    parser.add_argument("--count", type=int, default=120, help="Number of polls to run. Default: 120")
    parser.add_argument(
        "--until-stop",
        action="store_true",
        help=(
            "Keep polling from idle, detect watering start, and stop automatically "
            "after the valve returns to an idle/off state."
        ),
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=720,
        help="Safety cap for --until-stop mode. Default: 720 polls",
    )
    parser.add_argument(
        "--post-stop-polls",
        type=int,
        default=3,
        help="Extra polls to capture after watering stops in --until-stop mode. Default: 3",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tools/homgar_flow_probe/flow_probe_output.jsonl"),
        help="JSONL output path. Default: tools/homgar_flow_probe/flow_probe_output.jsonl",
    )
    args = parser.parse_args()

    if not args.email:
        args.email = input("Email: ").strip()
    if not args.password:
        args.password = getpass.getpass("Password: ")

    return args


def login(session: requests.Session, base_url: str, email: str, password: str, app_code: str, area_code: str) -> str:
    response = session.post(
        f"{base_url.rstrip('/')}{LOGIN_PATH}",
        headers=build_headers(app_code),
        json={
            "areaCode": area_code,
            "phoneOrEmail": email,
            "password": md5_hex(password),
            "deviceId": secrets.token_hex(16),
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"Login failed: {payload.get('msg')} (code={payload.get('code')})")
    return payload["data"]["token"]


def get_homes(session: requests.Session, base_url: str, app_code: str, token: str) -> list[dict]:
    response = session.get(
        f"{base_url.rstrip('/')}{HOMES_PATH}",
        headers=build_headers(app_code, token=token),
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"get_homes failed: {payload.get('msg')} (code={payload.get('code')})")
    return payload.get("data") or []


def get_devices_for_hid(session: requests.Session, base_url: str, app_code: str, token: str, hid: str) -> list[dict]:
    response = session.get(
        f"{base_url.rstrip('/')}{DEVICES_PATH}",
        headers=build_headers(app_code, token=token, hid=hid),
        params={"hid": str(hid)},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"get_devices_for_hid failed: {payload.get('msg')} (code={payload.get('code')})")
    return payload.get("data") or []


def get_device_status(session: requests.Session, base_url: str, app_code: str, token: str, hid: str, mid: str) -> dict:
    response = session.get(
        f"{base_url.rstrip('/')}{STATUS_PATH}",
        headers=build_headers(app_code, token=token, hid=hid),
        params={"mid": str(mid)},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"get_device_status failed: {payload.get('msg')} (code={payload.get('code')})")
    return payload.get("data") or {}


def auto_discover_target(homes: list[dict], all_devices: dict[str, list[dict]], model_code: str, hid: str | None, did: str | None, mid: str | None) -> tuple[dict, dict]:
    matches: list[tuple[dict, dict, dict]] = []
    for home in homes:
        home_hid = str(home.get("hid"))
        if hid and home_hid != str(hid):
            continue
        for hub in all_devices.get(home_hid, []):
            for sub in hub.get("subDevices", []):
                if str(sub.get("modelCode")) != str(model_code):
                    continue
                if did and str(sub.get("did")) != str(did):
                    continue
                if mid and str(sub.get("mid")) != str(mid):
                    continue
                matches.append((home, hub, sub))

    if not matches:
        raise RuntimeError(f"No modelCode {model_code} device found with the supplied filters.")
    if len(matches) > 1:
        raise RuntimeError(
            "Multiple matching devices found. Re-run with --hid, --mid, or --did to pick one:\n" +
            "\n".join(
                f"hid={home.get('hid')} mid={sub.get('mid')} did={sub.get('did')} name={sub.get('name')}"
                for home, _, sub in matches
            )
        )
    home, hub, sub = matches[0]
    return hub, sub


def parse_htv145_hex(raw_value: str | None) -> dict:
    if not raw_value or "#" not in raw_value:
        return {}

    hex_data = raw_value.split("#", 1)[1]
    result: dict[str, object] = {
        "hex_data": hex_data,
        "sequence_hex": hex_data[:6] if len(hex_data) >= 6 else None,
        "status_code": None,
        "status_text": None,
        "duration_seconds": None,
        "countdown_seconds": None,
        "clock_ticks": None,
        "unknown_chunks": [],
    }

    status_map = {
        "D841": "on",
        "D821": "on",
        "D820": "off_recent",
        "D800": "off_idle",
    }
    for code, text in status_map.items():
        if code in hex_data:
            result["status_code"] = code
            result["status_text"] = text
            break

    pos_duration = hex_data.find("AD")
    if pos_duration >= 0 and pos_duration + 6 <= len(hex_data):
        dur_hex = hex_data[pos_duration + 2:pos_duration + 6]
        try:
            result["duration_seconds"] = int.from_bytes(bytes.fromhex(dur_hex), "little")
        except ValueError:
            pass

    current_ticks = None
    for clock_marker in ("FEFF0F", "FF0F"):
        pos_clk = hex_data.find(clock_marker)
        if pos_clk >= 0 and pos_clk + len(clock_marker) + 8 <= len(hex_data):
            clk_hex = hex_data[pos_clk + len(clock_marker):pos_clk + len(clock_marker) + 8]
            try:
                current_ticks = int.from_bytes(bytes.fromhex(clk_hex), "little")
                result["clock_ticks"] = current_ticks
            except ValueError:
                pass
            break

    for timer_marker in ("20B7", "21B7"):
        pos_timer = hex_data.find(timer_marker)
        if pos_timer >= 0 and pos_timer + len(timer_marker) + 8 <= len(hex_data):
            timer_hex = hex_data[pos_timer + len(timer_marker):pos_timer + len(timer_marker) + 8]
            try:
                end_ticks = int.from_bytes(bytes.fromhex(timer_hex), "little")
                if current_ticks and end_ticks > current_ticks:
                    result["countdown_seconds"] = end_ticks - current_ticks
                else:
                    result["countdown_seconds"] = 0
            except ValueError:
                pass
            break

    cursor = 0
    markers = ["D841", "D821", "D820", "D800", "20B7", "21B7", "AD", "FEFF0F", "FF0F"]
    positions = sorted((hex_data.find(marker), marker) for marker in markers if hex_data.find(marker) >= 0)
    for pos, marker in positions:
        if pos > cursor:
            result["unknown_chunks"].append({"offset": cursor, "hex": hex_data[cursor:pos]})
        marker_len = {
            "D841": 4,
            "D821": 4,
            "D820": 4,
            "D800": 4,
            "20B7": 12,
            "21B7": 12,
            "AD": 6,
            "FEFF0F": 14,
            "FF0F": 12,
        }[marker]
        cursor = max(cursor, pos + marker_len)
    if cursor < len(hex_data):
        result["unknown_chunks"].append({"offset": cursor, "hex": hex_data[cursor:]})

    return result


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_jsonl(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def compact_status_map(status_data: dict) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for item in status_data.get("subDeviceStatus", []):
        value = item.get("value")
        if value is not None:
            result[item.get("id")] = value
    return result


def get_status_text(parsed: dict) -> str:
    return str(parsed.get("status_text") or "unknown")


def is_active_status(parsed: dict) -> bool:
    return get_status_text(parsed) == "on"


def is_stopped_status(parsed: dict) -> bool:
    return get_status_text(parsed) in {"off_idle", "off_recent"}


def summarize_run(entries: list[dict]) -> dict:
    if not entries:
        return {}

    pre_idle = None
    active = None
    post_idle = None

    for entry in entries:
        parsed = entry.get("parsed_d01") or {}
        if pre_idle is None and is_stopped_status(parsed):
            pre_idle = entry
        if active is None and is_active_status(parsed):
            active = entry
        if active is not None and is_stopped_status(parsed):
            post_idle = entry

    def extract(entry: dict | None) -> dict | None:
        if not entry:
            return None
        parsed = entry.get("parsed_d01") or {}
        unknown_chunks = parsed.get("unknown_chunks") or []
        return {
            "poll": entry.get("poll"),
            "timestamp": entry.get("timestamp"),
            "status": get_status_text(parsed),
            "duration_seconds": parsed.get("duration_seconds"),
            "countdown_seconds": parsed.get("countdown_seconds"),
            "clock_ticks": parsed.get("clock_ticks"),
            "d01": entry.get("status_non_null", {}).get("D01"),
            "unknown_chunks": unknown_chunks,
            "candidate_tail_hex": unknown_chunks[1]["hex"] if len(unknown_chunks) > 1 else None,
        }

    summary = {
        "label": entries[0].get("label"),
        "device_name": entries[0].get("device_name"),
        "device_model": entries[0].get("device_model"),
        "hid": entries[0].get("hid"),
        "mid": entries[0].get("mid"),
        "did": entries[0].get("did"),
        "poll_count": len(entries),
        "pre_idle": extract(pre_idle),
        "active": extract(active),
        "post_idle": extract(post_idle),
    }

    if summary["pre_idle"] and summary["post_idle"]:
        summary["candidate_tail_transition"] = {
            "before": summary["pre_idle"].get("candidate_tail_hex"),
            "after": summary["post_idle"].get("candidate_tail_hex"),
        }

    return summary


def print_summary(summary: dict) -> None:
    if not summary:
        return
    print("Run summary:")
    print(json.dumps(summary, indent=2))


def main() -> int:
    args = parse_args()
    session = requests.Session()
    token = login(session, args.base_url, args.email, args.password, str(args.app_code), str(args.area_code))
    homes = get_homes(session, args.base_url, str(args.app_code), token)

    all_devices: dict[str, list[dict]] = {}
    for home in homes:
        hid = str(home.get("hid"))
        all_devices[hid] = get_devices_for_hid(session, args.base_url, str(args.app_code), token, hid)

    hub, sub = auto_discover_target(
        homes=homes,
        all_devices=all_devices,
        model_code=str(args.model_code),
        hid=args.hid,
        did=args.did,
        mid=args.mid,
    )

    hid = str(hub.get("hid") or next(home.get("hid") for home in homes if any(h is hub for h in all_devices[str(home.get("hid"))])))
    mid = str(sub.get("mid"))
    did = str(sub.get("did"))

    print(f"Target device: {sub.get('name')} model={sub.get('model')} modelCode={sub.get('modelCode')}")
    print(f"hid={hid} mid={mid} did={did} addr={sub.get('addr')} portNumber={sub.get('portNumber')}")
    print(f"Output file: {args.output}")
    if args.label:
        print(f"Run label: {args.label}")
    print("Start manual watering from the app or timer button while this probe runs.")

    previous_d01 = None
    previous_non_null = None
    watering_started = False
    stop_poll_target = None
    total_polls = args.max_polls if args.until_stop else args.count
    entries: list[dict] = []

    for poll_index in range(1, total_polls + 1):
        status_data = get_device_status(session, args.base_url, str(args.app_code), token, hid, mid)
        non_null = compact_status_map(status_data)
        d01 = non_null.get("D01")
        parsed = parse_htv145_hex(d01)
        entry = {
            "poll": poll_index,
            "timestamp": now_iso(),
            "hid": hid,
            "mid": mid,
            "did": did,
            "device_name": sub.get("name"),
            "device_model": sub.get("model"),
            "label": args.label,
            "status_non_null": non_null,
            "parsed_d01": parsed,
        }
        entries.append(entry)
        write_jsonl(args.output, entry)

        changed = []
        if d01 != previous_d01:
            changed.append("D01")
        if non_null != previous_non_null:
            changed.append("status-map")

        summary = get_status_text(parsed)
        duration = parsed.get("duration_seconds")
        countdown = parsed.get("countdown_seconds")
        phase = "active" if is_active_status(parsed) else "idle"
        progress_total = args.max_polls if args.until_stop else args.count
        print(
            f"[{poll_index}/{progress_total}] {entry['timestamp']} "
            f"status={summary} phase={phase} duration={duration} countdown={countdown} "
            f"changed={','.join(changed) if changed else 'no'}"
        )

        if "D01" in changed and d01:
            print(f"  D01={d01}")
            unknown_chunks = parsed.get("unknown_chunks") or []
            if unknown_chunks:
                print(f"  unknown_chunks={json.dumps(unknown_chunks)}")

        previous_d01 = d01
        previous_non_null = non_null

        if args.until_stop:
            if is_active_status(parsed) and not watering_started:
                watering_started = True
                print("  Transition detected: watering started.")
            elif watering_started and is_stopped_status(parsed) and stop_poll_target is None:
                stop_poll_target = poll_index + max(args.post_stop_polls, 0)
                print(f"  Transition detected: watering stopped. Capturing {args.post_stop_polls} extra polls.")

            if stop_poll_target is not None and poll_index >= stop_poll_target:
                print_summary(summarize_run(entries))
                print("Probe complete after stop detection.")
                return 0

        limit_for_sleep = total_polls
        if poll_index < limit_for_sleep:
            time.sleep(max(args.interval, 0))

    if args.until_stop:
        print_summary(summarize_run(entries))
        print("Probe stopped by safety cap before stop detection completed.")
        return 1

    print_summary(summarize_run(entries))
    print("Probe complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
