#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import re
import sys
import os
import time
import base64
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

import yaml
from playwright.async_api import async_playwright, Page, Response, Request, Route
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("pluto_sniffer")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
SERIES_ID_PATTERN = re.compile(r"[a-f0-9]{24}")

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
        logger.warning("Usando configurações padrão mínimas.")
        return {
            "series_input": os.environ.get("SERIES_INPUT", "66d70dfaf98f52001332a8f5"),
            "output_dir": "./output",
            "cookies_file": "",
            "geo": {"latitude": -23.5505, "longitude": -46.6333, "accuracy": 100},
            "locale": "pt-BR",
            "timezone": "America/Sao_Paulo",
            "headless": True,
            "timeout": 60000,
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

def extract_episodes_from_data(data: dict, series_id: str) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    for key in ["VOD", "vod", "series", "item", "data"]:
        if key in data:
            for item in data[key] if isinstance(data[key], list) else [data[key]]:
                if isinstance(item, dict) and item.get("id") == series_id:
                    return item
    if data.get("id") == series_id and "seasons" in data:
        return data
    for value in data.values():
        if isinstance(value, dict):
            result = extract_episodes_from_data(value, series_id)
            if result:
                return result
        elif isinstance(value, list):
            for v in value:
                if isinstance(v, dict):
                    result = extract_episodes_from_data(v, series_id)
                    if result:
                        return result
    return None

def extract_episodes_info(series_data: dict) -> List[dict]:
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
        self.timeout = config.get("timeout", 60000)
        self.debug_mode = config.get("debug_mode", True)

        self.captured_series_data: Optional[dict] = None
        self.captured_responses: List[dict] = []
        self.captured_requests: List[Request] = []
        self.cookies_from_browser: List[Dict] = []
        self.local_storage: Dict = {}

    async def handle_response(self, response: Response):
        url = response.url
        content_type = response.headers.get("content-type", "")
        logger.debug(f"Response: {response.status} {url} [{content_type}]")
        if "application/json" in content_type or "text/plain" in content_type:
            try:
                data = await response.json()
                self.captured_responses.append({"url": url, "data": data})
                if "seasons" in json.dumps(data) and "episodes" in json.dumps(data):
                    logger.info(f"Resposta com episódios detectada: {url}")
                    series = extract_episodes_from_data(data, self.series_id)
                    if series:
                        self.captured_series_data = series
                        logger.info("Dados da série extraídos de resposta JSON.")
            except:
                pass

    async def handle_request(self, request: Request):
        self.captured_requests.append(request)

    async def extract_from_all_dom_sources(self, page: Page) -> Optional[dict]:
        logger.info("Vasculhando DOM por dados embutidos...")
        sources_to_try = [
            "window.__INITIAL_STATE__",
            "window.__NEXT_DATA__",
            "window.__PRELOADED_STATE__",
            "window.__APOLLO_STATE__",
            "window.__REDUX_STATE__",
            "window.__STATE__",
            "window.__DATA__",
        ]
        for var in sources_to_try:
            try:
                state = await page.evaluate(f"() => {var}")
                if state:
                    logger.info(f"Dados encontrados em {var}")
                    series = extract_episodes_from_data(state, self.series_id)
                    if series:
                        return series
            except:
                pass
        try:
            script_tags = await page.evaluate("""() => {
                const scripts = Array.from(document.querySelectorAll('script[type="application/json"], script[type="text/json"], script[type="application/ld+json"]'));
                return scripts.map(s => s.textContent);
            }""")
            for content in script_tags:
                try:
                    data = json.loads(content)
                    series = extract_episodes_from_data(data, self.series_id)
                    if series:
                        logger.info("Dados extraídos de tag script JSON.")
                        return series
                except:
                    pass
        except:
            pass
        return None

    async def fallback_direct_api_call(self) -> Optional[dict]:
        logger.info("Tentando fallback: chamada direta à API boot com requests...")
        cookies_dict = {c["name"]: c["value"] for c in self.cookies_from_browser}
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"https://pluto.tv/br/on-demand/series/{self.series_id}",
            "Origin": "https://pluto.tv",
        }
        params = {
            "appName": "web",
            "appVersion": "9.20.0-89258290264838515e264f5b051b7c1602a58482",
            "deviceType": "web",
            "deviceMake": "firefox",
            "deviceModel": "web",
            "deviceVersion": "149.0",
            "clientID": str(uuid.uuid4()) if "uuid" in sys.modules else "test-client-id",
            "deviceId": "test-device-id",
            "sessionID": "test-session-id",
            "marketingRegion": "BR",
            "country": "BR",
            "deviceLat": str(self.geo["latitude"]),
            "deviceLon": str(self.geo["longitude"]),
            "seriesIDs": self.series_id,
            "geoOverride": "BR",
        }
        try:
            import uuid
            params["clientID"] = str(uuid.uuid4())
            params["deviceId"] = params["clientID"]
            params["sessionID"] = params["clientID"]
        except:
            pass
        session = requests.Session()
        for name, value in cookies_dict.items():
            session.cookies.set(name, value, domain=".pluto.tv")
        resp = session.get("https://boot.pluto.tv/v4/start", headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            series = extract_episodes_from_data(data, self.series_id)
            if series:
                logger.info("Dados obtidos via fallback direto com sucesso!")
                return series
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
                "--window-size=1920,1080",
            ]
            browser = await p.chromium.launch(headless=self.headless, args=launch_args)

            context_kwargs = {
                "user_agent": USER_AGENT,
                "locale": self.locale,
                "timezone_id": self.timezone,
                "geolocation": self.geo,
                "permissions": ["geolocation"],
                "viewport": {"width": 1280, "height": 720},
                "extra_http_headers": {
                    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
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
            page.on("request", self.handle_request)

            await page.route("**/*", lambda route: route.continue_())

            series_url = f"https://pluto.tv/br/on-demand/series/{self.series_id}?lang=pt"
            logger.info(f"Acessando {series_url}")
            try:
                response = await page.goto(series_url, timeout=self.timeout, wait_until="networkidle")
                logger.info(f"Status: {response.status if response else 'desconhecido'}")
            except Exception as e:
                logger.error(f"Erro ao carregar página: {e}")

            await page.wait_for_timeout(8000)

            for _ in range(3):
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            self.cookies_from_browser = await context.cookies()
            self.local_storage = await page.evaluate("() => JSON.parse(JSON.stringify(localStorage))")

            if not self.captured_series_data:
                self.captured_series_data = await self.extract_from_all_dom_sources(page)

            if not self.captured_series_data and self.captured_responses:
                logger.info("Procurando em respostas capturadas...")
                for item in self.captured_responses:
                    series = extract_episodes_from_data(item["data"], self.series_id)
                    if series:
                        self.captured_series_data = series
                        break

            if not self.captured_series_data:
                logger.warning("Nenhum dado encontrado via navegador. Tentando fallback direto...")
                self.captured_series_data = await self.fallback_direct_api_call()

            if not self.captured_series_data:
                logger.error("Falha total: dados da série não localizados.")
                if self.debug_mode:
                    await page.screenshot(path="error_screenshot.png", full_page=True)
                    html = await page.content()
                    with open("error_page.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    with open("captured_responses.json", "w", encoding="utf-8") as f:
                        json.dump(self.captured_responses, f, indent=2, default=str)
                    logger.info("Arquivos de debug salvos.")
                await browser.close()
                sys.exit(1)

            episodes = extract_episodes_info(self.captured_series_data)
            series_title = self.captured_series_data.get("name", "Série Desconhecida")
            write_output_file(series_title, episodes, self.output_dir)

            await browser.close()

async def main():
    config = load_config()
    if len(sys.argv) > 1:
        config["series_input"] = sys.argv[1]
    elif os.environ.get("SERIES_INPUT"):
        config["series_input"] = os.environ["SERIES_INPUT"]
    sniffer = PlutoSniffer(config)
    await sniffer.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrompido.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Erro fatal.")
        sys.exit(1)
