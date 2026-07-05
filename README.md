# videovago-poster — felhő IG-posztoló

Mac-független Instagram Reels ütemezett posztolás GitHub Actions cronból.
A videót a runnerben egy Cloudflare quick-tunnel teszi ideiglenesen publikussá,
az IG onnan húzza le (pull-from-URL), majd publish. Állapot: `state.json`.

## Új posztok feltöltése (Macről)
1. videó (<100MB!) + borító a `videos/` mappába
2. job JSON a `jobs/` mappába (video/cover/caption/publish_at)
3. `git add -A && git commit -m "day4" && git push`

## Secrets (repo Settings → Secrets → Actions)
- `IG_ACCESS_TOKEN` — 60 naponta frissítendő! (refresh_access_token)
- `IG_USER_ID`

## Figyelem
- Cron UTC-ben van — téli időszámításkor (CET=UTC+1) a post.yml-ben +1 óra eltolás kell.
- Kiposztolt videók törölhetők a repóból, hogy ne hízzon.
