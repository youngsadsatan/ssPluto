#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gerador de playlist M3U para conteúdos On‑Demand do Pluto TV.
Utiliza as APIs oficiais do Pluto TV para obter automaticamente os episódios
de séries a partir de seus IDs, sem necessidade de scraping HTML.

Requer os cookies de uma sessão autenticada no Pluto TV, fornecidos via
variável de ambiente `PLUTO_COOKIES` no formato Netscape (curl/wget).

Autor: baseado em análise de tráfego da versão web do Pluto TV (abril/2026)
"""

import os
import sys
import json
import uuid
import requests
from urllib.parse import urlencode

# ----------------------------------------------------------------------
# Configurações globais (podem ser ajustadas conforme necessário)
# ----------------------------------------------------------------------

# User-Agent utilizado nas requisições – simula um navegador real
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Endpoints da API do Pluto TV (identificados via análise de tráfego)
BOOT_URL = "https://boot.pluto.tv/v4/start"
CATALOG_SERIES_URL = "https://service-vod.clusters.pluto.tv/v4/vod/series/{series_id}/seasons"
STITCHER_BASE = "https://cfd-v4-service-stitcher-dash-use1-1.prd.pluto.tv/v2/stitch/dash/episode/{episode_id}/main.mpd"

# Lista de IDs de séries que serão incluídas na playlist.
# Cada ID corresponde a uma série; para adicionar novas séries, basta incluir
# o identificador único extraído da URL (ex.: ".../series/66d70dfaf98f52001332a8f5").
SERIES_IDS = [
    "66d70dfaf98f52001332a8f5",  # Tratamento de Choque
    # Adicione outros IDs abaixo, um por linha:
    # "xxxxxxxxxxxxxxxxxxxxxxxx",
]

# Arquivo de saída da playlist M3U
OUTPUT_FILE = "playlist.m3u"

# ----------------------------------------------------------------------
# Funções auxiliares para manipulação de cookies
# ----------------------------------------------------------------------

def parse_netscape_cookies(content: str) -> dict:
    """
    Converte um arquivo de cookies no formato Netscape (usado por curl/wget)
    em um dicionário Python {nome: valor}.

    O formato Netscape é tabulado e possui 7 colunas:
    domain  flag  path  secure  expiration  name  value

    Linhas iniciadas por '#' são ignoradas (comentários).
    """
    cookies = {}
    if not content:
        return cookies

    for line in content.splitlines():
        line = line.strip()
        # Ignora comentários e linhas vazias
        if not line or line.startswith('#'):
            continue

        parts = line.split('\t')
        if len(parts) != 7:
            # Linha mal formatada, ignoramos silenciosamente
            continue

        # As colunas relevantes são: índice 0 (domain), 5 (name), 6 (value)
        domain, _, _, _, _, name, value = parts
        name = name.strip()
        value = value.strip()
        if name:
            cookies[name] = value

    return cookies


# ----------------------------------------------------------------------
# Comunicação com as APIs do Pluto TV
# ----------------------------------------------------------------------

def get_jwt_token(session: requests.Session, device_id: str) -> str:
    """
    Obtém um token JWT (JSON Web Token) a partir do endpoint /v4/start.

    Esse token é necessário para autenticar todas as chamadas subsequentes
    às APIs de catálogo e de streaming.

    Parâmetros obrigatórios foram determinados através da análise de requisições
    bem-sucedidas realizadas pelo site oficial.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://pluto.tv/",
        "Origin": "https://pluto.tv",
        "Accept": "application/json",
    }

    # Parâmetros da requisição – note a presença obrigatória de clientModelNumber
    params = {
        "appName": "web",
        "appVersion": "9.20.0-89258290264838515e264f5b051b7c1602a58482",
        "clientModelNumber": "1.0.0",          # <- OBRIGATÓRIO
        "deviceType": "web",
        "deviceMake": "firefox",               # mais realista do que "chrome"
        "deviceModel": "web",
        "deviceVersion": "136.0",              # versão comum do Firefox
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

    try:
        response = session.get(BOOT_URL, headers=headers, params=params)
        if response.status_code != 200:
            print(f"❌ Status HTTP {response.status_code}: {response.text[:500]}",
                  file=sys.stderr)
        response.raise_for_status()
        data = response.json()
        token = data.get("sessionToken")
        if not token:
            raise ValueError("Resposta não contém o campo 'sessionToken'.")
        return token

    except requests.exceptions.RequestException as e:
        print(f"❌ Falha na comunicação com {BOOT_URL}: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Corpo da resposta: {e.response.text[:500]}", file=sys.stderr)
        raise
    except json.JSONDecodeError as e:
        print(f"❌ Resposta inválida (JSON malformado): {e}", file=sys.stderr)
        raise


def fetch_series_episodes(session: requests.Session, jwt_token: str,
                          series_id: str) -> dict:
    """
    Busca a estrutura completa de temporadas e episódios de uma série.

    Retorna um dicionário com os dados da série, incluindo a lista de
    temporadas e, dentro de cada temporada, os episódios.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/json",
    }
    params = {
        "offset": 1000,   # número máximo de episódios por página (garante trazer todos)
        "page": 1,
    }
    url = CATALOG_SERIES_URL.format(series_id=series_id)

    response = session.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def build_stream_url(episode_id: str, jwt_token: str, device_id: str) -> str:
    """
    Constrói a URL completa do manifesto DASH (MPD) para um episódio,
    incluindo todos os parâmetros de autenticação e configuração de anúncios.
    """
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
# Função principal – geração da playlist M3U
# ----------------------------------------------------------------------

def generate_m3u_playlist(output_file: str = OUTPUT_FILE) -> None:
    """
    Função orquestradora que:
      1. Lê os cookies do ambiente
      2. Obtém um token JWT
      3. Para cada série listada, consulta a API de catálogo
      4. Gera um arquivo M3U contendo todos os episódios
    """
    # ------------------------------------------------------------------
    # 1. Carregar e validar os cookies
    # ------------------------------------------------------------------
    cookie_content = os.environ.get("PLUTO_COOKIES", "")
    if not cookie_content:
        raise ValueError(
            "❌ Variável de ambiente PLUTO_COOKIES não definida.\n"
            "   Defina-a nos Secrets do GitHub com o conteúdo do arquivo "
            "Netscape."
        )

    cookies_dict = parse_netscape_cookies(cookie_content)
    if not cookies_dict:
        raise ValueError(
            "❌ Nenhum cookie válido foi extraído de PLUTO_COOKIES.\n"
            "   Verifique se o conteúdo está no formato Netscape correto."
        )

    # ------------------------------------------------------------------
    # 2. Configurar sessão HTTP com os cookies e User-Agent
    # ------------------------------------------------------------------
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # Adiciona cada cookie individualmente, garantindo que o domínio
    # .pluto.tv seja utilizado para todos (compatível com o comportamento do site)
    for name, value in cookies_dict.items():
        session.cookies.set(name, value, domain=".pluto.tv")

    print(f"🍪 Cookies carregados: {len(cookies_dict)}", file=sys.stderr)

    # ------------------------------------------------------------------
    # 3. Gerar um identificador único para simular um dispositivo novo
    # ------------------------------------------------------------------
    device_id = str(uuid.uuid4())
    print(f"🆔 Device ID gerado: {device_id}", file=sys.stderr)

    # ------------------------------------------------------------------
    # 4. Obter o token JWT necessário para as demais chamadas
    # ------------------------------------------------------------------
    print("🔐 Obtendo token JWT...", file=sys.stderr)
    jwt_token = get_jwt_token(session, device_id)
    print("✅ JWT obtido com sucesso.\n", file=sys.stderr)

    # ------------------------------------------------------------------
    # 5. Processar cada série e gerar o arquivo M3U
    # ------------------------------------------------------------------
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        for series_id in SERIES_IDS:
            print(f"📺 Processando série ID: {series_id}", file=sys.stderr)
            try:
                data = fetch_series_episodes(session, jwt_token, series_id)
            except Exception as e:
                print(f"   ❌ Erro ao buscar episódios: {e}", file=sys.stderr)
                continue

            # Extrai o nome da série (fallback para "Série Desconhecida")
            series_name = data.get("name", "Série Desconhecida")
            seasons = data.get("seasons", [])

            for season in seasons:
                season_number = season.get("seasonNumber")
                episodes = season.get("episodes", [])

                for ep in episodes:
                    ep_id = ep.get("id")
                    ep_title = ep.get("name", "Sem título")
                    ep_number = ep.get("number", "S00E00")

                    # URL da thumbnail – tenta obter do campo thumbnail.path,
                    # senão usa o padrão images.pluto.tv/.../screenshot16_9.jpg
                    thumbnail = ep.get("thumbnail", {}).get("path", "")
                    if not thumbnail:
                        thumbnail = (
                            f"https://images.pluto.tv/episodes/{ep_id}/"
                            "screenshot16_9.jpg"
                        )

                    if not ep_id:
                        continue

                    stream_url = build_stream_url(ep_id, jwt_token, device_id)

                    # Escreve as linhas no formato M3U estendido
                    f.write(
                        f'#EXTINF:-1 type="video" '
                        f'tvg-logo="{thumbnail}" '
                        f'group-title="{series_name}", '
                        f'{ep_number} - {ep_title}\n'
                    )
                    f.write(f"{stream_url}\n")

                    print(f"   ✅ {ep_number}: {ep_title}", file=sys.stderr)

    print(f"\n🎉 Playlist '{output_file}' gerada com sucesso!", file=sys.stderr)


# ----------------------------------------------------------------------
# Ponto de entrada do script
# ----------------------------------------------------------------------
if __name__ == "__main__":
    try:
        generate_m3u_playlist()
    except Exception as e:
        print(f"\n💥 Erro fatal: {e}", file=sys.stderr)
        sys.exit(1)
