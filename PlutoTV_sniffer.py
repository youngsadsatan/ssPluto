#!/usr/bin/env python3
# -*- coding: utf-8 -*-

SERIES_URL_OR_ID = "66d70dfaf98f52001332a8f5"  #

import os, re, sys, json, uuid, base64, logging, requests
from datetime import datetime

# ---------- CONFIGURAÇÃO DE LOG ----------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("pluto_sniffer")

USER_AGENT = "Mozilla/5.0 (Linux; Android 15; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.200 Mobile Safari/537.36"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"
VOD_API_BASE = "https://service-vod.clusters.pluto.tv/v4/vod"

FIXED_DEVICE_ID = str(uuid.UUID("12345678-1234-5678-1234-567812345678"))

# ---------- FUNÇÕES AUXILIARES ----------
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
    logger.debug(f"Cookies carregados: {list(cookies.keys())}")
    return cookies

def decode_jwt(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        return decoded
    except Exception as e:
        logger.warning(f"Não foi possível decodificar JWT: {e}")
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
        "geoOverride": "BR",  # 🔥 Força o uso do catálogo brasileiro
    }
    logger.debug(f"Obtendo JWT via {BOOT_URL} com geoOverride=BR")
    resp = session.get(BOOT_URL, headers={
        "User-Agent": USER_AGENT,
        "Referer": "https://pluto.tv/",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
    }, params=params)
    logger.debug(f"Status boot: {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    token = data.get("sessionToken")
    if not token:
        raise ValueError("sessionToken não encontrado")
    jwt_payload = decode_jwt(token)
    logger.debug(f"JWT obtido. Claims: {json.dumps(jwt_payload, indent=2)}")
    return token

def fetch_series_via_boot(session, device_id, jwt_token, series_id):
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
        "geoOverride": "BR",  # 🔥 Reforça o override
    }
    logger.debug(f"Tentando obter série via boot com seriesIDs={series_id} e geoOverride=BR")
    resp = session.get(BOOT_URL, headers={
        "User-Agent": USER_AGENT,
        "Referer": f"https://pluto.tv/br/on-demand/series/{series_id}",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
    }, params=params)
    logger.debug(f"Status boot com seriesIDs: {resp.status_code}")
    if resp.status_code != 200:
        logger.warning(f"boot retornou {resp.status_code}: {resp.text[:500]}")
        return None
    data = resp.json()
    vod_list = data.get("VOD", [])
    logger.debug(f"VOD items retornados pelo boot: {len(vod_list)}")
    for item in vod_list:
        if item.get("id") == series_id:
            logger.info("Série encontrada via boot!")
            return item
    logger.warning("Série não encontrada na resposta boot. IDs disponíveis: " + ", ".join([i.get("id","?") for i in vod_list]))
    return None

def fetch_series_via_vod_api(session, series_id, jwt_token, device_id):
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {jwt_token}",
        "Client-ID": device_id,
        "Origin": "https://pluto.tv",
        "Referer": f"https://pluto.tv/br/on-demand/series/{series_id}/season/1",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate, br",
    }
    params = {"ids": series_id}
    logger.debug(f"Tentando obter série via VOD API: {VOD_API_BASE}/items")
    resp = session.get(f"{VOD_API_BASE}/items", params=params, headers=headers)
    logger.debug(f"Status VOD API: {resp.status_code}")
    if resp.status_code != 200:
        logger.warning(f"VOD API retornou {resp.status_code}: {resp.text[:500]}")
        return None
    data = resp.json()
    logger.debug(f"VOD API retornou {len(data)} itens")
    if not data:
        logger.warning("VOD API retornou lista vazia.")
        return None
    return data[0]

def fetch_seasons_via_vod_api(session, series_id, jwt_token, device_id):
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {jwt_token}",
        "Client-ID": device_id,
        "Referer": f"https://pluto.tv/br/on-demand/series/{series_id}",
        "Accept": "application/json",
    }
    logger.debug(f"Buscando temporadas via VOD API: {VOD_API_BASE}/series/{series_id}/seasons")
    resp = session.get(f"{VOD_API_BASE}/series/{series_id}/seasons", headers=headers)
    logger.debug(f"Status seasons: {resp.status_code}")
    if resp.status_code != 200:
        logger.warning(f"Seasons API retornou {resp.status_code}: {resp.text[:500]}")
        return []
    data = resp.json()
    seasons = data.get("seasons", [])
    logger.debug(f"Temporadas encontradas: {len(seasons)}")
    return seasons

def extract_episodes_from_series_data(series_data):
    series_title = series_data.get("name", "Desconhecido")
    series_id = series_data.get("id") or series_data.get("_id", "")
    episodes = []
    for season in series_data.get("seasons", []):
        season_num = season.get("seasonNumber") or season.get("number")
        season_id = season.get("_id") or season.get("id", "")
        for ep in season.get("episodes", []):
            ep_id = ep.get("_id") or ep.get("id")
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
    logger.debug(f"Episódios extraídos: {len(episodes)}")
    return episodes

def write_output_file(series_title, episodes):
    if not episodes:
        logger.warning("Nenhum episódio para salvar.")
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
    match = re.search(r"/series/([a-f0-9]+)", user_input)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-f0-9]+", user_input, re.I):
        return user_input
    raise ValueError("Formato inválido. Forneça URL ou ID hexadecimal")

def save_debug_response(filename, content):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    logger.debug(f"Resposta salva em {filename}")

def main():
    series_id = extract_id_from_input(SERIES_URL_OR_ID.strip())
    logger.info(f"Processando série ID: {series_id}")

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

    device_id = FIXED_DEVICE_ID
    jwt_token = get_jwt_token(session, device_id)

    # Estratégia 1: boot.pluto.tv
    series_data = fetch_series_via_boot(session, device_id, jwt_token, series_id)

    # Estratégia 2: VOD API (se boot falhar)
    if not series_data:
        logger.info("Tentando abordagem alternativa via VOD API...")
        series_data = fetch_series_via_vod_api(session, series_id, jwt_token, device_id)
        if series_data:
            seasons = fetch_seasons_via_vod_api(session, series_id, jwt_token, device_id)
            series_data["seasons"] = seasons
        else:
            logger.error("VOD API também não encontrou a série. Verifique os logs e o arquivo vod_error.json")
            resp = session.get(f"{VOD_API_BASE}/items", params={"ids": series_id})
            save_debug_response("vod_error.json", resp.text)

    if not series_data:
        raise ValueError("Nenhuma das APIs retornou dados da série. Verifique os logs acima.")

    series_title = series_data.get("name", "Série Desconhecida")
    episodes = extract_episodes_from_series_data(series_data)
    write_output_file(series_title, episodes)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception("Erro fatal")
        sys.exit(1)
