#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import re
import uuid
import logging
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pluto_sniffer")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"
SLUG_RESOLVER = "https://service-vod.clusters.pluto.tv/v4/vod/slugs"

# Lista de IDs externos (pode adicionar mais)
SERIES_IDS = [
    "66d70dfaf98f52001332a8f5",
]

def parse_netscape_cookies(content):
    cookies = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        name, value = parts[5].strip(), parts[6].strip()
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
        "geoOverride": "BR"
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://pluto.tv/",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
        "CloudFront-Viewer-Country": "BR",
        "X-Forwarded-For": "177.0.0.1"
    }
    resp = session.get(BOOT_URL, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("sessionToken")
    if not token:
        raise ValueError("sessionToken não encontrado")
    return token

def resolve_internal_id(session, external_id, jwt_token):
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "CloudFront-Viewer-Country": "BR",
        "X-Forwarded-For": "177.0.0.1"
    }
    resp = session.get(SLUG_RESOLVER, headers=headers, params={"slugs": external_id})
    resp.raise_for_status()
    data = resp.json()
    if external_id in data:
        return data[external_id]["id"]
    raise ValueError(f"Não foi possível resolver o ID externo: {external_id}")

def fetch_series_data(session, device_id, internal_id):
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
        "seriesIDs": internal_id,
        "geoOverride": "BR"
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"https://pluto.tv/br/on-demand/series/{internal_id}",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
        "CloudFront-Viewer-Country": "BR",
        "X-Forwarded-For": "177.0.0.1"
    }
    resp = session.get(BOOT_URL, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    vod_list = data.get("VOD", [])
    for item in vod_list:
        if item.get("id") == internal_id:
            return item
    raise ValueError(f"Série com ID interno {internal_id} não encontrada no VOD")

def extract_episodes(series_data):
    episodes = []
    for season in series_data.get("seasons", []):
        season_num = season.get("seasonNumber")
        if season_num is None:
            continue
        for ep in season.get("episodes", []):
            ep_id = ep.get("_id")
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
        raise ValueError("PLUTO_COOKIES não definido")
    cookies = parse_netscape_cookies(cookie_content)
    if not cookies:
        raise ValueError("Nenhum cookie válido encontrado")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".pluto.tv")

    device_id = str(uuid.uuid4())
    log.info("Device ID: %s", device_id)

    # 1. Obter JWT
    jwt_token = get_jwt_token(session, device_id)
    log.info("JWT obtido com sucesso")

    for external_id in SERIES_IDS:
        log.info("Processando ID externo: %s", external_id)

        # 2. Resolver ID interno
        try:
            internal_id = resolve_internal_id(session, external_id, jwt_token)
        except Exception as e:
            log.error("Falha ao resolver ID interno para %s: %s", external_id, e)
            continue
        log.info("ID interno resolvido: %s", internal_id)

        # 3. Buscar dados da série
        try:
            series_data = fetch_series_data(session, device_id, internal_id)
        except Exception as e:
            log.error("Falha ao obter dados da série %s: %s", internal_id, e)
            continue

        series_name = series_data.get("name", "Série Desconhecida")
        log.info("Série: %s", series_name)

        # 4. Extrair episódios
        episodes = extract_episodes(series_data)
        if not episodes:
            log.warning("Nenhum episódio encontrado para %s", series_name)
            continue

        # 5. Salvar JSON
        safe_name = re.sub(r'[\\/*?:"<>|]', "", series_name).strip()
        output_file = f"{safe_name}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(episodes, f, ensure_ascii=False, indent=2)

        log.info("Arquivo salvo: %s (%d episódios)", output_file, len(episodes))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Erro fatal")
        sys.exit(1)
