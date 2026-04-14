#!/usr/bin/env python3
# -*- coding: utf-8 -*-

SERIES_URL_OR_ID = "66d70dfaf98f52001332a8f5"  #

import os
import re
import sys
import uuid
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"
CHRONICLE_BASE = "https://service-chronicle.clusters.pluto.tv/v2"

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

def fetch_series_details(session, series_id, jwt_token, device_id):
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {jwt_token}",
        "Client-ID": device_id,
        "Origin": "https://pluto.tv",
        "Referer": f"https://pluto.tv/br/on-demand/series/{series_id}",
    }
    resp = session.get(f"{CHRONICLE_BASE}/series/{series_id}", headers=headers)
    resp.raise_for_status()
    return resp.json()

def fetch_seasons(session, series_id, jwt_token, device_id):
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {jwt_token}",
        "Client-ID": device_id,
    }
    resp = session.get(f"{CHRONICLE_BASE}/series/{series_id}/seasons", headers=headers)
    resp.raise_for_status()
    return resp.json()

def fetch_episodes(session, season_id, jwt_token, device_id):
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {jwt_token}",
        "Client-ID": device_id,
    }
    resp = session.get(f"{CHRONICLE_BASE}/seasons/{season_id}/episodes", headers=headers)
    resp.raise_for_status()
    return resp.json()

def extract_episodes_info(series_details, seasons_data, episodes_by_season):
    series_title = series_details.get("name", "Desconhecido")
    series_id = series_details.get("id", "")
    episodes = []
    for season in seasons_data:
        season_num = season.get("seasonNumber")
        season_id = season.get("id", "")
        ep_list = episodes_by_season.get(season_id, [])
        for ep in ep_list:
            ep_id = ep.get("id")
            ep_number = ep.get("number")
            if not ep_id or ep_number is None:
                continue
            ep_title = ep.get("name", "Sem título")
            episodes.append({
                "series_title": series_title,
                "series_id": series_id,
                "season_number": season_num,
                "season_id": season_id,
                "episode_number": ep_number,
                "episode_title": ep_title,
                "episode_id": ep_id
            })
    episodes.sort(key=lambda x: (x["season_number"], x["episode_number"]))
    return episodes

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def write_output_file(series_title, episodes):
    if not episodes:
        return
    safe_title = sanitize_filename(series_title) or "serie_sem_nome"
    filename = f"{safe_title}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write("Título\tTemporada\tEpisódio\tSeries_ID\tSeason_ID\tEpisode_ID\n")
        for ep in episodes:
            season_str = f"S{ep['season_number']:02d}"
            episode_str = f"E{ep['episode_number']:02d}"
            f.write(f"{ep['series_title']}\t{season_str}\t{episode_str}\t{ep['series_id']}\t{ep['season_id']}\t{ep['episode_id']}\n")
    print(f"Arquivo salvo: {filename} ({len(episodes)} episódios)")

def extract_id_from_input(user_input):
    if not user_input:
        raise ValueError("SERIES_URL_OR_ID está vazio")
    match = re.search(r'/series/([a-f0-9]+)', user_input)
    if match:
        return match.group(1)
    if re.fullmatch(r'[a-f0-9]+', user_input, re.I):
        return user_input
    raise ValueError("Formato inválido. Forneça URL ou ID hexadecimal")

def main():
    series_id = extract_id_from_input(SERIES_URL_OR_ID.strip())
    cookie_content = os.environ.get("PLUTO_COOKIES", "")
    if not cookie_content:
        raise ValueError("PLUTO_COOKIES não definido")
    cookies = parse_netscape_cookies(cookie_content)
    if not cookies:
        raise ValueError("Cookies inválidos")
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".pluto.tv")
    device_id = str(uuid.uuid4())
    jwt_token = get_jwt_token(session, device_id)

    series_details = fetch_series_details(session, series_id, jwt_token, device_id)
    series_title = series_details.get("name", "Série Desconhecida")

    seasons_data = fetch_seasons(session, series_id, jwt_token, device_id)

    episodes_by_season = {}
    for season in seasons_data:
        season_id = season.get("id")
        if season_id:
            ep_data = fetch_episodes(session, season_id, jwt_token, device_id)
            episodes_by_season[season_id] = ep_data

    episodes = extract_episodes_info(series_details, seasons_data, episodes_by_season)
    write_output_file(series_title, episodes)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)
