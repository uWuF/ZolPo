"""
Client for the shared "Cerberus" price-transparency portal
(url.publishedprices.co.il).

Many Israeli chains publish here — Rami Levy, Yohananof, Osher Ad, Tiv Taam,
Stop Market, Dor Alon … — each with its own username and a blank password. So
this one client unlocks a large chunk of the chain roadmap, not just Rami Levy.

Login flow (reverse-engineered):
  GET  /login            -> CSRF token in a <meta name="csrftoken"> tag
  POST /login/user       -> sets the session cookie (cftpSID)
  GET  /file             -> a *fresh* CSRF token (rotates per page)
  POST /file/json/dir    -> JSON directory listing
  GET  /file/d/<name>    -> download one file
"""

from __future__ import annotations

import os
import re

try:
    # publishedprices omits an intermediate cert; use the macOS system trust store.
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests

BASE = "https://url.publishedprices.co.il"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) ZolPo/1.0"}


def _csrf(html_text: str) -> str:
    for pat in (r'csrftoken"[^>]*content="([^"]+)"',
                r'name="csrftoken"[^>]*value="([^"]+)"',
                r'"csrftoken"\s*:\s*"([^"]+)"'):
        m = re.search(pat, html_text)
        if m:
            return m.group(1)
    return ""


class CerberusClient:
    """A logged-in session for one chain's username."""

    def __init__(self, username: str, password: str = ""):
        self.username = username
        self.password = password
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.token = ""

    def login(self) -> "CerberusClient":
        tok = _csrf(self.s.get(BASE + "/login", timeout=30).text)
        self.s.post(BASE + "/login/user",
                    data={"username": self.username, "password": self.password,
                          "Submit": "Sign in", "csrftoken": tok}, timeout=30)
        # The directory endpoint needs the token rendered on the /file page.
        self.token = _csrf(self.s.get(BASE + "/file", timeout=30).text)
        return self

    def list_files(self, search: str = "") -> list[str]:
        r = self.s.post(BASE + "/file/json/dir",
                        data={"sEcho": 1, "iColumns": 5, "iDisplayStart": 0,
                              "iDisplayLength": 3000, "sSearch": search,
                              "csrftoken": self.token},
                        headers={"X-Requested-With": "XMLHttpRequest", "Referer": BASE + "/file"},
                        timeout=90)
        return [row.get("name", "") for row in r.json().get("aaData", []) if row.get("name")]

    def download(self, name: str) -> bytes:
        raw = self.s.get(BASE + "/file/d/" + name, timeout=120).content
        if raw[:2] == b"\x1f\x8b":
            import gzip
            raw = gzip.decompress(raw)
        return raw


def _store_field(filename: str) -> str | None:
    """
    Store id from a PriceFull filename, handling both layouts:
      PriceFull<chain>-<sub>-<store>-<YYYYMMDD>-<HHMMSS>
      PriceFull<chain>-<store>-<YYYYMMDDHHMM>
    """
    f = filename.split(".")[0].split("-")
    if len(f) >= 5:
        return f[2]
    if len(f) >= 3:
        return f[1]
    return None


def newest_file_name(names: list[str], store_id: str, prefix: str = "pricefull") -> str | None:
    # Zero-padding differs between the Stores directory and the price filenames
    # (e.g. directory "19" vs file "019"), so compare both sides stripped.
    sid = str(store_id).lstrip("0")
    cands = [n for n in names
             if n.lower().startswith(prefix.lower())
             and (_store_field(n) or "").lstrip("0") == sid]
    return sorted(cands)[-1] if cands else None


def newest_pricefull_name(names: list[str], store_id: str) -> str | None:
    return newest_file_name(names, store_id, "pricefull")


def download_store_file(client: CerberusClient, store_id: str, out_dir: str,
                        names: list[str] | None = None,
                        prefix: str = "PriceFull") -> str | None:
    """Save the newest <prefix> file for `store_id` into out_dir. Returns the path."""
    names = names if names is not None else client.list_files(prefix)
    name = newest_file_name(names, store_id, prefix)
    if not name:
        return None
    raw = client.download(name)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name.replace(".gz", ""))
    with open(path, "wb") as f:
        f.write(raw)
    return path


def download_store_pricefull(client: CerberusClient, store_id: str, out_dir: str,
                             names: list[str] | None = None) -> str | None:
    return download_store_file(client, store_id, out_dir, names, "PriceFull")


def fetch_stores_directory(client: CerberusClient) -> bytes:
    """Raw bytes of the newest Stores<chain>-...xml directory file."""
    names = [n for n in client.list_files("Stores") if n.lower().startswith("stores")]
    if not names:
        raise RuntimeError("no Stores directory file on portal")
    return client.download(sorted(names)[-1])
