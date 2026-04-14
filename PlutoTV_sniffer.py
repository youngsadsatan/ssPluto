#!/usr/bin/env python3
# -*- coding: utf-8 -*-

SERIES_URL_OR_ID = "66d70dfaf98f52001332a8f5"  #

import os, re, sys, json, uuid, logging, requests

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("pluto_sniffer")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"

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

def decode_jwt(token):
    import base64
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except:
        return {}

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
        raise ValueError("sessionToken missing")
    logger.debug(f"JWT: {json.dumps(decode_jwt(token), indent=2)}")
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
        "geoOverride": "BR"
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"https://pluto.tv/br/on-demand/series/{series_id}",
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
        if item.get("id") == series_id:
            return item
    raise ValueError("Série não encontrada na resposta VOD")

def extract_episodes_info(series_data):
    series_title = series_data.get("name", "Desconhecido")
    series_id = series_data.get("id", "")
    episodes = []
    for season in series_data.get("seasons", []):
        season_num = season.get("seasonNumber")
        if season_num is None:
            season_num = 0  # fallback
        season_id = season.get("_id", "")
        for ep in season.get("episodes", []):
            ep_id = ep.get("_id")
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

def write_output_file(series_title, episodes):
    if not episodes:
        return
    safe_title = re.sub(r'[\\/*?:"<>|]', "", series_title).strip() or "serie_sem_nome"
    filename = f"{safe_title}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write("Título\tTemporada\tEpisódio\tSeries_ID\tSeason_ID\tEpisode_ID\n")
        for ep in episodes:
            season_str = f"S{ep['season_number']:02d}"
            episode_str = f"E{ep['episode_number']:02d}"
            f.write(f"{ep['series_title']}\t{season_str}\t{episode_str}\t{ep['series_id']}\t{ep['season_id']}\t{ep['episode_id']}\n")
    logger.info(f"Arquivo salvo: {filename} ({len(episodes)} episódios)")

def extract_id_from_input(user_input):
    if not user_input:
        raise ValueError("SERIES_URL_OR_ID está vazio")
    match = re.search(r'/series/([a-f0-9]+)', user_input)
    if match:
        return match.group(1)
    if re.fullmatch(r'[a-f0-9]+', user_input, re.I):
        return user_input
    raise ValueError("Formato inválido")

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
    series_data = fetch_series_data(session, device_id, jwt_token, series_id)
    episodes = extract_episodes_info(series_data)
    write_output_file(series_data.get("name", "Série Desconhecida"), episodes)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception("Erro fatal")
        sys.exit(1)
