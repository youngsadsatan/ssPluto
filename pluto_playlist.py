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
    {"season": 1, "episode": 1, "title": "Charlie de volta à terapia", "episode_id": "66d71d6c46be430013cf2195"},
    {"season": 1, "episode": 2, "title": "Charlie e a transa que o tirou da seca", "episode_id": "66d71d6e46be430013cf22a4"},
    # Adicione aqui os próximos episódios...
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
