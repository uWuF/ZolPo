"""
Client for the "Bina Projects" portal family (<prefix>.binaprojects.com) —
King Store, Good Pharm, Bareket, Zol VeBegadol, Super Sapir and other small
chains publish there. No login.

Protocol (reverse-engineered, mirrors the il-supermarket-scraper engine):

    GET /MainIO_Hok.aspx?_=&wReshet=הכל&WFileType=<t>&WDate=&WStore=
        -> JSON [{"FileNm": "PriceFull...gz", ...}]     t: 1=Stores, 4=PriceFull, 5=PromoFull
    GET /Download.aspx?FileNm=<name>
        -> JSON [{"SPath": "<real download url>"}]

Despite the .gz extension the payloads are usually ZIP archives — unwrap()
handles zip / gzip / plain transparently.
"""

from __future__ import annotations

import gzip
import io
import os
import urllib.parse
import zipfile

import requests

from .cerberus import newest_file_name  # same gov filename layouts

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) ZolPo/1.0"}
FILE_TYPES = {"Stores": 1, "PriceFull": 4, "PromoFull": 5}


def _base(prefix: str) -> str:
    return f"http://{prefix}.binaprojects.com/"


def unwrap(raw: bytes) -> bytes:
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        return z.read(z.namelist()[0])
    return raw


def list_files(prefix: str, kind: str = "PriceFull") -> list[str]:
    q = urllib.parse.urlencode({"_": "", "wReshet": "הכל",
                                "WFileType": FILE_TYPES[kind], "WDate": "", "WStore": ""})
    r = requests.get(_base(prefix) + "MainIO_Hok.aspx?" + q, headers=UA, timeout=30)
    r.raise_for_status()
    return [e.get("FileNm", "") for e in r.json() if e.get("FileNm")]


def download(prefix: str, file_nm: str) -> bytes:
    r = requests.get(_base(prefix) + "Download.aspx?FileNm=" + urllib.parse.quote(file_nm),
                     headers=UA, timeout=30)
    r.raise_for_status()
    spath = r.json()[0]["SPath"]
    return unwrap(requests.get(spath, headers=UA, timeout=120).content)


def fetch_stores_directory(prefix: str) -> bytes:
    names = [n for n in list_files(prefix, "Stores") if n.lower().startswith("stores")]
    if not names:
        raise RuntimeError("no Stores directory file on portal")
    return download(prefix, sorted(names)[-1])


def download_store_file(prefix: str, store_id: str, out_dir: str,
                        names: list[str] | None = None,
                        kind: str = "PriceFull") -> str | None:
    names = names if names is not None else list_files(prefix, kind)
    name = newest_file_name(names, store_id, kind.lower())
    if not name:
        return None
    raw = download(prefix, name)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name.replace(".gz", "").replace(".zip", ""))
    if not path.endswith(".xml"):
        path += ".xml"
    with open(path, "wb") as f:
        f.write(raw)
    return path
