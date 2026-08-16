#!/usr/bin/env python3
"""Runner for the STAR TeamTalk bot.

Usage:
    uv run python run.py            # run with config.json settings
    uv run python run.py --no-star  # connect to TT only, no auto STAR connect
"""
import os
import sys
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot import StarTeamTalkBot, build_bot_from_config
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("star_tt_bot.runner")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-star", action="store_true", help="do not auto-connect to STAR")
    ap.add_argument("--star-uri", default=None, help="override STAR coagulator URI")
    args = ap.parse_args()

    cfg = dict(config.CONFIG)
    if args.star_uri:
        cfg["star_uri"] = args.star_uri

    bot = build_bot_from_config(cfg)

    try:
        bot.connect()
    except Exception as e:
        log.error("Failed to connect/login to TeamTalk: %s", e)
        return 1

    if not args.no_star and cfg.get("star_uri"):
        try:
            bot.coag.connect(cfg["star_uri"])
            log.info("Auto-connected to STAR coagulator (%d voices)", len(bot.coag.list_voices()))
        except Exception as e:
            log.warning("Could not auto-connect to STAR coagulator: %s", e)

    try:
        bot.run()
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        bot.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())