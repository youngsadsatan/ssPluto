#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import json

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
OUTPUT_FILE = "playlist.m3u"

EPISODE_URLS = [
    "https://pluto.tv/br/on-demand/series/66d70dfaf98f52001332a8f5/season/1/episode/66d71d6c46be430013cf2195",
    "https://pluto.tv/br/on-demand/series/66d70dfaf98f52001332a8f5/season/1/episode/66d71d6e46be430013cf22a4",
]

def get_stream_url(video_url, cookies_file):
    cmd = [
        "streamlink",
        "--http-cookie-file", cookies_file,
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

    cookies_file = "cookies.txt"
    with open(cookies_file, "w", encoding="utf-8") as f:
        f.write(cookie_content)

    print(f"🍪 Cookies carregados", file=sys.stderr)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for url in EPISODE_URLS:
            print(f"\n📺 Processando: {url}", file=sys.stderr)
            stream_url = get_stream_url(url, cookies_file)
            if stream_url:
                f.write(f'#EXTINF:-1 type="video" group-title="Série", Episódio\n')
                f.write(f"{stream_url}\n")
                print(f"   ✅ URL obtida", file=sys.stderr)
            else:
                print(f"   ❌ Falha ao obter URL", file=sys.stderr)

    os.remove(cookies_file)
    print(f"\n🎉 Playlist '{OUTPUT_FILE}' gerada com sucesso!", file=sys.stderr)

if __name__ == "__main__":
    try:
        generate_m3u_playlist()
    except Exception as e:
        print(f"\n💥 Erro fatal: {e}", file=sys.stderr)
        sys.exit(1)
