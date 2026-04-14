#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import uuid
import requests
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"

SERIES_IDS = [
    "66d70dfaf98f52001332a8f5",  # Tratamento de Choque
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
        "geoOverride": "BR",
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
    log.debug("JWT: %s", json.dumps(data, indent=2))
    return token

def fetch_series_data(session, device_id, jwt_token, series_id):
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
        "geoOverride": "BR",
    }
    resp = session.get(BOOT_URL, headers={
        "User-Agent": USER_AGENT,
        "Referer": f"https://pluto.tv/br/on-demand/series/{series_id}",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
    }, params=params)
    resp.raise_for_status()
    return resp.json()

def extract_episodes(series_data):
    """
    Extrai os episódios organizados por temporada.
    Retorna uma lista de objetos com season, episode, title, episode_id.
    """
    episodes = []
    vod_list = series_data.get("VOD", [])
    for vod in vod_list:
        for season in vod.get("seasons", []):
            season_num = season.get("seasonNumber")
            if season_num is None:
                
                season_num = 0
            for ep in season.get("episodes", []):
                ep_id = ep.get("_id")
                if not ep_id:
                    continue
                ep_title = ep.get("name", "Sem título")
                ep_number = ep.get("episodeNumber") or ep.get("number")
                if not ep_number:
                    
                    ep_number = 0
                episodes.append({
                    "season": int(season_num),
                    "episode": int(ep_number),
                    "title": ep_title,
                    "episode_id": ep_id
                })
                
    episodes.sort(key=lambda x: (x["season"], x["episode"]))
    return episodes

def main():
    cookie_content = os.environ.get("PLUTO_COOKIES", "")
    if not cookie_content:
        raise ValueError("PLUTO_COOKIES environment variable not set")

    cookies = parse_netscape_cookies(cookie_content)
    if not cookies:
        raise ValueError("no valid cookies extracted")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".pluto.tv")

    device_id = str(uuid.uuid4())
    log.info("Device ID: %s", device_id)

    jwt_token = get_jwt_token(session, device_id)

    for series_id in SERIES_IDS:
        log.info("Fetching series: %s", series_id)
        data = fetch_series_data(session, device_id, jwt_token, series_id)
        vod_list = data.get("VOD", [])
        if not vod_list:
            log.warning("No VOD data for %s", series_id)
            continue

        series_name = vod_list[0].get("name", "Série Desconhecida")
        log.info("Processing: %s", series_name)

        episodes = extract_episodes(data)
        
        json_output = json.dumps(episodes, ensure_ascii=False, indent=2)

        output_file = f"{series_name}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json_output)

        log.info("Arquivo salvo: %s (%d episódios)", output_file, len(episodes))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Erro fatal")
        sys.exit(1)
