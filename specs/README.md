# specs/

Per-game-version data — **not committed to git**.

You must populate this directory before the first run. Two ways:

## A. Pull from wowsinfo/data mirror (easiest)

```bash
cd ..  # back to repo root
python tools/update_specs.py
# This writes to specs_out/ ; move its contents into specs/:
rm -rf specs/scripts specs/content specs/metadata.toml
mv specs_out/* specs/
rmdir specs_out
```

## B. Extract from local WoWs install (Win, freshest)

See `UPDATE.md` in the repo root.

## Expected layout

```
specs/
├── metadata.toml          # version = "15.3.0"   build = 12267945
├── scripts/               # entity definition XMLs (~500 KB)
│   ├── entities.xml
│   ├── components.xml
│   └── entity_defs/
└── content/
    └── GameParams.data    # game parameter dict (~15 MB)
```

Once populated, `bin/wows_report some.wowsreplay` should work.
