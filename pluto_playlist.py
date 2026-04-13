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
SERIES_IDS = ["66d70dfaf98f52001332a8f5"]
OUTPUT_FILE = "playlist.m3u"

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

def get_jwt_and_vod_data(session, device_id, series_id):
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
        "seriesIDs": series_id,
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
    return token, data

def build_stream_url(episode_id, jwt_token, device_id):
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

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for series_id in SERIES_IDS:
            print(f"\n📺 Processando série ID: {series_id}", file=sys.stderr)
            try:
                print("🔐 Obtendo token JWT...", file=sys.stderr)
                jwt_token, vod_data = get_jwt_and_vod_data(session, device_id, series_id)
                print("✅ JWT obtido com sucesso.\n", file=sys.stderr)

                # DEBUG: exibe um resumo da resposta VOD
                vod_list = vod_data.get("VOD", [])
                print(f"   📦 VOD contém {len(vod_list)} item(ns)", file=sys.stderr)
                if vod_list:
                    first = vod_list[0]
                    print(f"   Série retornada: {first.get('name')} (ID: {first.get('id')})", file=sys.stderr)
                    seasons = first.get("seasons", [])
                    print(f"   Temporadas: {len(seasons)}", file=sys.stderr)
                    if seasons:
                        first_season = seasons[0]
                        eps = first_season.get("episodes", [])
                        print(f"   Episódios na primeira temporada: {len(eps)}", file=sys.stderr)
                        if eps:
                            ep0 = eps[0]
                            print(f"   Primeiro episódio: {ep0.get('name')} (_id: {ep0.get('_id')})", file=sys.stderr)
                else:
                    # Tenta buscar em outros lugares (fallback)
                    print("   ⚠️ Nenhum VOD encontrado, exibindo chaves da resposta:", file=sys.stderr)
                    print(f"   Chaves disponíveis: {list(vod_data.keys())}", file=sys.stderr)
                    if "EPG" in vod_data:
                        print("   EPG presente (talvez seja canal ao vivo)", file=sys.stderr)
                    continue

                if not vod_list:
                    continue

                series_info = vod_list[0]
                series_name = series_info.get("name", "Série Desconhecida")
                for season in series_info.get("seasons", []):
                    for ep in season.get("episodes", []):
                        ep_id = ep.get("_id")
                        if not ep_id:
                            continue
                        ep_title = ep.get("name", "Sem título")
                        ep_number = ep.get("number", "S00E00")
                        thumb = ep.get("thumbnail", {}).get("path", "")
                        if not thumb:
                            thumb = f"https://images.pluto.tv/episodes/{ep_id}/screenshot16_9.jpg"
                        url = build_stream_url(ep_id, jwt_token, device_id)
                        f.write(f'#EXTINF:-1 type="video" tvg-logo="{thumb}" group-title="{series_name}", {ep_number} - {ep_title}\n')
                        f.write(f"{url}\n")
                        print(f"   ✅ {ep_number}: {ep_title}", file=sys.stderr)

            except Exception as e:
                print(f"   ❌ Erro ao obter dados: {e}", file=sys.stderr)
                continue

    print(f"\n🎉 Playlist '{OUTPUT_FILE}' gerada com sucesso!", file=sys.stderr)

if __name__ == "__main__":
    try:
        generate_m3u_playlist()
    except Exception as e:
        print(f"\n💥 Erro fatal: {e}", file=sys.stderr)
        sys.exit(1)
