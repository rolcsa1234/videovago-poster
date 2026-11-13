#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NAGY (100 MB fölötti / nem átcsomagolható) EREDETI VIDEÓK A FELHŐN ÁT — bitre azonosan (2026-11-13).

MIÉRT: a GitHub 100 MB fölötti fájlt nem fogad el, ezért eddig minden nagy videó a Mac-ágon ment, és
lecsukott fedéllel elmaradt (11-13: az AO14 két órát késett). Ákos: újrakódolni tilos.

HOGYAN: a Mac az eredetit ≤90 MB-os darabokra vágja, és egy KÜLÖN, előzmény nélküli ágra tolja
(`nagy/<slug>`, nem a main-be). A futó a posztolás előtt letölti és összefűzi (sha256-tal ellenőrizve),
posztolás után az ágat törli. Így a main előzménye nem hízik a nagy fájloktól (a törölt ág objektumait
a GitHub idővel eldobja), és a checkout sem húzza le őket minden futásnál.

Job-mezők: "video": "_nagy/<slug>.mp4" (helyi, gitignore-olt), "darabok": {"ag", "sha256", "meret", "db"}.
"""
from __future__ import annotations
import hashlib, os, shutil, subprocess, tempfile
from pathlib import Path

import allapot

DARAB = 90 * 1024 * 1024
PUSH_IDO = 1800          # mp; a 250 MB-os feltöltés lassú vonalon is elfér
REPO_URL = os.environ.get("NAGY_REPO", "git@github.com:rolcsa1234/videovago-poster.git")
# fix dátum → ugyanaz a fájl ugyanazt a commit-sha-t adja, így az újrapróbálás felismeri a már fent lévő ágat
FIX_DATUM = {"GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
             "GIT_AUTHOR_NAME": "mac-atad", "GIT_AUTHOR_EMAIL": "mac-atad@users.noreply.github.com",
             "GIT_COMMITTER_NAME": "mac-atad", "GIT_COMMITTER_EMAIL": "mac-atad@users.noreply.github.com"}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blokk in iter(lambda: f.read(1 << 20), b""):
            h.update(blokk)
    return h.hexdigest()


def _run(cwd: Path, *args: str, bemenet: bytes | None = None, env: dict | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, input=bemenet, capture_output=True, env={**os.environ, **(env or {})})
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {r.stderr.decode(errors='replace')[-300:]}")
    return r.stdout.decode().strip()


def feltolt(video: Path, slug: str) -> dict:
    """MAC: az eredetit darabokban a nagy/<slug> ágra tolja. Visszaad: a job „darabok” mezője. Hibánál kivételt dob."""
    ag = f"nagy/{slug}"
    with tempfile.TemporaryDirectory() as t:     # külön csupasz repó: a Mac felho/.git-je sem hízik a daraboktól
        repo = Path(t) / "r.git"
        _run(Path(t), "init", "-q", "--bare", str(repo))
        sorok, db = [], 0
        with open(video, "rb") as f:
            while blokk := f.read(DARAB):
                sha = _run(repo, "hash-object", "-w", "--stdin", bemenet=blokk)
                sorok.append(f"100644 blob {sha}\t{db:03d}")
                db += 1
        fa = _run(repo, "mktree", bemenet=("\n".join(sorok) + "\n").encode())
        commit = _run(repo, "commit-tree", fa, "-m", f"nagy: {slug} ({db} darab)", env=FIX_DATUM)
        fent = allapot.git(repo, "ls-remote", REPO_URL, f"refs/heads/{ag}")
        if fent.returncode != 0:
            raise RuntimeError(f"ls-remote: {fent.stderr[-200:]}")
        if commit not in fent.stdout:
            p = allapot.git(repo, "push", "-q", "--force", REPO_URL, f"{commit}:refs/heads/{ag}", timeout=PUSH_IDO)
            if p.returncode != 0:
                raise RuntimeError(f"push {ag}: {p.stderr.strip()[-300:]}")
    return {"ag": ag, "sha256": _sha256(video), "meret": video.stat().st_size, "db": db}


def helyi(root: Path, job: dict) -> Path:
    """FUTÓ: a job videójának helyi útja; nagy jobnál letölti és összefűzi az ágat, bitre ellenőrizve."""
    cel = root / job["video"]
    d = job.get("darabok")
    if not d:
        return cel
    if cel.exists() and cel.stat().st_size == d["meret"] and _sha256(cel) == d["sha256"]:
        return cel
    f = allapot.git(root, "fetch", "-q", "--depth", "1", "origin", f"refs/heads/{d['ag']}", timeout=PUSH_IDO)
    if f.returncode != 0:
        raise RuntimeError(f"a {d['ag']} ág nem tölthető le: {f.stderr.strip()[-200:]}")
    cel.parent.mkdir(parents=True, exist_ok=True)
    tmp = cel.with_suffix(".tmp")
    with open(tmp, "wb") as ki:
        for i in range(d["db"]):
            p = subprocess.Popen(["git", "cat-file", "blob", f"FETCH_HEAD:{i:03d}"], cwd=root, stdout=subprocess.PIPE)
            shutil.copyfileobj(p.stdout, ki)
            if p.wait() != 0:
                raise RuntimeError(f"hiányzó darab: {d['ag']}:{i:03d}")
    sha = _sha256(tmp)
    if tmp.stat().st_size != d["meret"] or sha != d["sha256"]:
        tmp.unlink()
        raise RuntimeError(f"összefűzés eltér az eredetitől ({d['ag']}: sha {sha[:12]} ≠ {d['sha256'][:12]})")
    tmp.replace(cel)
    print(f"  🧩 {d['ag']}: {d['db']} darab összefűzve, {d['meret'] / 2**20:.1f} MB, sha256 egyezik az eredetivel ({sha[:16]}…)",
          flush=True)
    return cel


def _kesz(slug: str, job: dict, state: dict) -> bool:
    ig = job.get("csak_tiktok") or slug in state
    tt_ertek = str(state.get(f"tt:{slug}", ""))
    tt = not job.get("tiktok") or (tt_ertek and not tt_ertek.startswith("tiktok:FELTOLTVE"))
    return bool(ig and tt)


def torolheto(jobs: list[tuple[str, dict]], state: dict) -> list[str]:
    """Azok a nagy/* ágak, amelyekre minden hivatkozó job (a ~proba ikreket is beleértve) kint van."""
    agak: dict[str, bool] = {}
    for slug, job in jobs:
        if job.get("darabok"):
            ag = job["darabok"]["ag"]
            agak[ag] = agak.get(ag, True) and _kesz(slug, job, state)
    return [ag for ag, kesz in agak.items() if kesz]


def takarit(root: Path) -> None:
    """Posztolás után: a már nem kellő nagy/* ágakat törli az originről (és a helyi összefűzött fájlt)."""
    import json
    state = json.loads((root / "state.json").read_text()) if (root / "state.json").exists() else {}
    jobs = [(jf.stem, json.loads(jf.read_text())) for jf in sorted(root.glob("jobs/*.json"))]
    fent = allapot.git(root, "ls-remote", "--heads", "origin", "nagy/*")
    if fent.returncode != 0:
        print(f"  ⚠️ nagy-takarítás: ls-remote hiba ({fent.stderr.strip()[-150:]})"); return
    for ag in torolheto(jobs, state):
        if f"refs/heads/{ag}" in fent.stdout:
            r = allapot.git(root, "push", "-q", "origin", "--delete", ag)
            print(f"  🧹 {ag} törölve" if r.returncode == 0 else f"  ⚠️ {ag} törlése nem ment: {r.stderr.strip()[-150:]}")
    for slug, job in jobs:
        if job.get("darabok") and job["darabok"]["ag"] in torolheto(jobs, state):
            (root / job["video"]).unlink(missing_ok=True)


def _teszt() -> None:
    """Hálózat nélkül: darabolás → helyi „origin” → összefűzés bitre azonos; takarítási döntés."""
    global REPO_URL, DARAB
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        allapot.git(t, "init", "-q", "--bare", "-b", "main", "origin.git")
        allapot.git(t, "clone", "-q", str(t / "origin.git"), "klon")
        eredeti = t / "v.mp4"
        eredeti.write_bytes(os.urandom(2500) + b"\x00" * 1000)
        REPO_URL, DARAB = str(t / "origin.git"), 1024
        d = feltolt(eredeti, "x")
        assert d["db"] == 4 and d["meret"] == 3500
        assert feltolt(eredeti, "x") == d                     # újrapróbálás: ugyanaz a commit, nincs újratöltés
        job = {"video": "_nagy/x.mp4", "darabok": d, "tiktok": {}}
        kesz = helyi(t / "klon", job)
        assert kesz.read_bytes() == eredeti.read_bytes()
        assert helyi(t / "klon", job) == kesz                 # már megvan: nem tölti le újra
        rossz = {**job, "video": "_nagy/y.mp4", "darabok": {**d, "sha256": "0" * 64}}
        try:
            helyi(t / "klon", rossz); raise AssertionError("eltérő sha-t elfogadott")
        except RuntimeError:
            pass
    j = {"darabok": {"ag": "nagy/a"}, "tiktok": {"caption": "c"}}
    iker = {"darabok": {"ag": "nagy/a"}}
    assert torolheto([("a", j), ("a~proba", iker)], {"a": "POSTED", "tt:a": "tiktok:DRAFT"}) == []   # az iker még nincs kint
    assert torolheto([("a", j), ("a~proba", iker)], {"a": "P", "a~proba": "P", "tt:a": "tiktok:DRAFT"}) == ["nagy/a"]
    assert torolheto([("a", j)], {"a": "P", "tt:a": "tiktok:FELTOLTVE(feldolgozás alatt) id=1"}) == []  # FAILED esetén újra kell
    assert torolheto([("a", {**j, "csak_tiktok": True})], {"tt:a": "tiktok:DRAFT"}) == ["nagy/a"]
    print("ok")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--teszt"]:
        _teszt()
    elif sys.argv[1:] == ["takarit"]:
        takarit(Path(__file__).resolve().parent)
    else:
        print("használat: nagy.py --teszt | takarit"); sys.exit(2)
