# wows_report_bot

Generate a Chinese-language battle report PNG from a World of Warships `.wowsreplay` file.
Designed to be subprocess-called from a QQ bot.

## What it does

```
.wowsreplay (15.x+, Asia or CN servers)
   → replayshark (Rust)  → JSON (per-player stats, deaths, chat)
   → render_battle_report.py (PIL)  → PNG (dark game-style report)
```

The PNG shows: per-team rosters with damage / kills / potential / spotting / raw_xp /
HP bar / death cause + killer / achievement icons, plus a death timeline and a
personal stats box for the replay owner.

## Directory layout

```
wows_report_bot/
├── bin/
│   ├── wows_report                # main entry (Python)
│   └── render_battle_report.py    # PNG renderer
├── data/                          # rarely-changing assets
│   ├── achievement_icons/         # ~400 PNG (from minimap_renderer)
│   ├── achievements.json          # ID → index map
│   ├── constants.json             # results-array index map (from wows-toolkit)
│   └── zh_sg.mo                   # gettext catalog for Chinese names
├── specs/                         # per-game-version (scp from home machine)
│   ├── metadata.toml              # version + build
│   ├── scripts/                   # entity defs (XML)
│   └── content/GameParams.data    # ship/achievement param dict
├── tools/
│   ├── update_specs.py            # refresh specs/ from wowsinfo/data mirror
│   └── replayshark_battle_report.patch
├── replayshark                    # Rust binary (built on Linux — see DEPLOY.md)
└── venv/                          # Python venv (built on Linux — see DEPLOY.md)
```

## Quick start

After DEPLOY.md is done on the Linux bot host:

```bash
/path/to/wows_report_bot/bin/wows_report /path/to/replay.wowsreplay [out_dir]
# stdout last line: /tmp/wows_report/<replay_basename>.png
```

## Workflow

| Frequency | Who | What |
|---|---|---|
| Once per host | Linux bot host | Run **DEPLOY.md** (install Rust, build replayshark, create venv) |
| Per major game update | Home machine (Win/Mac) | Run `tools/update_specs.py`, then `scp specs_out/ → bot:specs/` |
| Per replay request | Linux bot | `subprocess` call to `bin/wows_report` |

See also: `DEPLOY.md`, `UPDATE.md`.
