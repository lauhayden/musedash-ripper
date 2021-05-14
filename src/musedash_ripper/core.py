"""Core ripping functionality"""

import base64
import contextlib
import csv
import dataclasses
import io
import logging
import os
from typing import Optional

# We use JSON5 parsing because the albums JSON asset has trailing commas
import json5
from mutagen.oggvorbis import OggVorbis
from mutagen.flac import Picture
from PIL import ImageOps
import unitypack

logger = logging.getLogger(__name__)

# TODO: use pathlib
DATAS_DIR = os.path.join("MuseDash_Data", "StreamingAssets", "AssetBundles", "datas")
CONFIGS_DIR = os.path.join(DATAS_DIR, "configs")
MUSICS_DIR = os.path.join(DATAS_DIR, "audios", "stage", "musics")
COVER_DIR = os.path.join(DATAS_DIR, "cover")

# Remove these characters before writing filename
ILLEGAL_FILENAME_CHARS = '<>:"/\\|?*'

DEFAULT_GAME_DIR = "C:\Program Files (x86)\Steam\steamapps\common\Muse Dash"
DEFAULT_OUT_DIR = os.path.join(os.getcwd(), "output")


LANGUAGES = {
    None: None,
    "Chinese Simplified": "ChineseS",
    "Chinese Traditional": "ChineseT",
    "English": "English",
    "Japanese": "Japanese",
    "Korean": "Korean",
}


@dataclasses.dataclass
class Song:
    title: str
    artist: str
    album_number: int
    album_name: str
    track_number: int
    track_total: int
    music_name: str
    cover_name: str
    genre: Optional[str] = None


def fix_songs(songs):
    for song in songs:
        # fix chaos_glitch_cover not existing
        if song.cover_name == "chaos_glitch_cover":
            song.cover_name = "chaos_cover"


def normalize_songs(songs):
    for song in songs:
        # prefix album name
        song.album_name = "Muse Dash - " + song.album_name

        # add genre
        song.genre = "Video Games"


def find_asset(bundle, object_type, name, raise_on_not_found=True):
    for asset in bundle.assets:
        for object in asset.objects.values():
            if object.type != object_type:
                continue
            data = object.read()
            if data.name == name:
                return data
    if raise_on_not_found:
        raise FileNotFoundError(f"Could not find asset '{name}'")
    return None


def parse_config(game_dir, language, progress):
    language_suffix = LANGUAGES.get(language)
    with contextlib.ExitStack() as stack:
        others_path = os.path.join(game_dir, CONFIGS_DIR, "others")
        others_file = stack.enter_context(open(others_path, "rb"))
        others_bundle = unitypack.load(others_file)
        if language_suffix is not None:
            language_path = os.path.join(game_dir, CONFIGS_DIR, language_suffix.lower())
            language_file = stack.enter_context(open(language_path, "rb"))
            language_bundle = unitypack.load(language_file)

        # find and parse albums JSON
        albums_data = find_asset(others_bundle, "TextAsset", "albums")
        albums_json = json5.loads(albums_data.script)
        if language_suffix is not None:
            l_albums_data = find_asset(language_bundle, "TextAsset", "albums_" + language_suffix)
            l_albums_json = json5.loads(l_albums_data.script)
        else:
            l_albums_json = [{}] * len(albums_json)

        songs = []
        # find and parse individual ALBUM* JSONs
        for album_num, (album_entry, l_album_entry) in enumerate(
            zip(albums_json, l_albums_json), 1
        ):
            album_entry.update(l_album_entry)
            if not album_entry["jsonName"]:
                # Just as Planned is listed as an album without a jsonName
                continue
            entry_data = find_asset(others_bundle, "TextAsset", album_entry["jsonName"])
            entry_json = json5.loads(entry_data.script)
            if language_suffix is not None:
                asset_name = album_entry["jsonName"] + "_" + language_suffix
                l_entry_data = find_asset(language_bundle, "TextAsset", asset_name)
                l_entry_json = json5.loads(l_entry_data.script)
            else:
                l_entry_json = [{}] * len(entry_json)

            for track_num, (song_entry, l_song_entry) in enumerate(
                zip(entry_json, l_entry_json), start=1
            ):
                song_entry.update(l_song_entry)
                songs.append(
                    Song(
                        title=song_entry["name"],
                        artist=song_entry["author"],
                        album_number=int(album_entry["jsonName"].lstrip("ALBUM")),
                        album_name=album_entry["title"],
                        track_number=track_num,
                        track_total=len(entry_json),
                        music_name=song_entry["music"],
                        cover_name=song_entry["cover"],
                    )
                )
            progress(album_num / len(albums_json) * 100)
    return sorted(songs, key=lambda song: (song.album_number, song.track_number))


def extract_music(game_dir, music_name):
    music_path = os.path.join(game_dir, MUSICS_DIR, music_name)
    with open(music_path, "rb") as music_file:
        bundle = unitypack.load(music_file)
        data = find_asset(bundle, "AudioClip", music_name)
        samples = unitypack.utils.extract_audioclip_samples(data)
        assert len(samples) == 1
        ogg_name, bindata = list(samples.items())[0]
        assert ogg_name == music_name + ".ogg"
        return io.BytesIO(bindata.tobytes())


def extract_cover(game_dir, album_number, cover_name):
    if album_number == 1:
        # default songs (album 1) is
        bundle_names = [f"01_part{part_num}" for part_num in range(1, 10)]
    else:
        bundle_names = [f"{album_number:02}"]
    for bundle_name in bundle_names:
        bundle_path = os.path.join(game_dir, COVER_DIR, bundle_name)
        with open(bundle_path, "rb") as bundle_file:
            bundle = unitypack.load(bundle_file)
            data = find_asset(bundle, "Texture2D", cover_name, raise_on_not_found=False)
            if data is not None:
                # Texture2D objects are flipped
                return ImageOps.flip(data.image)
    raise FileNotFoundError(f"Could not find cover asset '{cover_name}' in album {album_number}")


def embed_metadata(music_file, cover_image, song):
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


def normalize_path_segment(path):
    for char in ILLEGAL_FILENAME_CHARS:
        path = path.replace(char, "_")
    return path


def songs_to_csv(songs, csv_file):
    # don't include empty genre in CSV file
    field_names = [field.name for field in dataclasses.fields(Song) if field.name != "genre"]
    writer = csv.DictWriter(csv_file, field_names)
    writer.writeheader()
    for song in songs:
        row = dataclasses.asdict(song)
        row.pop("genre")
        writer.writerow(row)


def rip(
    game_dir,
    output_dir,
    language,
    album_dirs,
    save_covers,
    save_songs_csv,
    progress,
    stop_event,
):
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
        music = extract_music(game_dir, song.music_name)
        cover = extract_cover(game_dir, song.album_number, song.cover_name)
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
