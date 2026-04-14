#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import re
import sys
import os
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

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0"
SERIES_PAGE_URL = "https://pluto.tv/br/on-demand/series/{series_id}/details"
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

def extract_series_data_from_html(html: str) -> Optional[dict]:
    # Tenta extrair de window.__INITIAL_STATE__
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            # Navega até os dados da série
            series = data.get("vod", {}).get("series", {})
            if series and series.get("seasons"):
                return series
        except:
            pass

    # Tenta encontrar em tags <script type="application/json">
    script_matches = re.findall(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
    for script_content in script_matches:
        try:
            data = json.loads(script_content)
            if isinstance(data, dict):
                series = data.get("vod", {}).get("series", {})
                if series and series.get("seasons"):
                    return series
        except:
            pass

    # Tenta encontrar qualquer JSON grande que contenha "seasons"
    json_matches = re.findall(r'({[^<]*"seasons"\s*:\s*\[.*?\][^<]*})', html, re.DOTALL)
    for json_str in json_matches:
        try:
            data = json.loads(json_str)
            if "seasons" in data:
                return data
        except:
            pass

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
    debug_mode = config.get("debug_mode", True)

    # Carregar cookies
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

    page_url = SERIES_PAGE_URL.format(series_id=series_id)
    logger.info(f"Baixando página: {page_url}")
    try:
        resp = session.get(page_url, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.exception("Falha ao baixar a página.")
        sys.exit(1)

    series_data = extract_series_data_from_html(html)
    if not series_data:
        logger.error("Não foi possível extrair os dados da série do HTML.")
        if debug_mode:
            with open("page_debug.html", "w", encoding="utf-8") as f:
                f.write(html)
            logger.info("HTML salvo em page_debug.html")
        sys.exit(1)

    if debug_mode:
        with open("series_debug.json", "w", encoding="utf-8") as f:
            json.dump(series_data, f, indent=2, ensure_ascii=False)
        logger.info("Dados da série salvos em series_debug.json")

    episodes = extract_episodes(series_data, series_id)
    write_output_file(series_data.get("name", "Série Desconhecida"), episodes, output_dir)

if __name__ == "__main__":
    main()
