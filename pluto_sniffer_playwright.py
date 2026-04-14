#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pluto TV Sniffer - Versão Robusta com Cookies
Captura informações de séries on-demand do Pluto TV utilizando a API oficial.
Requer a variável de ambiente PLUTO_COOKIES ou um arquivo de cookies.
"""

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
VOD_API_URL = "https://service-vod.clusters.pluto.tv/v4/vod/series/{series_id}/seasons"

CONFIG_SEARCH_PATHS = [
    Path("config.yml"),
    Path(".github/workflows/config.yml"),
    Path("..") / "config.yml",
]

def find_config_file() -> Optional[Path]:
    for p in CONFIG_SEARCH_PATHS:
        if p.exists():
            logger.info(f"Configuração encontrada em: {p.absolute()}")
            return p
    logger.error("Arquivo config.yml não localizado.")
    return None

def load_config(config_path: Optional[Path] = None) -> dict:
    if config_path is None:
        config_path = find_config_file()
    if config_path is None or not config_path.exists():
        logger.warning("Usando configurações padrão.")
        return {
            "series_input": os.environ.get("SERIES_INPUT", "66d70dfaf98f52001332a8f5"),
            "output_dir": "./output",
            "cookies_file": "",
            "geo": {"latitude": -23.5505, "longitude": -46.6333, "accuracy": 100},
            "locale": "pt-BR",
            "timezone": "America/Sao_Paulo",
            "debug_mode": True
        }
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        return data

def extract_series_id(user_input: str) -> str:
    match = re.search(r"/series/([a-f0-9]+)", user_input)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-f0-9]+", user_input, re.I):
        return user_input
    raise ValueError(f"Formato inválido para série: {user_input}")

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
    """Obtém o token JWT necessário para as requisições autenticadas."""
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
    logger.info("Obtendo token de sessão...")
    resp = session.get(BOOT_URL, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("sessionToken")
    if not token:
        raise ValueError("sessionToken não encontrado na resposta.")
    logger.info("Token de sessão obtido com sucesso.")
    return token

def fetch_seasons(session: requests.Session, series_id: str, token: str) -> dict:
    """Busca os dados das temporadas e episódios da série."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Referer": f"https://pluto.tv/br/on-demand/series/{series_id}",
        "Origin": "https://pluto.tv",
    }
    params = {
        "offset": 1000,
        "page": 1,
    }
    url = VOD_API_URL.format(series_id=series_id)
    logger.info(f"Buscando temporadas em: {url}")
    resp = session.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()

def extract_episodes(seasons_data: dict, series_id: str) -> List[dict]:
    """Extrai e organiza as informações de todos os episódios."""
    series_title = seasons_data.get("name", "Desconhecido")
    episodes = []
    for season in seasons_data.get("seasons", []):
        season_num = season.get("number")
        if season_num is None:
            season_num = 0
        season_slug = season.get("slug", "")
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
                "season_slug": season_slug,
                "episode_number": ep_number,
                "episode_title": ep_title,
                "episode_id": ep_id,
            })
    episodes.sort(key=lambda x: (x["season_number"], x["episode_number"]))
    return episodes

def write_output_file(series_title: str, episodes: List[dict], output_dir: Path):
    """Salva os episódios em um arquivo .txt."""
    if not episodes:
        logger.warning("Nenhum episódio para salvar.")
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
        logger.error("Nenhuma série especificada.")
        sys.exit(1)

    series_id = extract_series_id(series_input)
    output_dir = Path(config.get("output_dir", "./output"))
    cookies_file = config.get("cookies_file")
    geo = config.get("geo", {"latitude": -23.5505, "longitude": -46.6333})
    debug_mode = config.get("debug_mode", True)

    # --- LEITURA DOS COOKIES (CRUCIAL) ---
    cookie_content = os.environ.get("PLUTO_COOKIES", "")
    if not cookie_content and cookies_file:
        cookie_path = Path(cookies_file)
        if cookie_path.exists():
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookie_content = f.read()
                logger.info(f"Cookies carregados do arquivo: {cookies_file}")

    if not cookie_content:
        logger.error("PLUTO_COOKIES não definido no ambiente e arquivo de cookies não encontrado.")
        sys.exit(1)

    cookies = parse_netscape_cookies(cookie_content)
    if not cookies:
        logger.error("Nenhum cookie válido encontrado.")
        sys.exit(1)
    # --- FIM DA LEITURA DOS COOKIES ---

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".pluto.tv")

    device_id = str(uuid.uuid4())
    try:
        token = get_jwt_token(session, device_id, geo)
        seasons_data = fetch_seasons(session, series_id, token)

        if debug_mode:
            debug_file = Path("seasons_debug.json")
            with open(debug_file, "w", encoding="utf-8") as f:
                json.dump(seasons_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Dados brutos salvos em {debug_file}")

        episodes = extract_episodes(seasons_data, series_id)
        series_title = seasons_data.get("name", "Série Desconhecida")
        write_output_file(series_title, episodes, output_dir)

    except Exception as e:
        logger.exception("Erro durante a execução.")
        sys.exit(1)

if __name__ == "__main__":
    main()
