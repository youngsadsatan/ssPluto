import os
import requests
import json
from urllib.parse import urlencode
import re

# --- Configuração (via Secrets do GitHub) ---
PLUTO_COOKIES = os.environ.get("PLUTO_COOKIES", "")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
BOOT_URL = "https://boot.pluto.tv/v4/start"
CATALOG_SERIES_URL = "https://service-vod.clusters.pluto.tv/v4/vod/series/{series_id}/seasons"
STITCHER_BASE = "https://cfd-v4-service-stitcher-dash-use1-1.prd.pluto.tv/v2/stitch/dash/episode/{episode_id}/main.mpd"

SERIES_IDS = [
    "66d70dfaf98f52001332a8f5",  # Tratamento de Choque
]

def parse_netscape_cookies(content):
    """
    Processa o conteúdo no formato Netscape (curl/wget).
    Retorna um dicionário {nome: valor}.
    """
    cookies = {}
    if not content:
        return cookies

    for line in content.splitlines():
        line = line.strip()
        # Ignora linhas de comentário e vazias
        if not line or line.startswith('#'):
            continue

        parts = line.split('\t')
        if len(parts) != 7:
            continue  # linha inválida

        domain, flag1, path, secure, expires, name, value = parts
        # Apenas para garantir que não haja espaços extras
        name = name.strip()
        value = value.strip()
        if name:
            cookies[name] = value

    return cookies

def get_jwt_token(session):
    """Obtém um JWT válido a partir do endpoint /start."""
    headers = {"User-Agent": USER_AGENT}
    params = {
        "appName": "web",
        "appVersion": "9.20.0-89258290264838515e264f5b051b7c1602a58482",
        "deviceType": "web",
        "deviceMake": "chrome",
        "deviceModel": "web",
        "deviceVersion": "143.0.0",
        "clientID": "a491ac3f-509b-4637-a4a1-9ed036ce5cf2",
        "marketingRegion": "BR",
        "country": "BR"
    }
    try:
        response = session.get(BOOT_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        token = data.get("sessionToken")
        if not token:
            raise ValueError("Resposta de /start não contém 'sessionToken'.")
        return token
    except requests.exceptions.RequestException as e:
        print(f"❌ Erro na requisição para {BOOT_URL}: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"   Status: {e.response.status_code}")
            print(f"   Corpo: {e.response.text[:200]}")
        raise
    except json.JSONDecodeError as e:
        print(f"❌ Resposta inválida (não é JSON): {e}")
        raise

def fetch_series_episodes(session, jwt_token, series_id):
    """Busca todas as temporadas e episódios de uma série."""
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {jwt_token}"
    }
    params = {
        "offset": 1000,
        "page": 1
    }
    url = CATALOG_SERIES_URL.format(series_id=series_id)
    response = session.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def build_stream_url(episode_id, jwt_token, session_id, device_id):
    """Constrói a URL completa do manifesto DASH com os parâmetros necessários."""
    params = {
        "jwt": jwt_token,
        "sid": session_id,
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
        "deviceMake": "chrome",
        "deviceModel": "web",
        "deviceType": "web",
        "deviceVersion": "143.0.0",
        "marketingRegion": "BR",
        "serverSideAds": "false",
        "sessionID": session_id,
        "userId": "",
        "masterJWTPassthrough": "true",
        "includeExtendedEvents": "true",
        "eventVOD": "false"
    }
    base_url = STITCHER_BASE.format(episode_id=episode_id)
    return f"{base_url}?{urlencode(params)}"

def generate_m3u_playlist(output_file="playlist.m3u"):
    """Gera o arquivo M3U final."""
    if not PLUTO_COOKIES:
        raise ValueError("❌ PLUTO_COOKIES não definido no ambiente (Secrets do GitHub).")

    # Processa o conteúdo no formato Netscape
    cookies_dict = parse_netscape_cookies(PLUTO_COOKIES)
    if not cookies_dict:
        raise ValueError("❌ Nenhum cookie válido encontrado em PLUTO_COOKIES (formato Netscape esperado).")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # Adiciona cookies um a um, definindo o domínio com base no arquivo (opcional)
    # Para simplificar, usamos o domínio padrão .pluto.tv para todos, o que funciona.
    for key, value in cookies_dict.items():
        session.cookies.set(key, value, domain=".pluto.tv")

    print(f"🍪 Cookies carregados: {len(cookies_dict)}")

    print("🔐 Obtendo token JWT...")
    jwt_token = get_jwt_token(session)
    print("✅ JWT obtido com sucesso.")

    # IDs fixos (você pode extrair da resposta do /start se quiser, mas estes funcionam)
    session_id = "c4f5efe2-370e-11f1-ace8-5e805755c9ec"
    device_id = "a491ac3f-509b-4637-a4a1-9ed036ce5cf2"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        for series_id in SERIES_IDS:
            print(f"\n📺 Processando série ID: {series_id}")
            try:
                data = fetch_series_episodes(session, jwt_token, series_id)
            except Exception as e:
                print(f"   ❌ Erro ao buscar episódios: {e}")
                continue

            series_name = data.get("name", "Série Desconhecida")
            seasons = data.get("seasons", [])

            for season in seasons:
                season_number = season.get("seasonNumber")
                episodes = season.get("episodes", [])
                for ep in episodes:
                    ep_id = ep.get("id")
                    ep_title = ep.get("name", "Sem título")
                    ep_number = ep.get("number", "S00E00")
                    thumbnail = ep.get("thumbnail", {}).get("path", "")
                    if not thumbnail:
                        thumbnail = f"https://images.pluto.tv/episodes/{ep_id}/screenshot16_9.jpg"

                    if not ep_id:
                        continue

                    stream_url = build_stream_url(ep_id, jwt_token, session_id, device_id)

                    f.write(f'#EXTINF:-1 type="video" tvg-logo="{thumbnail}" group-title="{series_name}", {ep_number} - {ep_title}\n')
                    f.write(f"{stream_url}\n")
                    print(f"   ✅ {ep_number}: {ep_title}")

    print(f"\n🎉 Playlist '{output_file}' gerada com sucesso!")

if __name__ == "__main__":
    generate_m3u_playlist()
