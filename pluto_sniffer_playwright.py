#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pluto TV Sniffer com Playwright
Captura informações de séries on-demand do Pluto TV através da interface web.
Autor: Assistente
Requer: Python 3.8+, playwright, pyyaml
"""

import asyncio
import json
import logging
import re
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from playwright.async_api import async_playwright, BrowserContext, Page, Response

# ----------------------------------------------------------------------
# Configuração de logging
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("pluto_sniffer")

# ----------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
BOOT_API_PATTERN = re.compile(r"https://boot\.pluto\.tv/v4/start\?.*seriesIDs=([a-f0-9]+)")
DEFAULT_CONFIG_PATH = Path("config.yml")

# ----------------------------------------------------------------------
# Funções auxiliares
# ----------------------------------------------------------------------
def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Carrega as configurações do arquivo YAML."""
    if not config_path.exists():
        logger.warning(f"Arquivo de configuração {config_path} não encontrado. Usando padrões.")
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def extract_series_id(user_input: str) -> str:
    """Extrai o ID da série a partir de uma URL ou ID puro."""
    match = re.search(r"/series/([a-f0-9]+)", user_input)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-f0-9]+", user_input, re.I):
        return user_input
    raise ValueError(f"Formato inválido para série: {user_input}")

def parse_netscape_cookies(content: str) -> List[Dict]:
    """Converte cookies no formato Netscape para lista compatível com Playwright."""
    cookies = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _, path, secure, expires, name, value = parts
        cookie = {
            "name": name.strip(),
            "value": value.strip(),
            "domain": domain.strip(),
            "path": path.strip(),
            "secure": secure.strip().upper() == "TRUE",
            "httpOnly": False,  # não temos essa informação
        }
        if expires.strip() and expires.strip() != "0":
            cookie["expires"] = int(expires.strip())
        cookies.append(cookie)
    return cookies

def safe_filename(text: str) -> str:
    """Substitui espaços por underline e remove caracteres inválidos."""
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    return text or "serie_sem_nome"

def extract_episodes_data(series_data: dict) -> List[dict]:
    """Extrai informações detalhadas de todos os episódios."""
    series_title = series_data.get("name", "Desconhecido")
    series_id = series_data.get("id", "")
    episodes = []

    for season in series_data.get("seasons", []):
        season_num = season.get("seasonNumber")
        if season_num is None:
            season_num = 0
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
                "episode_id": ep_id,
            })

    episodes.sort(key=lambda x: (x["season_number"], x["episode_number"]))
    return episodes

def write_output_file(series_title: str, episodes: List[dict], output_dir: Path):
    """Gera arquivo .txt com os dados tabulados."""
    if not episodes:
        logger.warning("Nenhum episódio para salvar.")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(series_title) + ".txt"
    filepath = output_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("Series_Title\tSeason_Number\tEpisode_Number\tEpisode_Title\tSeries_ID\tSeason_ID\tEpisode_ID\n")
        for ep in episodes:
            f.write(
                f"{ep['series_title']}\t"
                f"{ep['season_number']}\t"
                f"{ep['episode_number']}\t"
                f"{ep['episode_title']}\t"
                f"{ep['series_id']}\t"
                f"{ep['season_id']}\t"
                f"{ep['episode_id']}\n"
            )

    logger.info(f"Arquivo salvo: {filepath} ({len(episodes)} episódios)")

# ----------------------------------------------------------------------
# Núcleo do sniffer com Playwright
# ----------------------------------------------------------------------
class PlutoSniffer:
    def __init__(self, config: dict):
        self.config = config
        self.series_input = config.get("series_input")
        if not self.series_input:
            raise ValueError("Configuração 'series_input' é obrigatória.")
        self.series_id = extract_series_id(self.series_input)
        self.output_dir = Path(config.get("output_dir", "./output"))
        self.cookies_file = config.get("cookies_file")
        self.geo = config.get("geo", {"latitude": -23.5505, "longitude": -46.6333})
        self.locale = config.get("locale", "pt-BR")
        self.timezone = config.get("timezone", "America/Sao_Paulo")
        self.headless = config.get("headless", True)
        self.timeout = config.get("timeout", 30000)

        self.captured_series_data: Optional[dict] = None

    async def handle_response(self, response: Response):
        """Callback para capturar a resposta da API que contém os dados da série."""
        url = response.url
        if not BOOT_API_PATTERN.search(url):
            return

        if f"seriesIDs={self.series_id}" not in url:
            return

        try:
            data = await response.json()
        except Exception:
            return

        vod_list = data.get("VOD", [])
        for item in vod_list:
            if item.get("id") == self.series_id:
                self.captured_series_data = item
                logger.info("Dados da série capturados com sucesso!")
                return

    async def run(self):
        """Executa o processo de captura."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--disable-gpu"
                ]
            )
            
            context_kwargs = {
                "user_agent": USER_AGENT,
                "locale": self.locale,
                "timezone_id": self.timezone,
                "geolocation": self.geo,
                "permissions": ["geolocation"],
                "viewport": {"width": 1280, "height": 720},
            }

            if self.cookies_file:
                cookie_path = Path(self.cookies_file)
                if cookie_path.exists():
                    with open(cookie_path, "r", encoding="utf-8") as f:
                        cookie_content = f.read()
                    cookies = parse_netscape_cookies(cookie_content)
                    context_kwargs["storage_state"] = {"cookies": cookies}
                    logger.info(f"Cookies carregados de {self.cookies_file}")

            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()

            page.on("response", self.handle_response)

            series_url = f"https://pluto.tv/br/on-demand/series/{self.series_id}"
            logger.info(f"Acessando {series_url}")
            try:
                await page.goto(series_url, timeout=self.timeout)
                await page.wait_for_selector("h1", timeout=10000)
            except Exception as e:
                logger.error(f"Erro ao carregar a página: {e}")

            await page.wait_for_timeout(3000)

            if not self.captured_series_data:
                logger.error("Não foi possível capturar os dados da série via API.")
                await browser.close()
                sys.exit(1)

            episodes = extract_episodes_data(self.captured_series_data)
            series_title = self.captured_series_data.get("name", "Série Desconhecida")
            write_output_file(series_title, episodes, self.output_dir)

            await browser.close()

# ----------------------------------------------------------------------
# Ponto de entrada
# ----------------------------------------------------------------------
async def main():
    config = load_config()
    # Permite sobrescrever a entrada da série via argumento de linha de comando
    if len(sys.argv) > 1:
        config["series_input"] = sys.argv[1]
        logger.info(f"Usando argumento da linha de comando: {sys.argv[1]}")
    # Também verifica variável de ambiente SERIES_INPUT (útil no GitHub Actions)
    elif os.environ.get("SERIES_INPUT"):
        config["series_input"] = os.environ["SERIES_INPUT"]
        logger.info(f"Usando variável de ambiente SERIES_INPUT: {os.environ['SERIES_INPUT']}")
    
    sniffer = PlutoSniffer(config)
    await sniffer.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Execução interrompida pelo usuário.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Erro fatal durante execução.")
        sys.exit(1)
