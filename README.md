# videovago-poster — felhő IG- és TikTok-posztoló

Mac-független posztolás GitHub Actionsből. Az Instagram a videót a repó nyilvános raw URL-jéről
húzza le (nincs tunnel), a TikTok inbox-draftot kap (`tt_post.py`). Állapot: `state.json`
(IG: `<slug>`, TikTok: `tt:<slug>`).

## Honnan jönnek a jobok
A Mac `felho_atad.py`-ja 96 órával előre feltölti a `jobs/` és `videos/` mappába, ami esedékes lesz.
Kézzel nem kell ide semmit tenni.

## Mikor fut (2026-09-30 óta)
A GitHub `*/10` ütemezése a gyakorlatban csak 5–6 óránként indult el, ezért a posztok órákat késtek.
Most három út indítja, ebben a sorrendben:
1. **Ébren lévő Mac:** esedékességkor egy üres commitot tol (`felho_atad._tick`), a push azonnal indítja a futást.
2. **Külső időzítő (kikapcsolt Machez):** cron-job.org 5 percenként `workflow_dispatch`-et hív (lent).
3. **GitHub-ütemezés:** tartalék.
A Mac-fallback (`felho_fallback.py`) csak akkor posztol, ha 20 percnél régebben esedékes valami, és épp nem fut felhő.

## Külső időzítő beállítása (egyszer, kb. 5 perc)
1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
   - Repository access: **Only select repositories** → `videovago-poster`
   - Permissions → Repository permissions → **Actions: Read and write** (minden más: No access)
   - Lejárat: a leghosszabb, amit enged; a lejárat napját írd be a naptárba
2. cron-job.org → Create cronjob
   - URL: `https://api.github.com/repos/rolcsa1234/videovago-poster/actions/workflows/post.yml/dispatches`
   - Schedule: minden 5. perc
   - Advanced → Request method: **POST**
   - Headers: `Accept: application/vnd.github+json` · `Authorization: Bearer <a token>` · `X-GitHub-Api-Version: 2022-11-28`
   - Request body: `{"ref":"main"}`
3. Execute now → a válasz **204** legyen, és a repó Actions fülén megjelenik egy `workflow_dispatch` futás.

## Secrets (repo Settings → Secrets → Actions)
- `IG_ACCESS_TOKEN` — kb. 60 naponta újra kell másolni (a Mac a sajátját frissíti, ezt nem)
- `IG_USER_ID`
- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`

## Állapot és ütközés
- Az `allapot.py` írja vissza a `state.json`-t: az origin az igazság, a felhő és a Mac bejegyzéseinek
  uniója kerül fel, újrapróbálással. Önteszt: `python3 allapot.py --teszt`.
- TikTok: ha a feldolgozás 3 percnél tovább tart, `FELTOLTVE(feldolgozás alatt)` kerül a state-be,
  és a következő futás ellenőrzi. Újra nem tölti fel, így nincs dupla draft.

## Figyelem
- A `publish_at` időzónás ISO-idő, a nyári/téli átállás nem gond.
- Kiposztolt videók törölhetők a repóból, hogy ne hízzon.
