"""Pobiera oficjalny schemat FA(3) razem ze wszystkimi importowanymi schematami
i przepisuje odwołania na pliki lokalne (lxml/libxml2 nie obsługuje HTTPS).

Użycie:  python scripts/fetch_xsd.py katalog_docelowy
Wynik:   katalog_docelowy/schemat.xsd gotowy do walidacji offline.
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

ROOT_URL = "https://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd"
LOC = re.compile(r'schemaLocation="([^"]+)"')


def fetch(url: str) -> str:
    url = url.replace("http://", "https://", 1)
    req = urllib.request.Request(url, headers={"User-Agent": "nexus-tsl-ci"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - stały adres MF
        return r.read().decode("utf-8")


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    queue, names = [ROOT_URL], {ROOT_URL: "schemat.xsd"}
    while queue:
        url = queue.pop()
        text = fetch(url)

        def local(m: re.Match, base: str = url) -> str:
            dep = urljoin(base, m.group(1))
            if dep not in names:
                names[dep] = Path(dep).name
                queue.append(dep)
            return f'schemaLocation="{names[dep]}"'

        (out / names[url]).write_text(LOC.sub(local, text), encoding="utf-8")
        print("pobrano", names[url])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "xsd")
