#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import json

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
OUTPUT_FILE = "playlist.m3u"

EPISODE_URLS = [
    "https://pluto.tv/on-demand/series/66d70dfaf98f52001332a8f5/season/1/episode/66d716679f04dd0013b7f9de",
    "https://pluto.tv/on-demand/series/66d70dfaf98f52001332a8f5/season/1/episode/66d70dfbf98f52001332a916",
    "https://pluto.tv/on-demand/series/66d70dfaf98f52001332a8f5/season/1/episode/66d70dfef98f52001332aa28",
]

def parse_netscape_cookies(content):
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

def cookies_to_string(cookies):
    return "; ".join(f"{k}={v}" for k, v in cookies.items())

def get_stream_url(video_url, cookies_str):
    cmd = [
        "streamlink",
        "--http-cookie", cookies_str,
        "--json",
        video_url,
        "best"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        return data.get("url")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao executar streamlink para {video_url}: {e.stderr}", file=sys.stderr)
        return None

def generate_m3u_playlist():
    cookie_content = os.environ.get("PLUTO_COOKIES", "")
    if not cookie_content:
        raise ValueError("PLUTO_COOKIES not set")
    cookies = parse_netscape_cookies(cookie_content)
    if not cookies:
        raise ValueError("no valid cookies")
    cookies_str = cookies_to_string(cookies)

    print(f"🍪 Cookies carregados", file=sys.stderr)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for url in EPISODE_URLS:
            print(f"\n📺 Processando: {url}", file=sys.stderr)
            stream_url = get_stream_url(url, cookies_str)
            if stream_url:
                f.write(f'#EXTINF:-1 type="video" group-title="Série", Episódio\n')
                f.write(f"{stream_url}\n")
                print(f"   ✅ URL obtida", file=sys.stderr)
            else:
                print(f"   ❌ Falha ao obter URL", file=sys.stderr)

    print(f"\n🎉 Playlist '{OUTPUT_FILE}' gerada com sucesso!", file=sys.stderr)

if __name__ == "__main__":
    try:
        generate_m3u_playlist()
    except Exception as e:
        print(f"\n💥 Erro fatal: {e}", file=sys.stderr)
        sys.exit(1)
