"""Core ripping functionality"""

import base64
import csv
import dataclasses
import glob
import io
import logging
import os
from threading import Event
from typing import BinaryIO, Callable, Dict, List, Optional

import fsb5

# We use JSON5 parsing because the albums JSON assets have trailing commas
import json5
from mutagen.oggvorbis import OggVorbis
from mutagen.flac import Picture
from PIL import Image
import UnityPy.classes

logger: logging.Logger = logging.getLogger(__name__)

# TODO: use pathlib
DATAS_DIR: str = os.path.join("MuseDash_Data", "StreamingAssets", "aa", "StandaloneWindows64")

# Remove these characters before writing filename
ILLEGAL_FILENAME_CHARS: str = '<>:"/\\|?*'

# default to Steam install location
DEFAULT_GAME_DIR: str = "C:\Program Files (x86)\Steam\steamapps\common\Muse Dash"
# default output folder is next to our .EXE
DEFAULT_OUT_DIR: str = os.path.join(os.getcwd(), "muse_dash_soundtrack")


# abbreviations for languages used by Muse Dash's assets
LANGUAGES: Dict[Optional[str], Optional[str]] = {
    None: None,
    "Chinese Simplified": "ChineseS",
    "Chinese Traditional": "ChineseT",
    "English": "English",
    "Japanese": "Japanese",
    "Korean": "Korean",
}


@dataclasses.dataclass
class Song:
    """Dataclass to store song metadata"""

    title: str  # human-friendly title
    artist: str  # human-friendly artist name
    album_number: int  # internal album number (1-indexed)
    album_name: str  # human-friendly album name
    track_number: int  # track number in the album (1-indexed)
    track_total: int  # number of tracks in the album
    asset_name: str  # internal code-friendly song name used
    music_name: str  # music data asset name
    cover_name: str  # cover data asset name
    genre: Optional[str] = None  # optional music genre


def fix_songs(songs: List[Song]) -> None:
    """Fix inconsistencies and typos in the song metadata"""
    for song in songs:
        # chaos_glitch's asset and cover names are mangled
        if song.cover_name == "chaos_glitch_cover":
            song.cover_name = "chaos_cover"
        if song.asset_name == "chaos_glitch":
            song.asset_name = "chaos"

        # misspelled "Everything" in "Cute is Everyting"
        song.album_name = song.album_name.replace("Everyting", "Everything")

        # if "_music" is in asset_name, it gets dropped
        song.asset_name = song.asset_name.replace("_music", "")

        # fm_17314_sugar_radio uses qu_jianhai_de_rizi's cover
        if song.asset_name == "fm_17314_sugar_radio":
            song.asset_name = "qu_jianhai_de_rizi"
            song.cover_name = "qu_jianhai_de_rizi_cover"


def normalize_songs(songs: List[Song]) -> None:
    """Apply global modifications to all the songs"""
    for song in songs:
        # prefix album name
        song.album_name = "Muse Dash - " + song.album_name

        # add genre
        song.genre = "Video Games"


def find_asset(
    env: UnityPy.Environment, object_type: str, name: str, raise_on_not_found: bool = True
) -> UnityPy.classes.NamedObject:
    """Find a specific asset in a bundle"""
    for obj in env.objects:
        if obj.type.name != object_type:
            continue
        data = obj.read()
        if data.name == name:
            return data
    if raise_on_not_found:
        raise FileNotFoundError(f"Could not find asset '{name}'")
    return None


def find_with_prefix(dir_path: str, prefix: str) -> str:
    """Find a file with a prefix in a folder"""
    results = glob.glob(os.path.join(dir_path, prefix) + "*")
    if len(results) != 1:
        raise FileNotFoundError(f"Could not find unique bundle file with prefix '{prefix}'")
    return results[0]


def load_json(bundle_path: str, asset_name: str) -> List:
    """Extract and parse JSON from a TextAsset in a bundle"""
    with open(bundle_path, "rb") as bundle_file:
        env = UnityPy.load(bundle_file)
        data = find_asset(env, "TextAsset", asset_name)
        return json5.loads(data.text)


def parse_config(game_dir: str, language: str, progress: Callable[[float], None]) -> List[Song]:
    """Parse the game configuration JSONs to create a list of Songs"""
    l_suffix = LANGUAGES.get(language)
    datas_path = os.path.join(game_dir, DATAS_DIR)

    # load the "albums" JSON containing info on all albums
    albums_path = find_with_prefix(datas_path, "config_others_assets_albums_")
    albums_json = load_json(albums_path, "albums")

    # load the language-specific albums JSON
    if l_suffix is not None:
        prefix = "config_" + l_suffix.lower() + "_assets_albums_" + l_suffix.lower() + "_"
        l_albums_path = find_with_prefix(datas_path, prefix)
        l_albums_json = load_json(l_albums_path, "albums_" + l_suffix)
        assert len(albums_json) == len(l_albums_json)
    else:
        l_albums_json = [{}] * len(albums_json)

    # iterate through the albums
    songs = []
    for album_num, (album_entry, l_album_entry) in enumerate(zip(albums_json, l_albums_json), 1):
        # overlay language-specific stuff onto general album entry
        album_entry.update(l_album_entry)

        if not album_entry["jsonName"]:
            # Just as Planned is listed as an album without a jsonName
            continue

        # load individual album JSON
        prefix = "config_others_assets_" + album_entry["jsonName"].lower() + "_"
        entry_path = find_with_prefix(datas_path, prefix)
        entry_json = load_json(entry_path, album_entry["jsonName"])

        # load the language-specific individual album JSON
        if l_suffix is not None:
            prefix = (
                "config_"
                + l_suffix.lower()
                + "_assets_"
                + album_entry["jsonName"].lower()
                + "_"
                + l_suffix.lower()
                + "_"
            )
            l_entry_path = find_with_prefix(datas_path, prefix)
            l_entry_json = load_json(l_entry_path, album_entry["jsonName"] + "_" + l_suffix)
            assert len(entry_json) == len(l_entry_json)
        else:
            l_entry_json = [{}] * len(entry_json)

        for track_num, (song_entry, l_song_entry) in enumerate(
            zip(entry_json, l_entry_json), start=1
        ):
            # overlay the language-specific stuff onto general song entry
            song_entry.update(l_song_entry)

            # construct Song from song and album entries
            # asset_name reconstructed from cover_name
            assert song_entry["cover"].endswith("_cover")
            asset_name = song_entry["cover"][: -len("_cover")]
            songs.append(
                Song(
                    title=song_entry["name"],
                    artist=song_entry["author"],
                    album_number=int(album_entry["jsonName"].lstrip("ALBUM")),
                    album_name=album_entry["title"],
                    track_number=track_num,
                    track_total=len(entry_json),
                    asset_name=asset_name,
                    music_name=song_entry["music"],
                    cover_name=song_entry["cover"],
                )
            )

        progress(album_num / len(albums_json) * 100)
    return sorted(songs, key=lambda song: (song.album_number, song.track_number))


def extract_music(game_dir: str, song: Song) -> io.BytesIO:
    """Find and extract the music file from game assets given a Song"""
    datas_path = os.path.join(game_dir, DATAS_DIR)
    prefix = "music_assets_" + song.music_name + "_"
    music_path = find_with_prefix(datas_path, prefix)
    with open(music_path, "rb") as music_file:
        env = UnityPy.load(music_file)
        data = find_asset(env, "AudioClip", song.music_name)

        # use python-fsb5 to rebuild the Ogg Vorbis file from FSB5 compressed
        af = fsb5.FSB5(data.m_AudioData)
        # there should only be one track
        assert len(af.samples) == 1
        return io.BytesIO(af.rebuild_sample(af.samples[0]).tobytes())


def extract_cover(game_dir: str, song: Song) -> Image:
    """Find and extract a cover image from game assets given a Song"""
    datas_path = os.path.join(game_dir, DATAS_DIR)
    prefix = "song_" + song.asset_name + "_assets_all_"
    assets_path = find_with_prefix(datas_path, prefix)
    with open(assets_path, "rb") as assets_file:
        env = UnityPy.load(assets_file)
        return find_asset(env, "Texture2D", song.cover_name).image


def embed_metadata(music_file: io.BytesIO, cover_image: Image, song: Song) -> None:
    """Add metadata to extracted OGG files.

    For details on the METADATA_BLOCK_PICTURE struct format, see
    https://xiph.org/flac/format.html#metadata_block_picture
    """
    music_file.seek(0)
    audio = OggVorbis(music_file)
    audio["title"] = song.title
    audio["artist"] = song.artist
    audio["album"] = song.album_name
    audio["tracknumber"] = str(song.track_number)
    audio["tracktotal"] = str(song.track_total)
    if song.genre is not None:
        audio["genre"] = song.genre
    picture = Picture()

    # PIL does not allow for direct saving to bytes
    cover_image_file = io.BytesIO()
    cover_image.save(cover_image_file, format="png")
    picture.data = cover_image_file.getvalue()

    picture.type = 3  # Cover (front)
    picture.mime = "image/png"
    picture.width = cover_image.width
    picture.height = cover_image.height

    # PIL does not give depth, so we assert then hardcode
    assert cover_image.mode == "RGBA"
    picture.depth = 32

    audio["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
    audio.save(music_file)


def normalize_path_segment(path: str) -> str:
    """Remove illegal characters from a path"""
    for char in ILLEGAL_FILENAME_CHARS:
        path = path.replace(char, "_")
    return path


def songs_to_csv(songs: List[Song], csv_file: BinaryIO) -> None:
    """Dump a list of Songs to a CSV file"""
    # write a byte order mark so Excel recognizes CSV as UTF-8
    csv_file.write("\ufeff")
    # don't include empty genre in CSV file
    field_names = [field.name for field in dataclasses.fields(Song) if field.name != "genre"]
    writer = csv.DictWriter(csv_file, field_names)
    writer.writeheader()
    for song in songs:
        row = dataclasses.asdict(song)
        row.pop("genre")
        writer.writerow(row)


def rip(
    game_dir: str,
    output_dir: str,
    language: str,
    album_dirs: bool,
    save_covers: bool,
    save_songs_csv: bool,
    progress: Callable[[float], None],
    stop_event: Event,
) -> None:
    """Rip the soundtrack from an installation of Muse Dash"""
    progress(0)

    # validate input
    if not os.path.exists(os.path.join(game_dir, "MuseDash.exe")):
        raise ValueError("Could not find MuseDash.exe in game folder")

    logger.info("Starting rip...")
    logger.info("game_dir: %s", game_dir)
    logger.info("output_dir: %s", output_dir)
    logger.info("album_dirs: %s", album_dirs)
    logger.info("save_covers: %s", save_covers)
    logger.info("save_songs_csv: %s", save_songs_csv)

    os.makedirs(output_dir, exist_ok=True)
    # parse_config is ~4% of the total time
    logger.info("Parsing game config...")
    songs = parse_config(game_dir, language, progress=lambda x: progress(x * 4 / 100))
    fix_songs(songs)
    if save_songs_csv:
        logger.info("Saving songs.csv...")
        with open(
            os.path.join(output_dir, "songs.csv"), "wt", newline="", encoding="utf-8"
        ) as csv_file:
            songs_to_csv(songs, csv_file)
    normalize_songs(songs)
    if save_covers:
        os.makedirs(os.path.join(output_dir, "covers"), exist_ok=True)
    num_albums = len(set(song.album_number for song in songs))
    logger.info("%s songs in %s albums found.", len(songs), num_albums)
    if stop_event.is_set():
        return

    for song_num, song in enumerate(songs, start=1):
        logger.info("Exporting song: %s by %s", song.title, song.artist)
        album_dirname = normalize_path_segment(song.album_name)
        song_filestem = normalize_path_segment(song.title)
        music = extract_music(game_dir, song)
        cover = extract_cover(game_dir, song)
        embed_metadata(music, cover, song)
        if album_dirs:
            os.makedirs(os.path.join(output_dir, album_dirname), exist_ok=True)
            music_filename = os.path.join(output_dir, album_dirname, song_filestem + ".ogg")
        else:
            music_filename = os.path.join(output_dir, song_filestem + ".ogg")
        with open(music_filename, "wb") as music_file:
            music_file.write(music.getvalue())
        if save_covers:
            if album_dirs:
                os.makedirs(os.path.join(output_dir, "covers", album_dirname), exist_ok=True)
                cover_filename = os.path.join(
                    output_dir, "covers", album_dirname, song_filestem + ".png"
                )
            else:
                cover_filename = os.path.join(output_dir, "covers", song_filestem + ".png")
            with open(cover_filename, "wb") as cover_file:
                cover.save(cover_file, format="png")
        progress(4 + 96 * song_num / len(songs))
        if stop_event.is_set():
            return

    logger.info("Done!")
