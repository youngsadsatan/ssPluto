#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import re
import sys
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import requests
import yaml

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("pluto_sniffer")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"
VOD_API_V3_SLUG = "https://service-vod.clusters.pluto.tv/v3/vod/slugs/{slug}"
VOD_API_V4_SEASONS = "https://service-vod.clusters.pluto.tv/v4/vod/series/{series_id}/seasons"
CONFIG_SEARCH_PATHS = [
    Path("config.yml"),
    Path(".github/workflows/config.yml"),
]

def find_config_file() -> Optional[Path]:
    for p in CONFIG_SEARCH_PATHS:
        if p.exists():
            return p
    return None

def load_config(config_path: Optional[Path] = None) -> dict:
    if config_path is None:
        config_path = find_config_file()
    if config_path is None or not config_path.exists():
        logger.warning("Configuração não encontrada, usando padrões.")
        return {
            "series_input": os.environ.get("SERIES_INPUT", "66d70dfaf98f52001332a8f5"),
            "output_dir": "./output",
            "cookies_file": "",
            "geo": {"latitude": -23.5505, "longitude": -46.6333},
            "debug_mode": True
        }
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def extract_series_id(user_input: str) -> str:
    match = re.search(r"/series/([a-f0-9]+)", user_input)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-f0-9]+", user_input, re.I):
        return user_input
    raise ValueError(f"Formato inválido: {user_input}")

def parse_netscape_cookies(content: str) -> Dict[str, str]:
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

def safe_filename(text: str) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    return text or "serie_sem_nome"

def get_jwt_token(session: requests.Session, device_id: str, geo: dict) -> str:
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
        "deviceLat": str(geo.get("latitude", -23.5505)),
        "deviceLon": str(geo.get("longitude", -46.6333)),
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
    }
    logger.info("Obtendo token JWT...")
    resp = session.get(BOOT_URL, headers=headers, params=params)
    resp.raise_for_status()
    token = resp.json().get("sessionToken")
    if not token:
        raise ValueError("sessionToken não encontrado.")
    logger.info("Token obtido.")
    return token

def fetch_seasons_v4(session: requests.Session, series_id: str, token: str) -> dict:
    """Endpoint funcional: /v4/vod/series/{id}/seasons"""
    url = VOD_API_V4_SEASONS.format(series_id=series_id)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Referer": f"https://pluto.tv/br/on-demand/series/{series_id}",
        "Origin": "https://pluto.tv",
    }
    params = {"offset": 1000, "page": 1}
    logger.info(f"Consultando API v4: {url}")
    resp = session.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()

def fetch_series_v3(session: requests.Session, slug: str, token: str) -> dict:
    """API v3 por slug textual (ex: 'anger-management')"""
    url = VOD_API_V3_SLUG.format(slug=slug)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Referer": f"https://pluto.tv/br/on-demand/series/{slug}",
        "Origin": "https://pluto.tv",
    }
    params = {
        "appName": "web",
        "appVersion": FIXED_APP_VERSION,
        "deviceType": "web",
        "deviceMake": "firefox",
        "deviceModel": "web",
        "deviceVersion": "149.0",
        "clientID": str(uuid.uuid4()),
        "deviceId": str(uuid.uuid4()),
        "sessionID": str(uuid.uuid4()),
        "marketingRegion": "BR",
        "country": "BR",
        "geoOverride": "BR",
    }
    logger.info(f"Consultando API v3: {url}")
    resp = session.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()

def extract_slug_from_page(session: requests.Session, series_id: str) -> Optional[str]:
    """Extrai o slug textual da página da série."""
    url = f"https://pluto.tv/br/on-demand/series/{series_id}"
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"}
    try:
        resp = session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text
        # Procura por padrões como: "slug":"anger-management"
        match = re.search(r'"slug"\s*:\s*"([a-z0-9-]+)"', html)
        if match:
            slug = match.group(1)
            logger.info(f"Slug extraído: {slug}")
            return slug
        # Fallback: tenta extrair de __INITIAL_STATE__
        match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            slug = data.get("vod", {}).get("series", {}).get("slug")
            if slug:
                logger.info(f"Slug via __INITIAL_STATE__: {slug}")
                return slug
    except Exception as e:
        logger.warning(f"Falha ao extrair slug: {e}")
    return None

def extract_episodes(series_data: dict, series_id: str) -> List[dict]:
    series_title = series_data.get("name", "Desconhecido")
    episodes = []
    for season in series_data.get("seasons", []):
        season_num = season.get("number", 0)
        season_slug = season.get("slug", "")
        for ep in season.get("episodes", []):
            ep_id = ep.get("_id")
            ep_num = ep.get("number")
            if not ep_id or ep_num is None:
                continue
            episodes.append({
                "series_title": series_title,
                "series_id": series_id,
                "season_number": season_num,
                "season_slug": season_slug,
                "episode_number": ep_num,
                "episode_title": ep.get("name", "Sem título"),
                "episode_id": ep_id,
            })
    episodes.sort(key=lambda x: (x["season_number"], x["episode_number"]))
    return episodes

def write_output_file(series_title: str, episodes: List[dict], output_dir: Path):
    if not episodes:
        logger.warning("Nenhum episódio encontrado.")
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(series_title) + ".txt"
    filepath = output_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("Series_Title\tSeason_Number\tEpisode_Number\tEpisode_Title\tSeries_ID\tSeason_Slug\tEpisode_ID\n")
        for ep in episodes:
            f.write(
                f"{ep['series_title']}\t"
                f"{ep['season_number']}\t"
                f"{ep['episode_number']}\t"
                f"{ep['episode_title']}\t"
                f"{ep['series_id']}\t"
                f"{ep['season_slug']}\t"
                f"{ep['episode_id']}\n"
            )
    logger.info(f"Arquivo salvo: {filepath} ({len(episodes)} episódios)")

def main():
    config = load_config()
    series_input = config.get("series_input")
    if len(sys.argv) > 1:
        series_input = sys.argv[1]
    elif os.environ.get("SERIES_INPUT"):
        series_input = os.environ["SERIES_INPUT"]
    if not series_input:
        logger.error("Nenhuma série informada.")
        sys.exit(1)

    series_id = extract_series_id(series_input)
    output_dir = Path(config.get("output_dir", "./output"))
    cookies_file = config.get("cookies_file")
    geo = config.get("geo", {"latitude": -23.5505, "longitude": -46.6333})
    debug_mode = config.get("debug_mode", True)

    # Carrega cookies
    cookie_content = os.environ.get("PLUTO_COOKIES", "")
    if not cookie_content and cookies_file:
        cookie_path = Path(cookies_file)
        if cookie_path.exists():
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookie_content = f.read()
    if not cookie_content:
        logger.error("PLUTO_COOKIES não definido e arquivo de cookies não encontrado.")
        sys.exit(1)

    cookies = parse_netscape_cookies(cookie_content)
    if not cookies:
        logger.error("Nenhum cookie válido.")
        sys.exit(1)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".pluto.tv")

    device_id = str(uuid.uuid4())
    try:
        token = get_jwt_token(session, device_id, geo)

        # Tenta primeiro a API v4 com /seasons (endpoint confirmado funcional)
        series_data = None
        try:
            series_data = fetch_seasons_v4(session, series_id, token)
            logger.info("Dados obtidos via API v4 /seasons.")
        except Exception as e:
            logger.warning(f"API v4 falhou: {e}")

        # Se falhar, tenta extrair slug e usar API v3
        if not series_data:
            slug = extract_slug_from_page(session, series_id)
            if slug:
                try:
                    series_data = fetch_series_v3(session, slug, token)
                    logger.info("Dados obtidos via API v3.")
                except Exception as e:
                    logger.warning(f"API v3 falhou: {e}")

        if not series_data:
            logger.error("Nenhuma API retornou dados da série.")
            sys.exit(1)

        if debug_mode:
            with open("seasons_debug.json", "w", encoding="utf-8") as f:
                json.dump(series_data, f, indent=2, ensure_ascii=False)
            logger.info("Debug salvo em seasons_debug.json")

        episodes = extract_episodes(series_data, series_id)
        write_output_file(series_data.get("name", "Série Desconhecida"), episodes, output_dir)

    except Exception as e:
        logger.exception("Erro fatal.")
        sys.exit(1)

if __name__ == "__main__":
    main()
