#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import re
import sys
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml
from playwright.async_api import async_playwright, BrowserContext, Page, Response, Request, Route

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("pluto_sniffer")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
BOOT_API_PATTERN = re.compile(r"https?://boot\.pluto\.tv/v4/start")
SERIES_ID_PATTERN = re.compile(r"[a-f0-9]{24}")

CONFIG_SEARCH_PATHS = [
    Path("config.yml"),
    Path(".github/workflows/config.yml"),
    Path("..") / "config.yml",
    Path("/home/runner/work") / "config.yml",
]

def find_config_file() -> Optional[Path]:
    for p in CONFIG_SEARCH_PATHS:
        if p.exists():
            logger.info(f"Configuração encontrada em: {p.absolute()}")
            return p
    logger.error("Arquivo config.yml não localizado em nenhum caminho esperado.")
    return None

def load_config(config_path: Optional[Path] = None) -> dict:
    if config_path is None:
        config_path = find_config_file()
    if config_path is None or not config_path.exists():
        logger.warning("Usando configurações padrão mínimas.")
        return {
            "series_input": os.environ.get("SERIES_INPUT", "66d70dfaf98f52001332a8f5"),
            "output_dir": "./output",
            "cookies_file": "",
            "geo": {"latitude": -23.5505, "longitude": -46.6333, "accuracy": 100},
            "locale": "pt-BR",
            "timezone": "America/Sao_Paulo",
            "headless": True,
            "timeout": 45000,
            "debug_mode": True
        }
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        logger.info(f"Configuração carregada: {json.dumps(data, indent=2)}")
        return data

def extract_series_id(user_input: str) -> str:
    match = re.search(r"/series/([a-f0-9]+)", user_input)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-f0-9]+", user_input, re.I):
        return user_input
    raise ValueError(f"Formato inválido para série: {user_input}")

def parse_netscape_cookies(content: str) -> List[Dict]:
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
            "httpOnly": False,
        }
        if expires.strip() and expires.strip() != "0":
            cookie["expires"] = int(expires.strip())
        cookies.append(cookie)
    return cookies

def safe_filename(text: str) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    return text or "serie_sem_nome"

def extract_episodes_data(series_data: dict) -> List[dict]:
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
        self.timeout = config.get("timeout", 45000)
        self.debug_mode = config.get("debug_mode", False)

        self.captured_series_data: Optional[dict] = None
        self.captured_responses: List[dict] = []

    async def handle_response(self, response: Response):
        url = response.url
        logger.debug(f"Resposta recebida: {response.status} {url}")
        if BOOT_API_PATTERN.search(url):
            logger.info(f"Resposta da API boot interceptada: {url}")
            try:
                data = await response.json()
                self.captured_responses.append(data)
                vod_list = data.get("VOD", [])
                for item in vod_list:
                    if item.get("id") == self.series_id:
                        self.captured_series_data = item
                        logger.info("Dados da série capturados via API boot!")
                        return
            except Exception as e:
                logger.error(f"Erro ao processar JSON da resposta: {e}")

    async def handle_route(self, route: Route, request: Request):
        logger.debug(f"Requisição: {request.method} {request.url}")
        await route.continue_()

    async def extract_from_dom(self, page: Page) -> Optional[dict]:
        logger.info("Tentando extrair dados do DOM (__INITIAL_STATE__)...")
        try:
            state = await page.evaluate("() => window.__INITIAL_STATE__")
            if state and isinstance(state, dict):
                vod = state.get("vod", {})
                series = vod.get("series", {})
                if series and series.get("id") == self.series_id:
                    logger.info("Dados da série extraídos do __INITIAL_STATE__ com sucesso!")
                    return series
        except Exception as e:
            logger.error(f"Falha ao extrair do DOM: {e}")
        try:
            script_content = await page.evaluate("() => { const s = document.querySelector('script[type=\"application/json\"]'); return s ? s.textContent : null; }")
            if script_content:
                data = json.loads(script_content)
                if isinstance(data, dict):
                    vod = data.get("vod", {})
                    series = vod.get("series", {})
                    if series and series.get("id") == self.series_id:
                        logger.info("Dados da série extraídos de tag script JSON com sucesso!")
                        return series
        except Exception as e:
            logger.error(f"Falha ao extrair de script JSON: {e}")
        return None

    async def run(self):
        async with async_playwright() as p:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--window-size=1920,1080",
            ]
            if self.debug_mode:
                launch_args.append("--auto-open-devtools-for-tabs")
            browser = await p.chromium.launch(
                headless=self.headless,
                args=launch_args
            )

            context_kwargs = {
                "user_agent": USER_AGENT,
                "locale": self.locale,
                "timezone_id": self.timezone,
                "geolocation": self.geo,
                "permissions": ["geolocation"],
                "viewport": {"width": 1280, "height": 720},
                "extra_http_headers": {
                    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Referer": "https://pluto.tv/",
                    "Origin": "https://pluto.tv",
                }
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
            await page.route("**/*", self.handle_route)

            series_url = f"https://pluto.tv/br/on-demand/series/{self.series_id}"
            logger.info(f"Acessando {series_url}")
            try:
                response = await page.goto(series_url, timeout=self.timeout, wait_until="domcontentloaded")
                logger.info(f"Página carregada com status {response.status if response else 'desconhecido'}")
                await page.wait_for_selector("h1", timeout=15000)
                logger.info("Elemento H1 encontrado na página.")
            except Exception as e:
                logger.error(f"Erro ao carregar a página: {e}")

            await page.wait_for_timeout(5000)

            if not self.captured_series_data:
                logger.warning("API não capturada, tentando extrair do DOM...")
                dom_data = await self.extract_from_dom(page)
                if dom_data:
                    self.captured_series_data = dom_data

            if not self.captured_series_data and self.captured_responses:
                logger.info("Procurando dados da série nas respostas capturadas...")
                for resp_data in self.captured_responses:
                    vod_list = resp_data.get("VOD", [])
                    for item in vod_list:
                        if item.get("id") == self.series_id:
                            self.captured_series_data = item
                            logger.info("Dados encontrados em resposta armazenada.")
                            break
                    if self.captured_series_data:
                        break

            if not self.captured_series_data:
                logger.error("Não foi possível capturar os dados da série por nenhum método.")
                if self.debug_mode:
                    screenshot_path = "error_screenshot.png"
                    await page.screenshot(path=screenshot_path, full_page=True)
                    logger.info(f"Screenshot salva em {screenshot_path}")
                    html_content = await page.content()
                    with open("error_page.html", "w", encoding="utf-8") as f:
                        f.write(html_content)
                    logger.info("HTML da página salvo em error_page.html")
                await browser.close()
                sys.exit(1)

            episodes = extract_episodes_data(self.captured_series_data)
            series_title = self.captured_series_data.get("name", "Série Desconhecida")
            write_output_file(series_title, episodes, self.output_dir)

            await browser.close()

async def main():
    config = load_config()
    if len(sys.argv) > 1:
        config["series_input"] = sys.argv[1]
        logger.info(f"Argumento de linha de comando: {sys.argv[1]}")
    elif os.environ.get("SERIES_INPUT"):
        config["series_input"] = os.environ["SERIES_INPUT"]
        logger.info(f"Variável SERIES_INPUT: {os.environ['SERIES_INPUT']}")

    sniffer = PlutoSniffer(config)
    await sniffer.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Execução interrompida.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Erro fatal.")
        sys.exit(1)
