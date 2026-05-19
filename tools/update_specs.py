#!/usr/bin/env python3
"""update_specs.py — refresh WoWs entity defs + GameParams.data.

Run on the home machine (Mac/Win/Linux) after a major game update.
Pulls fresh data from the wowsinfo/data community mirror (asia/global server)
into specs_out/, ready to scp to the Linux bot host.

Usage:
    python update_specs.py [--out DIR] [--repo URL] [--branch BRANCH]

After running:
    scp -r specs_out/ user@bot-host:/path/to/wows_report_bot/specs/
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_REPO = "https://github.com/wowsinfo/data.git"
DEFAULT_BRANCH = "master"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "specs_out"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def latest_build_from_commit(repo_dir: Path) -> tuple[str, int]:
    """Read latest commit message for live/scripts/ to extract version+build.
    Commit format: 'Update 15.3.0.0.12267945'."""
    out = subprocess.check_output(
        ["git", "log", "-1", "--pretty=%s", "--", "live/scripts"],
        cwd=repo_dir, text=True,
    ).strip()
    # e.g. "Update 15.3.0.0.12267945" → version 15.3.0, build 12267945
    parts = out.replace("Update ", "").split(".")
    if len(parts) < 5:
        raise RuntimeError(f"unexpected commit message format: {out!r}")
    version = ".".join(parts[:3])
    build = int(parts[4])
    return version, build


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"output dir (default: {DEFAULT_OUT})")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--branch", default=DEFAULT_BRANCH)
    ap.add_argument("--cache", type=Path,
                    default=Path("/tmp/wowsinfo_data_cache"),
                    help="local git clone cache dir")
    args = ap.parse_args()

    cache = args.cache.resolve()
    out = args.out.resolve()

    # Clone or pull
    if (cache / ".git").exists():
        print(f"updating existing cache at {cache}")
        run(["git", "-C", str(cache), "fetch", "origin", args.branch])
        run(["git", "-C", str(cache), "reset", "--hard", f"origin/{args.branch}"])
    else:
        print(f"cloning {args.repo} → {cache}")
        run(["git", "clone", "--depth", "5", "--branch", args.branch,
             args.repo, str(cache)])

    version, build = latest_build_from_commit(cache)
    print(f"\nlatest data: version {version} build {build}")

    # Build output layout
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "content").mkdir()

    src_scripts = cache / "live" / "scripts"
    src_gameparams = cache / "live" / "GameParams.data"
    if not src_scripts.is_dir():
        sys.exit(f"error: {src_scripts} missing — repo layout changed?")
    if not src_gameparams.is_file():
        sys.exit(f"error: {src_gameparams} missing — repo layout changed?")

    print(f"\ncopying scripts/ ...")
    shutil.copytree(src_scripts, out / "scripts")
    print(f"copying GameParams.data ...")
    shutil.copy(src_gameparams, out / "content" / "GameParams.data")

    (out / "metadata.toml").write_text(
        f'version = "{version}"\nbuild = {build}\n'
    )

    size_mb = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6
    print(f"\ndone — {out}  ({size_mb:.1f} MB)")
    print(f"\nNext: scp -r {out}/ user@bot-host:/path/to/wows_report_bot/specs/")


if __name__ == "__main__":
    main()
