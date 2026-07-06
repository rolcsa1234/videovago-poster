#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FELHŐ IG-posztoló (GitHub Actions runnerben fut) — Mac-független.

Végigmegy a jobs/*.json fájlokon; ami esedékes (publish_at <= most) és nincs a
state.json-ban, azt kiposztolja: a videót a runnerben egy helyi http.server +
Cloudflare quick-tunnel teszi publikussá, az IG onnan húzza le (pull-from-URL),
majd konténer-poll -> media_publish. Állapot: state.json (a workflow commitolja vissza).

Job séma (jobs/day3v1.json):
  {"video":"videos/day3v1.mp4","cover":"videos/day3v1.jpg",
   "caption":"...","publish_at":"2026-07-06T12:00:00+02:00"}
Opcionális: "publish": false -> csak konténer-teszt, NEM publikál (pipeline-ellenőrzés).

Titkok: IG_ACCESS_TOKEN + IG_USER_ID env-ből (GitHub Secrets — SOHA nem a repóba).
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state.json"
PORT = 8791
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
BASE = "https://graph.instagram.com/v21.0"


def _http_json(url: str, method: str = "GET") -> dict:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:400]}")


def _start_tunnel() -> tuple[subprocess.Popen, Path, str]:
    """Quick-tunnel; kimenet FÁJLBA (a tele pipe blokkolná a cloudflared-et)."""
    logp = ROOT / "_cf.log"
    logf = open(logp, "w")
    proc = subprocess.Popen(
        [str(ROOT / "cloudflared"), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
        stdout=logf, stderr=subprocess.STDOUT)
    url, registered, deadline = "", False, time.time() + 90
    while time.time() < deadline:
        txt = logp.read_text() if logp.exists() else ""
        if not url:
            m = TUNNEL_RE.search(txt)
            if m:
                url = m.group(0)
        registered = registered or "Registered tunnel connection" in txt
        if url and registered:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    if not (url and registered):
        proc.terminate()
        raise RuntimeError(f"tunnel nem állt fel (url={bool(url)} registered={registered})")
    return proc, logp, url


def _wait_public(url: str, tries: int = 14) -> bool:
    time.sleep(2)
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=8) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def _ig_publish(video_url: str, cover_url: str | None, caption: str, do_publish: bool) -> str:
    tok, uid = os.environ["IG_ACCESS_TOKEN"], os.environ["IG_USER_ID"]
    params = {"media_type": "REELS", "video_url": video_url, "caption": caption, "access_token": tok}
    if cover_url:
        params["cover_url"] = cover_url
    cont = _http_json(f"{BASE}/{uid}/media?{urllib.parse.urlencode(params)}", "POST")
    cid = cont.get("id")
    if not cid:
        raise RuntimeError(f"IG: nincs konténer-id ({cont})")
    status = ""
    for _ in range(30):                                     # max ~5 perc feldolgozás
        st = _http_json(f"{BASE}/{cid}?fields=status_code&access_token={tok}")
        status = st.get("status_code", "")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"IG feldolgozási hiba: {st}")
        time.sleep(10)
    if status != "FINISHED":
        raise RuntimeError(f"IG: konténer nem lett kész (status={status!r})")
    if not do_publish:
        return f"KONTENER-OK(nem publikálva) id={cid}"
    pub = _http_json(f"{BASE}/{uid}/media_publish?"
                     + urllib.parse.urlencode({"creation_id": cid, "access_token": tok}), "POST")
    return f"POSTED id={pub.get('id', '?')}"


def post_job(job: dict) -> str:
    video = ROOT / job["video"]
    cover = ROOT / job["cover"] if job.get("cover") else None
    httpd = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1",
         "--directory", str(video.parent)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        for attempt in range(1, 6):                         # trycloudflare flaky -> újrapróba
            proc = None
            try:
                proc, logp, tunnel = _start_tunnel()
                vurl = f"{tunnel}/{urllib.parse.quote(video.name)}"
                curl = f"{tunnel}/{urllib.parse.quote(cover.name)}" if cover else None
                print(f"  tunnel #{attempt}: {vurl}", flush=True)
                if _wait_public(vurl) and (not curl or _wait_public(curl)):
                    return _ig_publish(vurl, curl, job.get("caption", ""),
                                       job.get("publish", True))
                print(f"  ez a tunnel nem routol ({attempt}/5)", flush=True)
            finally:
                if proc:
                    proc.terminate()
        raise RuntimeError("nincs működő tunnel 5 próbán át")
    finally:
        httpd.terminate()


def main() -> int:
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    now = datetime.now(timezone.utc)
    # fallback-mód (Mac): csak a legalább N perce esedékes jobokat posztolja — így a
    # felhőé az elsőbbség, a Mac csak a kihagyottakat pótolja (MIN_OVERDUE_MIN env).
    from datetime import timedelta
    now -= timedelta(minutes=int(os.environ.get("MIN_OVERDUE_MIN", "0")))
    fails = 0
    for jf in sorted(ROOT.glob("jobs/*.json")):
        slug = jf.stem
        if slug in state:
            continue
        job = json.loads(jf.read_text())
        pa = job.get("publish_at")
        if pa and datetime.fromisoformat(pa) > now:
            print(f"  ⏳ {slug}: még nem esedékes ({pa})")
            continue
        try:
            res = post_job(job)
            state[slug] = res
            print(f"  ✅ {slug}: {res}", flush=True)
        except Exception as e:
            fails += 1
            print(f"  ❌ {slug}: {e!r}", flush=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
