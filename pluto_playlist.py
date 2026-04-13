#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import uuid
import requests
from urllib.parse import urlencode, urlparse, parse_qs

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"
SLUG_RESOLVER = "https://service-vod.clusters.pluto.tv/v4/vod/slugs"
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

def resolve_series_id(session, external_id):
    resp = session.get(SLUG_RESOLVER, params={"slugs": external_id})
    resp.raise_for_status()
    data = resp.json()
    if external_id in data:
        return data[external_id]["id"]
    raise ValueError(f"Slug {external_id} not resolved")

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
        "Referer": "https://pluto.tv/br/on-demand/series/" + series_id,
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
        for external_id in SERIES_IDS:
            print(f"\n📺 Processando ID externo: {external_id}", file=sys.stderr)
            try:
                print("🔍 Resolvendo ID interno...", file=sys.stderr)
                internal_id = resolve_series_id(session, external_id)
                print(f"   ID interno: {internal_id}", file=sys.stderr)

                print("🔐 Obtendo token JWT...", file=sys.stderr)
                jwt_token, vod_data = get_jwt_and_vod_data(session, device_id, internal_id)
                print("✅ JWT obtido com sucesso.\n", file=sys.stderr)

                vod_list = vod_data.get("VOD", [])
                print(f"   📦 VOD contém {len(vod_list)} item(ns)", file=sys.stderr)
                if not vod_list:
                    print("   ⚠️ Nenhum VOD encontrado", file=sys.stderr)
                    continue

                # Filtra pelo ID interno
                series_info = next((v for v in vod_list if v["id"] == internal_id), None)
                if not series_info:
                    print(f"   ❌ Série com ID {internal_id} não encontrada na resposta VOD", file=sys.stderr)
                    continue

                series_name = series_info.get("name", "Série Desconhecida")
                seasons = series_info.get("seasons", [])
                print(f"   Temporadas: {len(seasons)}", file=sys.stderr)

                for season in seasons:
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
                print(f"   ❌ Erro: {e}", file=sys.stderr)
                continue

    print(f"\n🎉 Playlist '{OUTPUT_FILE}' gerada com sucesso!", file=sys.stderr)

if __name__ == "__main__":
    try:
        generate_m3u_playlist()
    except Exception as e:
        print(f"\n💥 Erro fatal: {e}", file=sys.stderr)
        sys.exit(1)
