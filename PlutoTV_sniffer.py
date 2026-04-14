#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import uuid
import time
import requests
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"

SERIES_IDS = [
    "66d70dfaf98f52001332a8f5",
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
    return token

def fetch_series_vod(session, device_id, jwt_token, series_id):
    """Obtém os dados VOD da série usando o endpoint boot."""
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

def extract_episodes(vod_data, series_id):
    episodes = []
    vod_list = vod_data.get("VOD", [])
    target = None
    for item in vod_list:
        if item.get("id") == series_id:
            target = item
            break
    if not target:
        # fallback: tenta encontrar pelo nome (pode ser arriscado)
        for item in vod_list:
            if "tratamento" in item.get("name", "").lower():
                target = item
                break
    if not target:
        log.warning("Série %s não localizada no VOD. Itens disponíveis: %s",
                    series_id, [v.get("name") for v in vod_list])
        return episodes

    for season in target.get("seasons", []):
        season_num = season.get("seasonNumber")
        if season_num is None:
            continue
        for ep in season.get("episodes", []):
            ep_id = ep.get("_id") or ep.get("id")
            if not ep_id:
                continue
            ep_title = ep.get("name", "Sem título")
            ep_number = ep.get("episodeNumber") or ep.get("number")
            if ep_number is None:
                continue
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
    time.sleep(1)  # Pequena pausa para evitar 429

    for series_id in SERIES_IDS:
        log.info("Fetching series: %s", series_id)
        try:
            data = fetch_series_vod(session, device_id, jwt_token, series_id)
        except Exception as e:
            log.error("Falha ao obter VOD para %s: %s", series_id, e)
            continue

        episodes = extract_episodes(data, series_id)
        if not episodes:
            log.warning("Nenhum episódio encontrado para %s", series_id)
            continue

        # O nome da série é pego do próprio objeto alvo
        series_name = next((v.get("name", "Série Desconhecida") for v in data.get("VOD", []) if v.get("id") == series_id), "Série Desconhecida")
        log.info("Processando: %s", series_name)

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
