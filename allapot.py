#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A FELHŐ-REPÓ SZINKRONJA ÉS AZ ÁLLAPOT (state.json) BIZTONSÁGOS VISSZAÍRÁSA — felhő és Mac közös kódja.

2026-09-30: a Mac helyi felho-repója beragadt. Egy korábbi visszavonás (reset HEAD~1) egy MÁR FELTÖLTÖTT
commitot vett vissza, a fájljai követetlenül bent maradtak, és onnantól minden `git pull --rebase`
elhasalt („untracked files would be overwritten”). A hibát senki nem nézte, így a Mac 2 percenként
régi alapra commitolt, a push elutasítva, visszavonás, újra — fél napig. Közben egy `git push` 1 óra
40 percre beragadt, és a zár miatt a Mac semmit nem posztolt.

AZ ELV: az origin/main az igazság, a helyi repó csak másolat. Minden futás elején ahhoz igazodunk;
az egyetlen helyi érték, amit meg kell őrizni, a state.json új bejegyzése (mit posztolt a Mac) —
azt összefésüljük az originéval (kulcsok uniója), és úgy toljuk fel. Így két író (felhő és Mac)
sem tudja felülírni egymás bejegyzését, és nem lesz dupla poszt.
"""
from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# BatchMode: jelszó- vagy kulcs-kérdés helyett azonnal hibázzon; a ServerAlive a félig halott kapcsolatot bontja.
SSH = "ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4"


def git(cwd: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", SSH), "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["git", *args], 124, "", f"időtúllépés ({timeout} mp)")


def _olvas(cwd: Path, ref: str | None = None) -> dict:
    if ref is None:
        p = cwd / "state.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    r = git(cwd, "show", f"{ref}:state.json")
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}


def egyesit(origin: dict, helyi: dict) -> dict:
    """Kulcsok uniója; közös kulcsnál az origin értéke marad (mindkettő ugyanazt jelenti: kint van)."""
    return {**helyi, **origin}


def push_allapot(cwd: Path, uzenet: str, probak: int = 5) -> bool:
    """A helyi state.json új bejegyzéseit az originéval összefésülve feltolja. True = fent van."""
    helyi = _olvas(cwd)
    for _ in range(probak):
        if git(cwd, "fetch", "-q", "origin").returncode != 0:
            time.sleep(3); continue
        origin = _olvas(cwd, "origin/main")
        uj = egyesit(origin, helyi)
        if uj == origin:
            git(cwd, "reset", "-q", "--hard", "origin/main")
            return True                                   # nincs mit feltolni
        git(cwd, "reset", "-q", "--hard", "origin/main")
        (cwd / "state.json").write_text(json.dumps(uj, ensure_ascii=False, indent=2), encoding="utf-8")
        git(cwd, "add", "state.json")
        git(cwd, "-c", "user.name=state-bot", "-c", "user.email=rolcsa3@gmail.com", "commit", "-q", "-m", uzenet)
        if git(cwd, "push", "-q", "origin", "HEAD:main", timeout=180).returncode == 0:
            return True
        time.sleep(3)                                      # közben más is tolt → újra összefésüljük
    (cwd / "state.json").write_text(json.dumps(helyi, ensure_ascii=False, indent=2), encoding="utf-8")
    return False                                           # a bejegyzések helyben maradnak, a következő futás tolja


def mar_kint(cwd: Path, kulcs: str) -> bool:
    """Közvetlenül posztolás előtt: szerepel-e már a kulcs az origin legfrissebb state-jében? (dupla ellen)"""
    if git(cwd, "fetch", "-q", "origin", timeout=60).returncode != 0:
        return False                                       # nem tudjuk ellenőrizni → a helyi state dönt
    return kulcs in _olvas(cwd, "origin/main")


def szinkron(cwd: Path) -> bool:
    """A helyi repót az origin/main-re hozza; a helyi state-bejegyzéseket megőrzi és feltolja.

    False = nincs kapcsolat, vagy a helyi bejegyzéseket nem sikerült feltolni. Ilyenkor a Mac NE
    posztoljon: régi állapotból dolgozva duplán posztolhatna.
    """
    helyi = _olvas(cwd)
    if git(cwd, "fetch", "-q", "origin").returncode != 0:
        return False
    git(cwd, "rebase", "--abort")                          # egy félbemaradt rebase se akassza meg
    git(cwd, "reset", "-q", "--hard", "origin/main")
    git(cwd, "clean", "-q", "-fd", "--", "jobs", "videos")  # sikertelen átadások maradékai
    origin = _olvas(cwd)
    if egyesit(origin, helyi) == origin:
        return True
    (cwd / "state.json").write_text(json.dumps(helyi, ensure_ascii=False, indent=2), encoding="utf-8")
    return push_allapot(cwd, "state: mac (pótolt bejegyzés)")


def _teszt() -> None:
    """Két klón + egy „origin”: a 09-30-i beragadás és a párhuzamos state-írás, hálózat nélkül."""
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        git(t, "init", "-q", "--bare", "-b", "main", "origin.git")
        for nev in ("mac", "felho"):
            git(t, "clone", "-q", str(t / "origin.git"), nev)
            git(t / nev, "config", "user.name", nev); git(t / nev, "config", "user.email", f"{nev}@x")
        mac, felho = t / "mac", t / "felho"
        (mac / "jobs").mkdir(); (mac / "videos").mkdir()
        (mac / "state.json").write_text("{}")
        (mac / "jobs/a.json").write_text('{"x": 1}')
        git(mac, "add", "."); git(mac, "commit", "-q", "-m", "alap"); git(mac, "push", "-q", "origin", "HEAD:main")

        # 1) A beragadás: a felhőben már fent van egy commit, a Macen a fájljai követetlenül állnak,
        #    és egy követett fájl törölve van. A régi kóddal a pull --rebase itt elhasalt.
        git(felho, "pull", "-q", "origin", "main")
        (felho / "jobs/b.json").write_text('{"y": 2}')
        git(felho, "add", "."); git(felho, "commit", "-q", "-m", "atadas b"); git(felho, "push", "-q", "origin", "HEAD:main")
        (mac / "jobs/b.json").write_text('{"y": 2}')
        (mac / "jobs/a.json").unlink()
        (mac / "state.json").write_text('{"tt:a": "DRAFT mac"}')     # a Mac posztolt, de nem tolta fel
        assert szinkron(mac), "a szinkronnak helyre kell hoznia a beragadt repót"
        assert (mac / "jobs/a.json").exists() and (mac / "jobs/b.json").exists()
        assert _olvas(mac, "origin/main") == {"tt:a": "DRAFT mac"}, "a Mac bejegyzése nem veszhet el"

        # 2) Párhuzamos írás: a felhő és a Mac egyszerre ír a state-be — mindkét bejegyzésnek meg kell maradnia.
        git(felho, "pull", "-q", "origin", "main")
        (felho / "state.json").write_text(json.dumps({**_olvas(felho), "a": "POSTED felho"}))
        (mac / "state.json").write_text(json.dumps({**_olvas(mac), "tt:b": "DRAFT mac"}))
        assert push_allapot(felho, "state: posted")
        assert push_allapot(mac, "state: mac")
        vegso = _olvas(mac, "origin/main")
        assert vegso == {"tt:a": "DRAFT mac", "a": "POSTED felho", "tt:b": "DRAFT mac"}, vegso
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--teszt"]:
        _teszt(); sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "push":         # a GitHub-workflow hívja: python3 allapot.py push "state: posted"
        sys.exit(0 if push_allapot(ROOT, sys.argv[2]) else 1)
    print("használat: allapot.py push <üzenet> | --teszt"); sys.exit(2)
