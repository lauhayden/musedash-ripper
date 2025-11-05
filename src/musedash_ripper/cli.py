"""Argparse-based CLI"""

import argparse
import logging
import multiprocessing
import pathlib
import signal
import threading

from musedash_ripper import core

logger = logging.getLogger(__name__)

STOP_EVENT = threading.Event()


def parse_args():
    """Parse CLI arguments"""
    parser = argparse.ArgumentParser(
        prog="musedash-ripper", description="Tool for ripping the Muse Dash soundtrack."
    )
    parser.add_argument(
        "--game-dir",
        default=core.detect_default_gamedir(),
        type=pathlib.Path,
        help="game directory with MuseDash.exe",
    )
    parser.add_argument(
        "--out-dir",
        default=core.DEFAULT_OUT_DIR,
        type=pathlib.Path,
        help="output directory for ripped music",
    )
    parser.add_argument(
        "--language",
        default="English",
        choices=core.LANGUAGES.keys(),
        help="language for song names, album names, and metadata",
    )
    parser.add_argument(
        "--no-album-dirs",
        action="store_true",
        help="do not place songs and covers into album folders",
    )
    parser.add_argument("--save-covers", action="store_true", help="export cover images as .png")
    parser.add_argument("--save-csv", action="store_true", help="export songs.csv")
    return parser.parse_args()


def sigint_handler(_signum, _frame):
    """Handle SIGINT gracefully"""
    STOP_EVENT.set()


def main():
    """Main entry point"""
    args = parse_args()
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGINT, sigint_handler)

    core.rip(
        game_dir=args.game_dir,
        output_dir=args.out_dir,
        language=args.language,
        album_dirs=not args.no_album_dirs,
        save_covers=args.save_covers,
        save_songs_csv=args.save_csv,
        progress=lambda x: None,
        stop_event=STOP_EVENT,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
