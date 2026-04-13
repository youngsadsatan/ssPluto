#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import uuid
import requests
from urllib.parse import urlencode

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"
STITCHER_BASE = "https://cfd-v4-service-stitcher-dash-use1-1.prd.pluto.tv/v2/stitch/dash/episode/{episode_id}/main.mpd"
OUTPUT_FILE = "playlist.m3u"

# --- Lista de episódios (exemplo com "Tratamento de Choque") ---
# Você precisará coletar os IDs de cada episódio manualmente.
EPISODES = [
    {"season": 1, "episode": 1,  "title": "Pilot",                               "episode_id": "60959ee4d9b0ce0014e4b694"},
    {"season": 1, "episode": 2,  "title": "Beers and Ponds",                     "episode_id": "60959e2141fc48001326c5af"},
    {"season": 1, "episode": 3,  "title": "Pranks and Tricks",                   "episode_id": "60959e2341fc48001326c5d6"},
    {"season": 1, "episode": 4,  "title": "Kim Kelly Is My Friend",             "episode_id": "60959e2141fc48001326c59a"},
    {"season": 1, "episode": 5,  "title": "Tests and Tits",                      "episode_id": "60959e2041fc48001326c553"},
    {"season": 1, "episode": 6,  "title": "I'm in a Band",                      "episode_id": "60959e2541fc48001326c674"},
    {"season": 1, "episode": 7,  "title": "Carded and Discarded",               "episode_id": "60959e2e41fc48001326c6f2"},
    {"season": 1, "episode": 8,  "title": "Girlfriends and Boyfriends",          "episode_id": "60959e2541fc48001326c65d"},
    {"season": 1, "episode": 9,  "title": "We Have Spirit",                      "episode_id": "60959e2641fc48001326c689"},
    {"season": 1, "episode": 10, "title": "The Diary",                          "episode_id": "60959e2341fc48001326c615"},
    {"season": 1, "episode": 11, "title": "Appearance and Books",               "episode_id": "60959e2141fc48001326c585"},
    {"season": 1, "episode": 12, "title": "The Garage Door",                    "episode_id": "60959e2641fc48001326c6a7"},
    {"season": 1, "episode": 13, "title": "Choking and Smoking",                "episode_id": "60959e2341fc48001326c5eb"},
    {"season": 1, "episode": 14, "title": "Dead Dogs and Gym Teachers",         "episode_id": "60959e2e41fc48001326c707"},
    {"season": 1, "episode": 15, "title": "Noshing and Moshing",                "episode_id": "60959f4c72e8e300148a367f"},
    {"season": 1, "episode": 16, "title": "Kissing and Loafing",                "episode_id": "60959e2341fc48001326c62b"},
    {"season": 1, "episode": 17, "title": "The Little Things",                 "episode_id": "60959e2341fc48001326c600"},
    {"season": 1, "episode": 18, "title": "Discos and Dragons",                "episode_id": "60959e2141fc48001326c56e"},
]

def parse_netscape_cookies(content):
    cookies = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) != 7:
            continue
        name = parts[5].strip()
        value = parts[6].strip()
        if name:
            cookies[name] = value
    return cookies

def get_jwt_token(session, device_id):
    """Obtém um token JWT válido."""
    params = {
        "appName": "web",
        "appVersion": FIXED_APP_VERSION,
        "clientModelNumber": "1.0.0",
        "deviceType": "web",
        "deviceMake": "firefox",
        "deviceModel": "web",
        "deviceVersion": "149.0",
        "clientID": device_id,
        "deviceId": device_id,
        "sessionID": device_id,
        "marketingRegion": "BR",
        "country": "BR",
        "deviceLat": "-29.7800",
        "deviceLon": "-55.8000",
        "deviceDNT": "false",
        "serverSideAds": "false",
        "userId": "",
    }
    resp = session.get(BOOT_URL, headers={
        "User-Agent": USER_AGENT,
        "Referer": "https://pluto.tv/",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
    }, params=params)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("sessionToken")
    if not token:
        raise ValueError("sessionToken missing")
    return token

def build_dash_url(episode_id, jwt_token, device_id):
    """Constrói a URL DASH completa para um episódio."""
    params = {
        "jwt": jwt_token,
        "sid": device_id,
        "deviceId": device_id,
        "advertisingId": "",
        "appName": "web",
        "appVersion": FIXED_APP_VERSION,
        "app_name": "web",
        "clientDeviceType": "0",
        "clientID": device_id,
        "clientModelNumber": "1.0.0",
        "country": "BR",
        "deviceDNT": "false",
        "deviceLat": "-29.7800",
        "deviceLon": "-55.8000",
        "deviceMake": "firefox",
        "deviceModel": "web",
        "deviceType": "web",
        "deviceVersion": "149.0",
        "marketingRegion": "BR",
        "serverSideAds": "false",
        "sessionID": device_id,
        "userId": "",
        "masterJWTPassthrough": "true",
        "includeExtendedEvents": "true",
        "eventVOD": "false",
    }
    return f"{STITCHER_BASE.format(episode_id=episode_id)}?{urlencode(params)}"

def generate_m3u_playlist():
    cookie_content = os.environ.get("PLUTO_COOKIES", "")
    if not cookie_content:
        raise ValueError("PLUTO_COOKIES not set")
    cookies = parse_netscape_cookies(cookie_content)
    if not cookies:
        raise ValueError("no valid cookies")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".pluto.tv")

    print(f"🍪 Cookies carregados: {len(cookies)}", file=sys.stderr)
    device_id = str(uuid.uuid4())
    print(f"🆔 Device ID: {device_id}", file=sys.stderr)

    print("🔐 Obtendo token JWT...", file=sys.stderr)
    jwt_token = get_jwt_token(session, device_id)
    print("✅ JWT obtido com sucesso.\n", file=sys.stderr)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ep in EPISODES:
            season = str(ep["season"]).zfill(2)
            episode = str(ep["episode"]).zfill(2)
            ep_id = ep["episode_id"]
            title = ep["title"]
            thumb = f"https://images.pluto.tv/episodes/{ep_id}/screenshot16_9.jpg"
            url = build_dash_url(ep_id, jwt_token, device_id)

            f.write(f'#EXTINF:-1 type="video" tvg-logo="{thumb}" group-title="Tratamento de Choque", S{season}E{episode} • {title}\n')
            f.write(f"{url}\n")
            print(f"   ✅ S{season}E{episode}: {title}", file=sys.stderr)

    print(f"\n🎉 Playlist '{OUTPUT_FILE}' gerada com sucesso!", file=sys.stderr)

if __name__ == "__main__":
    try:
        generate_m3u_playlist()
    except Exception as e:
        print(f"\n💥 Erro fatal: {e}", file=sys.stderr)
        sys.exit(1)
