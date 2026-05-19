# UPDATE.md — refresh data after a WoWs major version update

Run on the home machine (Win/Mac/Linux — wherever has Python + git + internet).

## When to run

After WoWs ships a major version (15.3 → 15.4, etc.). The bot will start
spitting parse errors if it tries to read a replay with a newer build than its
`specs/` dir.

Minor build bumps within a version usually work via the auto-spoof path in
`bin/wows_report`, but updating specs/ is more correct.

## Steps

### Option A — pull from wowsinfo/data mirror (recommended)

Works on any OS with Python 3 and git. Mirror typically updates within 24h of
a game release.

```bash
cd /path/to/wows_report_bot
python tools/update_specs.py            # creates specs_out/

# Verify
cat specs_out/metadata.toml             # check version + build

# Push to Linux bot
scp -r specs_out/ user@bot-host:/tmp/specs_new/
ssh user@bot-host '
    cd /path/to/wows_report_bot
    rm -rf specs && mv /tmp/specs_new/specs_out specs
'
```

### Option B — extract from local WoWs install (Win, freshest)

If you cannot wait for the mirror, run the wows-toolkit GUI (Windows release)
against your local WoWs install. It auto-extracts game data to
`%APPDATA%\wows-toolkit\game_data\builds\<build>\`. You can then package that
folder the same way as Option A's output (must contain `scripts/`,
`content/GameParams.data`, `metadata.toml`).

## Verify on the bot

```bash
./bin/wows_report /path/to/recent.wowsreplay
# stderr should NOT show "[spoof] ..." for replays of the matching version
```
