#!/usr/bin/env python3
"""Standalone helper for authenticating against the HomGar API."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Iterable

import requests

API_BASE_URL = "https://region3.homgarus.com"
LOGIN_PATH = "/auth/basic/app/login"
HOMES_PATH = "/app/member/appHome/list"
DEFAULT_COMMON_AREA_CODES = ["1", "33", "31", "44", "49", "34", "39", "61"]
DEFAULT_APP_CODES = ["1", "2"]
APP_CODE_LABELS = {
    "1": "HomGar",
    "2": "RainPoint",
    "4": "RainPoint Agri",
}


class HomgarLoginError(Exception):
    """Structured login failure from the HomGar API."""

    def __init__(self, code: int | None, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def build_headers(app_code: str, token: str | None = None) -> dict[str, str]:
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
    return headers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Log in to the HomGar API with a specific area code or try a list "
            "of likely country dialing codes until one succeeds."
        )
    )
    parser.add_argument("--email", help="Account e-mail / username.")
    parser.add_argument("--password", help="Account password.")
    parser.add_argument(
        "--app-code",
        help="Single app code to test. Examples: 1=HomGar, 2=RainPoint, 4=RainPoint Agri.",
    )
    parser.add_argument(
        "--app-codes",
        help="Comma-separated app codes to try in order, for example 1,2.",
    )
    parser.add_argument(
        "--all-known-apps",
        action="store_true",
        help="Try the known app codes 1, 2, and 4.",
    )
    parser.add_argument(
        "--area-code",
        help="Single area code to test, for example 1, 31, or 33.",
    )
    parser.add_argument(
        "--area-codes",
        help="Comma-separated area codes to try in order, for example 1,31,33.",
    )
    parser.add_argument(
        "--common",
        action="store_true",
        help="Try a small built-in set of common country dialing codes.",
    )
    parser.add_argument(
        "--base-url",
        default=API_BASE_URL,
        help=f"HomGar API base URL. Default: {API_BASE_URL}",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10,
        help="HTTP timeout in seconds. Default: 10",
    )
    parser.add_argument(
        "--save-auth",
        type=Path,
        help="Optional path to write the successful auth response as JSON.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=5,
        help="Pause between non-rate-limited attempts in seconds. Default: 5",
    )
    parser.add_argument(
        "--rate-limit-wait",
        type=float,
        default=60,
        help="Wait in seconds before retrying after 'operate too frequently'. Default: 60",
    )
    parser.add_argument(
        "--max-rate-limit-retries",
        type=int,
        default=2,
        help="Number of retries for the same area code after rate limiting. Default: 2",
    )
    args = parser.parse_args()

    if not args.email:
        args.email = input("Email: ").strip()
    if not args.password:
        args.password = getpass.getpass("Password: ")

    if not args.area_code and not args.area_codes and not args.common:
        args.common = True

    return args


def collect_area_codes(args: argparse.Namespace) -> list[str]:
    codes: list[str] = []

    def extend(values: Iterable[str]) -> None:
        for value in values:
            code = value.strip()
            if code and code not in codes:
                codes.append(code)

    if args.area_code:
        extend([args.area_code])
    if args.area_codes:
        extend(args.area_codes.split(","))
    if args.common:
        extend(DEFAULT_COMMON_AREA_CODES)

    return codes


def collect_app_codes(args: argparse.Namespace) -> list[str]:
    codes: list[str] = []

    def extend(values: Iterable[str]) -> None:
        for value in values:
            code = value.strip()
            if code and code not in codes:
                codes.append(code)

    if args.app_code:
        extend([args.app_code])
    if args.app_codes:
        extend(args.app_codes.split(","))
    if args.all_known_apps:
        extend(["1", "2", "4"])
    if not codes:
        extend(DEFAULT_APP_CODES)

    return codes


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def login(
    session: requests.Session,
    base_url: str,
    app_code: str,
    email: str,
    password: str,
    area_code: str,
    timeout: float,
) -> dict:
    response = session.post(
        f"{base_url}{LOGIN_PATH}",
        headers=build_headers(app_code=app_code),
        json={
            "areaCode": area_code,
            "phoneOrEmail": email,
            "password": md5_hex(password),
            "deviceId": secrets.token_hex(16),
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise HomgarLoginError(
            payload.get("code"),
            payload.get("msg") or f"HomGar code {payload.get('code')}",
        )
    return payload["data"]


def fetch_homes(
    session: requests.Session,
    base_url: str,
    app_code: str,
    token: str,
    timeout: float,
) -> list[dict]:
    response = session.get(
        f"{base_url}{HOMES_PATH}",
        headers=build_headers(app_code=app_code, token=token),
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("msg") or f"HomGar code {payload.get('code')}")
    return payload.get("data") or []


def build_auth_cache(email: str, app_code: str, login_data: dict) -> dict:
    user_data = login_data.get("user", {})
    return {
        "email": email,
        "app_code": app_code,
        "token": login_data.get("token"),
        "token_expires": time.time() + (login_data.get("tokenExpired") or 0),
        "refresh_token": login_data.get("refreshToken"),
        "mqtt_host": login_data.get("mqttHostUrl"),
        "v_device_name": user_data.get("deviceName"),
        "v_device_secret": user_data.get("deviceSecret"),
        "v_product_key": user_data.get("productKey"),
    }


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_rate_limited(error: Exception) -> bool:
    if isinstance(error, HomgarLoginError):
        return "operate too frequently" in error.msg.lower()
    return False


def main() -> int:
    args = parse_args()
    app_codes = collect_app_codes(args)
    area_codes = collect_area_codes(args)

    if not app_codes:
        print("No app codes were provided.", file=sys.stderr)
        return 2
    if not area_codes:
        print("No area codes were provided.", file=sys.stderr)
        return 2

    session = requests.Session()

    total_attempts = len(app_codes) * len(area_codes)
    attempt_number = 0

    for app_code in app_codes:
        for area_code in area_codes:
            attempt_number += 1
            rate_limit_retries = 0
            while True:
                app_label = APP_CODE_LABELS.get(app_code, "Unknown")
                print(
                    f"[{attempt_number}/{total_attempts}] "
                    f"Trying app_code={app_code} ({app_label}), area_code={area_code}..."
                )
                try:
                    login_data = login(
                        session=session,
                        base_url=args.base_url.rstrip("/"),
                        app_code=app_code,
                        email=args.email,
                        password=args.password,
                        area_code=area_code,
                        timeout=args.timeout,
                    )
                    homes = fetch_homes(
                        session=session,
                        base_url=args.base_url.rstrip("/"),
                        app_code=app_code,
                        token=login_data["token"],
                        timeout=args.timeout,
                    )
                except requests.HTTPError as err:
                    print(f"  HTTP error: {err}")
                    break
                except requests.RequestException as err:
                    print(f"  Network error: {err}")
                    break
                except HomgarLoginError as err:
                    if is_rate_limited(err) and rate_limit_retries < max(args.max_rate_limit_retries, 0):
                        rate_limit_retries += 1
                        print(
                            "  Rate limited by API. "
                            f"Waiting {args.rate_limit_wait:.0f}s before retry "
                            f"({rate_limit_retries}/{args.max_rate_limit_retries})..."
                        )
                        time.sleep(max(args.rate_limit_wait, 0))
                        continue
                    print(f"  Login failed: {err.msg}")
                    break
                except (KeyError, ValueError) as err:
                    print(f"  Login failed: {err}")
                    break
                else:
                    print(f"  Success. app_code={app_code}, area_code={area_code}")
                    print(f"  Token present: {'yes' if login_data.get('token') else 'no'}")
                    print(f"  Homes found: {len(homes)}")
                    for home in homes:
                        print(f"    - hid={home.get('hid')} name={home.get('homeName')}")

                    if args.save_auth:
                        auth_cache = build_auth_cache(args.email, app_code, login_data)
                        save_json(args.save_auth, auth_cache)
                        print(f"  Auth cache written to: {args.save_auth}")

                    print()
                    print("Use these values in Home Assistant or other API scripts:")
                    print(f"  app_code={app_code}")
                    print(f"  area_code={area_code}")
                    return 0

                time.sleep(max(args.pause, 0))
                break

    print()
    print("No supplied app_code / area_code combination worked.")
    print(
        "The account may belong to a different app brand, region, or identifier format. "
        "If you log into RainPoint rather than HomGar, app_code=2 is the next value to try."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
