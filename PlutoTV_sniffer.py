#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import uuid
import re
import requests
from urllib.parse import urlencode

# ============================================================
# CONFIGURAÇÕES FIXAS
# ============================================================
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
FIXED_APP_VERSION = "9.20.0-89258290264838515e264f5b051b7c1602a58482"
BOOT_URL = "https://boot.pluto.tv/v4/start"

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================
def parse_netscape_cookies(content: str) -> dict:
    """Converte cookies no formato Netscape (exportados do navegador) para dicionário."""
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

def get_jwt_token(session: requests.Session, device_id: str) -> str:
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
        "deviceLat": "-29.7800",
        "deviceLon": "-55.8000",
        "deviceDNT": "false",
        "serverSideAds": "false",
        "userId": "",
    }
    resp = session.get(BOOT_URL, headers={
        "User-Agent": USER_AGENT,
        "Referer": "https://pluto.tv/br",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
    }, params=params)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("sessionToken")
    if not token:
        raise ValueError("sessionToken não encontrado na resposta boot")
    return token

def fetch_series_data(session: requests.Session, device_id: str, jwt_token: str, series_id: str) -> dict:
    """Busca os metadados completos da série, incluindo temporadas e episódios."""
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
    }
    resp = session.get(BOOT_URL, headers={
        "User-Agent": USER_AGENT,
        "Referer": f"https://pluto.tv/br/on-demand/series/{series_id}",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
    }, params=params)
    resp.raise_for_status()
    data = resp.json()
    vod_list = data.get("VOD", [])
    for item in vod_list:
        if item.get("id") == series_id:
            return item
    raise ValueError(f"Série {series_id} não encontrada na resposta VOD")

def extract_episodes_info(series_data: dict) -> list:
    """
    Extrai as informações estruturadas de cada episódio:
    Retorna lista de dicionários com:
      - series_title
      - series_id
      - season_number (int)
      - season_id
      - episode_number (int)
      - episode_title
      - episode_id
    """
    episodes = []
    series_title = series_data.get("name", "Desconhecido")
    series_id = series_data.get("id", "")

    for season in series_data.get("seasons", []):
        season_num = season.get("seasonNumber")
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

    # Ordena por temporada e episódio
    episodes.sort(key=lambda x: (x["season_number"], x["episode_number"]))
    return episodes

def sanitize_filename(name: str) -> str:
    """Remove caracteres inválidos para nome de arquivo."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def write_output_file(series_title: str, episodes: list, output_dir: str = "."):
    """
    Gera um arquivo .txt com as colunas:
    título | temporada S0X | episódio E0X | series_id | season_id | episode_id
    """
    if not episodes:
        print(f"⚠️ Nenhum episódio encontrado para '{series_title}'. Nenhum arquivo gerado.")
        return

    safe_title = sanitize_filename(series_title) or "serie_sem_nome"
    filename = os.path.join(output_dir, f"{safe_title}.txt")

    with open(filename, "w", encoding="utf-8") as f:
        # Cabeçalho opcional (pode remover se quiser)
        f.write("Título\tTemporada\tEpisódio\tSeries_ID\tSeason_ID\tEpisode_ID\n")
        for ep in episodes:
            season_str = f"S{ep['season_number']:02d}"
            episode_str = f"E{ep['episode_number']:02d}"
            line = (
                f"{ep['series_title']}\t"
                f"{season_str}\t"
                f"{episode_str}\t"
                f"{ep['series_id']}\t"
                f"{ep['season_id']}\t"
                f"{ep['episode_id']}\n"
            )
            f.write(line)

    print(f"💾 Arquivo salvo: {filename} ({len(episodes)} episódios)")

# ============================================================
# FUNÇÃO PRINCIPAL
# ============================================================
def process_series(series_id: str, output_dir: str = "."):
    """Executa todo o pipeline para uma única série."""
    cookie_content = os.environ.get("PLUTO_COOKIES", "")
    if not cookie_content:
        raise ValueError("Variável de ambiente PLUTO_COOKIES não definida")

    cookies = parse_netscape_cookies(cookie_content)
    if not cookies:
        raise ValueError("Nenhum cookie válido extraído")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".pluto.tv")

    device_id = str(uuid.uuid4())
    print(f"🆔 Device ID: {device_id}")

    print("🔐 Obtendo token JWT...")
    jwt_token = get_jwt_token(session, device_id)
    print("✅ JWT obtido.")

    print(f"📡 Buscando dados da série {series_id}...")
    series_data = fetch_series_data(session, device_id, jwt_token, series_id)
    series_title = series_data.get("name", "Série Desconhecida")
    print(f"📺 Série: {series_title}")

    episodes = extract_episodes_info(series_data)
    print(f"🎬 Total de episódios encontrados: {len(episodes)}")

    write_output_file(series_title, episodes, output_dir)

def main():
    if len(sys.argv) < 2:
        print(f"Uso: {sys.argv[0]} <series_id> [diretório_saída]", file=sys.stderr)
        print("Exemplo: python PlutoTV_sniffer.py 5f972b4e8f3b4e001e2b0a1b", file=sys.stderr)
        sys.exit(1)

    series_id = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "."

    try:
        process_series(series_id, output_dir)
    except Exception as e:
        print(f"\n💥 Erro: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
