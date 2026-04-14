#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import uuid
import argparse
import glob
from pathlib import Path
from urllib.parse import urlencode

import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"
STITCHER_BASE = "https://cfd-v4-service-stitcher-dash-use1-1.prd.pluto.tv/v2/stitch/hls/episode/{episode_id}/master.m3u8"
OUTPUT_FILE = "playlist.m3u"
DEFAULT_JSON_DIR = "output"

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
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://pluto.tv/",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
    }
    resp = session.get(BOOT_URL, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("sessionToken")
    if not token:
        raise ValueError("sessionToken missing")
    return token

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

def load_series_from_json(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def generate_m3u_playlist(json_files):
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

    device_id = str(uuid.uuid4())
    jwt_token = get_jwt_token(session, device_id)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for json_file in json_files:
            series_data = load_series_from_json(json_file)
            series_title = series_data.get("series_title", "Desconhecido")
            episodes = series_data.get("episodes", [])
            for ep in episodes:
                ep_id = ep.get("episode_id")
                title = ep.get("title", "Sem título")
                slug = ep.get("slug", "")
                thumb = f"https://images.pluto.tv/episodes/{ep_id}/screenshot4_3.jpg"
                url = build_stream_url(ep_id, jwt_token, device_id)
                f.write(f'#EXTINF:-1 type="video" tvg-logo="{thumb}" group-title="{series_title}", {slug} • {title}\n')
                f.write(f"{url}\n")
                print(f"   ✅ {slug}: {title}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Gera playlist M3U a partir de arquivos JSON do Pluto TV.")
    parser.add_argument("json_files", nargs="*", help="Caminhos para arquivos JSON com dados das séries. Se omitido, busca em ./output/*.json")
    args = parser.parse_args()
    
    json_files = args.json_files
    if not json_files:
        json_files = glob.glob(os.path.join(DEFAULT_JSON_DIR, "*.json"))
        if not json_files:
            print("Nenhum arquivo JSON encontrado no diretório padrão './output/'.", file=sys.stderr)
            sys.exit(1)
    
    generate_m3u_playlist(json_files)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n💥 Erro fatal: {e}", file=sys.stderr)
        sys.exit(1)
