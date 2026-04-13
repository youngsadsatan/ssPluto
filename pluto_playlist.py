#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gerador de playlist M3U para conteúdos On‑Demand do Pluto TV.
Utiliza a API oficial do Pluto TV para obter automaticamente os episódios
de séries a partir de seus IDs, sem necessidade de scraping HTML.

Requer os cookies de uma sessão autenticada no Pluto TV, fornecidos via
variável de ambiente `PLUTO_COOKIES` no formato Netscape (curl/wget).
"""

import os
import sys
import json
import uuid
import requests
from urllib.parse import urlencode

# ----------------------------------------------------------------------
# Configurações globais
# ----------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

BOOT_URL = "https://boot.pluto.tv/v4/start"
STITCHER_BASE = "https://cfd-v4-service-stitcher-dash-use1-1.prd.pluto.tv/v2/stitch/dash/episode/{episode_id}/main.mpd"

# Lista de IDs de séries que você quer incluir na playlist
SERIES_IDS = [
    "66d70dfaf98f52001332a8f5",  # Tratamento de Choque
]

OUTPUT_FILE = "playlist.m3u"

# ----------------------------------------------------------------------
# Funções auxiliares
# ----------------------------------------------------------------------

def parse_netscape_cookies(content: str) -> dict:
    """Converte um arquivo de cookies no formato Netscape em um dicionário."""
    cookies = {}
    if not content:
        return cookies

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = line.split('\t')
        if len(parts) != 7:
            continue

        _, _, _, _, _, name, value = parts
        name = name.strip()
        value = value.strip()
        if name:
            cookies[name] = value

    return cookies


def get_app_version(session: requests.Session) -> str:
    """Extrai a versão do app a partir da meta tag do site."""
    # Fazemos uma requisição à página inicial para obter a versão mais recente.
    resp = session.get("https://pluto.tv/", headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    # Procura pela meta tag <meta name="appVersion" content="...">
    import re
    match = re.search(r'<meta name="appVersion" content="([^"]+)"', resp.text)
    if not match:
        raise RuntimeError("Não foi possível encontrar a versão do app na página.")
    return match.group(1)


def get_jwt_and_vod_data(session: requests.Session, device_id: str, series_id: str):
    """
    Obtém o token JWT e os dados completos da série (VOD) através do endpoint /v4/start.
    """
    app_version = get_app_version(session)
    print(f"📱 Versão do app: {app_version}", file=sys.stderr)

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://pluto.tv/",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
    }

    params = {
        "appName": "web",
        "appVersion": app_version,
        "clientModelNumber": "1.0.0",
        "deviceType": "web",
        "deviceMake": "firefox",
        "deviceModel": "web",
        "deviceVersion": "136.0",
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
        "seriesIDs": series_id,  # <- Aqui passamos o ID da série
    }

    try:
        response = session.get(BOOT_URL, headers=headers, params=params)
        if response.status_code != 200:
            print(f"❌ Status {response.status_code}: {response.text[:500]}", file=sys.stderr)
        response.raise_for_status()
        data = response.json()
        token = data.get("sessionToken")
        if not token:
            raise ValueError("sessionToken não encontrado na resposta.")
        return token, data
    except requests.exceptions.RequestException as e:
        print(f"❌ Falha na comunicação com {BOOT_URL}: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Corpo da resposta: {e.response.text[:500]}", file=sys.stderr)
        raise
    except json.JSONDecodeError as e:
        print(f"❌ Resposta inválida (JSON malformado): {e}", file=sys.stderr)
        raise


def build_stream_url(episode_id: str, jwt_token: str, device_id: str) -> str:
    """Constrói a URL completa do manifesto DASH para um episódio."""
    params = {
        "jwt": jwt_token,
        "sid": device_id,
        "deviceId": device_id,
        "advertisingId": "",
        "appName": "web",
        "appVersion": "9.20.0-89258290264838515e264f5b051b7c1602a58482",
        "app_name": "web",
        "clientDeviceType": "0",
        "clientID": device_id,
        "clientModelNumber": "1.0.0",
        "country": "BR",
        "deviceDNT": "false",
        "deviceLat": "-29.7800",
        "deviceLon": "-55.8000",
        "deviceMake": "firefox",
        "deviceModel": "web",
        "deviceType": "web",
        "deviceVersion": "136.0",
        "marketingRegion": "BR",
        "serverSideAds": "false",
        "sessionID": device_id,
        "userId": "",
        "masterJWTPassthrough": "true",
        "includeExtendedEvents": "true",
        "eventVOD": "false",
    }
    base_url = STITCHER_BASE.format(episode_id=episode_id)
    return f"{base_url}?{urlencode(params)}"


# ----------------------------------------------------------------------
# Função principal
# ----------------------------------------------------------------------

def generate_m3u_playlist(output_file: str = OUTPUT_FILE) -> None:
    # 1. Cookies
    cookie_content = os.environ.get("PLUTO_COOKIES", "")
    if not cookie_content:
        raise ValueError("❌ PLUTO_COOKIES não definida.")

    cookies_dict = parse_netscape_cookies(cookie_content)
    if not cookies_dict:
        raise ValueError("❌ Nenhum cookie válido encontrado.")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for name, value in cookies_dict.items():
        session.cookies.set(name, value, domain=".pluto.tv")

    print(f"🍪 Cookies carregados: {len(cookies_dict)}", file=sys.stderr)

    device_id = str(uuid.uuid4())
    print(f"🆔 Device ID: {device_id}", file=sys.stderr)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        for series_id in SERIES_IDS:
            print(f"\n📺 Processando série ID: {series_id}", file=sys.stderr)

            try:
                jwt_token, vod_data = get_jwt_and_vod_data(session, device_id, series_id)
                print("✅ JWT obtido com sucesso.", file=sys.stderr)
            except Exception as e:
                print(f"   ❌ Erro ao obter dados da série: {e}", file=sys.stderr)
                continue

            # A estrutura dos dados VOD retornados é:
            # {"VOD": [ { ... "seasons": [ { "episodes": [ ... ] } ] } ]}
            vod_list = vod_data.get("VOD", [])
            if not vod_list:
                print("   ⚠️ Nenhum dado VOD encontrado para esta série.", file=sys.stderr)
                continue

            series_info = vod_list[0]
            series_name = series_info.get("name", "Série Desconhecida")
            seasons = series_info.get("seasons", [])

            for season in seasons:
                for ep in season.get("episodes", []):
                    ep_id = ep.get("_id")  # Note o "_id"
                    if not ep_id:
                        continue

                    ep_title = ep.get("name", "Sem título")
                    ep_number = ep.get("number", "S00E00")
                    thumbnail = ep.get("thumbnail", {}).get("path", "")
                    if not thumbnail:
                        thumbnail = f"https://images.pluto.tv/episodes/{ep_id}/screenshot16_9.jpg"

                    stream_url = build_stream_url(ep_id, jwt_token, device_id)

                    f.write(
                        f'#EXTINF:-1 type="video" '
                        f'tvg-logo="{thumbnail}" '
                        f'group-title="{series_name}", '
                        f'{ep_number} - {ep_title}\n'
                    )
                    f.write(f"{stream_url}\n")
                    print(f"   ✅ {ep_number}: {ep_title}", file=sys.stderr)

    print(f"\n🎉 Playlist '{output_file}' gerada com sucesso!", file=sys.stderr)


if __name__ == "__main__":
    try:
        generate_m3u_playlist()
    except Exception as e:
        print(f"\n💥 Erro fatal: {e}", file=sys.stderr)
        sys.exit(1)
