#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FELHŐ TikTok-feltöltő (GitHub Actions runnerben VAGY a Mac-fallbackban fut) — Mac-független.

2026-09-29: a TikTok-draft eddig csak a Macről ment, alvó géppel nem érkezett meg.
Minden jobs/*.json-t, aminek van "tiktok" része ({"caption","publish_at"}), esedékességkor
a TikTok inboxába tölt (FILE_UPLOAD; auditálatlan app → draft, egy koppintás a TikTok-appban).
Állapot: state.json "tt:<slug>" kulccsal (az IG-é a sima <slug>, nem ütköznek).

Titkok env-ből: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN (GitHub Secrets).
Mac-fallbacknál TT_TOKEN_FILE a poszt/tiktok_token.json — onnan olvas és oda írja vissza a frisset.
"""
from __future__ import annotations
import json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state.json"
API = "https://open.tiktokapis.com/v2"


def _req(url: str, method: str, hdr: dict, data: bytes | None = None) -> dict:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=hdr), timeout=120) as r:
            return json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:400]}")


def _token() -> str:
    fajl = Path(os.environ["TT_TOKEN_FILE"]) if os.environ.get("TT_TOKEN_FILE") else None
    cache = json.loads(fajl.read_text()) if fajl and fajl.exists() else {}
    if cache.get("access_token") and cache.get("expires_at", 0) > time.time() + 120:
        return cache["access_token"]
    rt = cache.get("refresh_token") or os.environ.get("TIKTOK_REFRESH_TOKEN", "")
    ck, cs = os.environ.get("TIKTOK_CLIENT_KEY", ""), os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not (rt and ck and cs):
        raise RuntimeError("hiányzó TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET / TIKTOK_REFRESH_TOKEN")
    body = urllib.parse.urlencode({"client_key": ck, "client_secret": cs,
                                   "grant_type": "refresh_token", "refresh_token": rt}).encode()
    tok = _req(f"{API}/oauth/token/", "POST", {"Content-Type": "application/x-www-form-urlencoded"}, body)
    if not tok.get("access_token"):
        raise RuntimeError(f"token-frissítés hiba: {str(tok)[:200]}")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 86400))
    if fajl:
        fajl.write_text(json.dumps(tok, indent=2))
    return tok["access_token"]


def feltolt(video: Path) -> str:
    """Inbox-draft FILE_UPLOAD-dal (ugyanaz, mint a Mac posztolo.post_tiktok inbox-ága)."""
    hdr = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json; charset=UTF-8"}
    size, mb = video.stat().st_size, 1024 * 1024
    chunk, count = (size, 1) if size <= 64 * mb else (32 * mb, size // (32 * mb))
    init = _req(f"{API}/post/publish/inbox/video/init/", "POST", hdr, json.dumps(
        {"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                         "chunk_size": chunk, "total_chunk_count": count}}).encode())
    d = init.get("data") or {}
    pid, up = d.get("publish_id"), d.get("upload_url")
    if not (pid and up):
        raise RuntimeError(f"init hiba: {init}")
    raw = video.read_bytes()
    for i in range(count):
        lo = i * chunk
        hi = size - 1 if i == count - 1 else lo + chunk - 1
        urllib.request.urlopen(urllib.request.Request(up, data=raw[lo:hi + 1], method="PUT", headers={
            "Content-Type": "video/mp4", "Content-Length": str(hi - lo + 1),
            "Content-Range": f"bytes {lo}-{hi}/{size}"}), timeout=300).read()
    for _ in range(30):
        st = (_req(f"{API}/post/publish/status/fetch/", "POST", hdr,
                   json.dumps({"publish_id": pid}).encode()).get("data") or {}).get("status", "")
        if st in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return f"tiktok:DRAFT(inbox — egy koppintás a TikTok-appban) id={pid}"
        if st == "FAILED":
            raise RuntimeError(f"feldolgozási hiba (id={pid})")
        time.sleep(10)
    raise RuntimeError(f"nem lett kész 5 perc alatt (id={pid})")


def esedekes(job: dict, most: datetime) -> bool:
    tt = job.get("tiktok")
    return bool(tt) and (not tt.get("publish_at") or datetime.fromisoformat(tt["publish_at"]) <= most)


def main() -> int:
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    most = datetime.now(timezone.utc) - timedelta(minutes=int(os.environ.get("MIN_OVERDUE_MIN", "0")))
    hibak = 0
    for jf in sorted(ROOT.glob("jobs/*.json")):
        kulcs = f"tt:{jf.stem}"
        job = json.loads(jf.read_text())
        if kulcs in state or not esedekes(job, most):
            continue
        try:
            state[kulcs] = feltolt(ROOT / job["video"])
            print(f"  ✅ {kulcs}: {state[kulcs]}", flush=True)
        except Exception as e:
            hibak += 1
            print(f"  ❌ {kulcs}: {e!r}", flush=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return 1 if hibak else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--teszt"]:
        m = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
        assert esedekes({"tiktok": {"publish_at": "2026-09-29T19:45:00+02:00"}}, m)
        assert not esedekes({"tiktok": {"publish_at": "2026-09-29T20:45:00+02:00"}}, m)
        assert not esedekes({"caption": "csak IG"}, m)
        print("ok")
        sys.exit(0)
    sys.exit(main())
