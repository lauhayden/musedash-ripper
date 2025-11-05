"""Core ripping functionality"""

import base64
import csv
import concurrent.futures
import dataclasses
import io
import json
import logging
import os
import pathlib
import platform
import threading
from typing import Callable, Dict, Iterable, List, Optional, TextIO

import fsb5  # type: ignore
import mutagen.oggvorbis
import mutagen.flac
import PIL.Image
import pyjson5  # much faster than json5
import UnityPy.classes  # type: ignore
import UnityPy.helpers.ResourceReader

logger: logging.Logger = logging.getLogger(__name__)

DEBUG = os.getenv("MDRIPPER_DEBUG") is not None

ADDRESSABLES_DIR = pathlib.Path("MuseDash_Data", "StreamingAssets", "aa")
CATALOG_BUNDLE_PREFIX = "{UnityEngine.AddressableAssets.Addressables.RuntimePath}\\"

# Remove these characters before writing filename
ILLEGAL_FILENAME_CHARS = '<>:"/\\|?*'

# default output folder is next to our .EXE
DEFAULT_OUT_DIR = pathlib.Path.cwd() / "muse_dash_soundtrack"

# abbreviations for languages used by Muse Dash's assets
LANGUAGES: Dict[Optional[str], Optional[str]] = {
    None: None,
    "Chinese Simplified": "ChineseS",
    "Chinese Traditional": "ChineseT",
    "English": "English",
    "Japanese": "Japanese",
    "Korean": "Korean",
}

# how much percent of the overall ripping time is config parsing?
# this is rough and for the progress bar only. Depends on number of cores and such
CONFIG_PARSE_PROGRESS: float = 10


class UserError(Exception):
    """Exception for when the program was used incorrectly by the user"""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


@dataclasses.dataclass
class Song:
    """Dataclass to store song metadata"""

    title: str  # human-friendly title
    artist: str  # human-friendly artist name
    album_number: int  # internal album number (1-indexed)
    album_name: str  # human-friendly album name
    track_number: int  # track number in the album (1-indexed)
    track_total: int  # number of tracks in the album
    music_asset_name: str  # internal code-friendly name for "music" asset
    song_asset_name: str  # internal code-friendly name for "song" asset
    music_name: str  # music data asset name
    cover_name: str  # cover data asset name
    genre: Optional[str] = None  # optional music genre


def detect_default_gamedir() -> pathlib.Path:
    """Detect OS to get default game install location"""
    if platform.system() == "Windows":
        return pathlib.Path(
            "C:/", "Program Files (x86)", "Steam", "steamapps", "common", "Muse Dash"
        )
    if platform.system() == "Linux":
        return pathlib.Path.home() / pathlib.Path(
            ".local", "share", "Steam", "steamapps", "common", "Muse Dash"
        )
    raise ValueError("Unsupported platform")


def fix_songs(songs: List[Song]) -> None:
    """Fix inconsistencies and typos in the song metadata"""
    for song in songs:
        # misspelled "Everything" in "Cute is Everyting"
        song.album_name = song.album_name.replace("Everyting", "Everything")

        # if "_music" is in *_asset_name, it gets dropped
        song.music_asset_name = song.music_asset_name.replace("_music", "")
        song.song_asset_name = song.song_asset_name.replace("_music", "")

        # fm_17314_sugar_radio uses qu_jianhai_de_rizi's cover
        if song.song_asset_name == "fm_17314_sugar_radio":
            song.song_asset_name = "qu_jianhai_de_rizi"
            song.cover_name = "qu_jianhai_de_rizi_cover"

        # misty_memory (both versions) have their cover in the night version's bundle
        # this is contrary to what the Album JSON says
        if song.song_asset_name == "misty_memory_day_version":
            song.song_asset_name = "misty_memory_night_version"


def normalize_songs(songs: List[Song]) -> None:
    """Apply global modifications to all the songs"""
    for song in songs:
        # prefix album name
        song.album_name = "Muse Dash - " + song.album_name

        # add genre
        song.genre = "Video Games"


def find_asset(env: UnityPy.Environment, object_type: str, name: str):
    """Find a specific asset in a bundle

    No return type because Mypy has issues with the various UnityPy classes
    """
    for obj in env.objects:
        if obj.type.name != object_type:
            continue
        data = obj.read()
        if data.m_Name == name:
            return data
    raise FileNotFoundError(f"Could not find asset '{name}'")


def load_catalog(game_dir: pathlib.Path) -> List[str]:
    """Parse the Addressables catalog.json to get a list of all bundles"""
    catalog_path = game_dir / ADDRESSABLES_DIR / "catalog.json"
    with open(catalog_path, "rb") as catalog_file:
        # mypy decides that decode() does not take a file, pylint can't see inside pyjson5
        internal_ids = pyjson5.decode_io(catalog_file)["m_InternalIds"]  # type: ignore[arg-type] # pylint: disable=no-member

    if DEBUG:
        with pathlib.Path("internal_ids.json").open("wt", encoding="utf-8") as json_file:
            json.dump(internal_ids, json_file, indent=4)

    filtered = filter(lambda s: s.startswith(CATALOG_BUNDLE_PREFIX), internal_ids)
    return list(map(lambda s: s[len(CATALOG_BUNDLE_PREFIX) :], filtered))


def find_with_prefix(game_dir: pathlib.Path, catalog_list: List[str], prefix: str) -> pathlib.Path:
    """Find a file with a prefix in a folder"""
    addressables_path = game_dir / ADDRESSABLES_DIR
    filtered = list(filter(lambda s: s.startswith("StandaloneWindows64\\" + prefix), catalog_list))
    if len(filtered) != 1:
        raise FileNotFoundError(f"Could not find unique bundle file with prefix '{prefix}'")
    full_path = addressables_path / pathlib.Path(*filtered[0].split("\\"))
    if not full_path.exists():
        raise FileNotFoundError(f"Bundle file not found: '{full_path}'")
    return full_path


def load_json(bundle_path: pathlib.Path, asset_name: str) -> List:
    """Extract and parse JSON from a TextAsset in a bundle"""
    with bundle_path.open("rb") as bundle_file:
        env = UnityPy.load(bundle_file)
        data = find_asset(env, "TextAsset", asset_name)
        # We use JSON5 parsing because the albums JSON assets have trailing commas
        # pylint can't see inside pyjson5
        return pyjson5.decode(data.m_Script)  # pylint: disable=no-member


def parallel_execute(
    *,
    executor: concurrent.futures.ProcessPoolExecutor,
    stop_event: threading.Event,
    func: Callable,
    kwargs: Dict,
    iterable: Iterable,
    done_callback: Callable,
) -> bool:
    """Use a ProcessPoolExecutor to run func in parallel with error handling"""
    not_done = set()
    for item in iterable:
        not_done.add(executor.submit(func, song=item, **kwargs))
    error = None
    all_done = True
    while not_done:
        done, not_done = concurrent.futures.wait(
            not_done, return_when=concurrent.futures.FIRST_COMPLETED
        )
        for future in done:
            try:
                done_callback(future.result())
            except concurrent.futures.CancelledError:
                all_done = False
            except Exception as err:  # pylint: disable=broad-except
                error = err
        if stop_event.is_set() or error:
            for future in not_done:
                future.cancel()
    if error:
        raise error
    return all_done


def parse_config(
    game_dir: pathlib.Path,
    catalog_list: List[str],
    language: Optional[str],
    progress: Callable[[float], None],
) -> List[Song]:
    """Parse the game configuration JSONs to create a list of Songs"""
    l_suffix = LANGUAGES.get(language)
    # load the "albums" JSON containing info on all albums
    albums_path = find_with_prefix(game_dir, catalog_list, "config_others_assets_albums_")
    albums_json = load_json(albums_path, "albums")
    if DEBUG:
        with pathlib.Path("albums.json").open("wt", encoding="utf-8") as json_file:
            json.dump(albums_json, json_file, indent=4)

    # load the language-specific albums JSON
    if l_suffix is not None:
        prefix = "config_" + l_suffix.lower() + "_assets_albums_" + l_suffix.lower() + "_"
        l_albums_path = find_with_prefix(game_dir, catalog_list, prefix)
        l_albums_json = load_json(l_albums_path, "albums_" + l_suffix)
        if DEBUG:
            with pathlib.Path("albums_l.json").open("wt", encoding="utf-8") as json_file:
                json.dump(l_albums_json, json_file, indent=4)
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
        entry_path = find_with_prefix(game_dir, catalog_list, prefix)
        entry_json = load_json(entry_path, album_entry["jsonName"])
        if DEBUG:
            folder = pathlib.Path("album_jsons")
            folder.mkdir(exist_ok=True)
            file_name = album_entry["jsonName"].lower() + ".json"
            with (folder / file_name).open("wt", encoding="utf-8") as json_file:
                json.dump(entry_json, json_file, indent=4)

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
            l_entry_path = find_with_prefix(game_dir, catalog_list, prefix)
            l_entry_json = load_json(l_entry_path, album_entry["jsonName"] + "_" + l_suffix)
            if DEBUG:
                file_name = album_entry["jsonName"].lower() + "_l.json"
                with (pathlib.Path("album_jsons") / file_name).open(
                    "wt", encoding="utf-8"
                ) as json_file:
                    json.dump(l_entry_json, json_file, indent=4)

            if len(entry_json) != len(l_entry_json):
                logger.warning("%s has differing length JSONs", album_entry["jsonName"])
        else:
            l_entry_json = [{}] * len(entry_json)

        for track_num, (song_entry, l_song_entry) in enumerate(
            zip(entry_json, l_entry_json), start=1
        ):
            # overlay the language-specific stuff onto general song entry
            song_entry.update(l_song_entry)

            # construct Song from song and album entries
            assert song_entry["cover"].endswith("_cover")
            song_asset_name = song_entry["cover"][: -len("_cover")]
            assert song_entry["music"].endswith("_music")
            music_asset_name = song_entry["music"][: -len("_music")]
            songs.append(
                Song(
                    title=song_entry["name"],
                    artist=song_entry["author"],
                    album_number=int(album_entry["jsonName"].lstrip("ALBUM")),
                    album_name=album_entry["title"],
                    track_number=track_num,
                    track_total=len(entry_json),
                    music_asset_name=music_asset_name,
                    song_asset_name=song_asset_name,
                    music_name=song_entry["music"],
                    cover_name=song_entry["cover"],
                )
            )

        progress(album_num / len(albums_json) * 100)
    return sorted(songs, key=lambda song: (song.album_number, song.track_number))


def extract_music(game_dir: pathlib.Path, catalog_list: List[str], song: Song) -> io.BytesIO:
    """Find and extract the music file from game assets given a Song"""
    prefix = "music_" + song.music_asset_name + "_assets_all"
    music_path = find_with_prefix(game_dir, catalog_list, prefix)
    with open(music_path, "rb") as music_file:
        env = UnityPy.load(music_file)
        data = find_asset(env, "AudioClip", song.music_name)

        # fetch the raw data bytes
        # see https://github.com/K0lb3/UnityPy/blob/master/UnityPy/export/AudioClipConverter.py
        if data.m_AudioData:
            audio_data = data.m_AudioData
        elif data.m_Resource:
            assert (
                data.object_reader is not None
            ), "AudioClip uses an external resource but object_reader is not set"
            resource = data.m_Resource
            audio_data = UnityPy.helpers.ResourceReader.get_resource_data(
                resource.m_Source,
                data.object_reader.assets_file,
                resource.m_Offset,
                resource.m_Size,
            )
        else:
            raise ValueError("AudioClip with neither m_AudioData nor m_Resource")

        # use python-fsb5 to rebuild the Ogg Vorbis file from FSB5 compressed
        fsb = fsb5.FSB5(audio_data)
        # there should only be one track
        assert len(fsb.samples) == 1
        return io.BytesIO(fsb.rebuild_sample(fsb.samples[0]).tobytes())


def extract_cover(game_dir: pathlib.Path, catalog_list: List[str], song: Song) -> PIL.Image.Image:
    """Find and extract a cover image from game assets given a Song"""
    prefix = "song_" + song.song_asset_name + "_assets_all_"
    assets_path = find_with_prefix(game_dir, catalog_list, prefix)
    with open(assets_path, "rb") as assets_file:
        env = UnityPy.load(assets_file)
        return find_asset(env, "Texture2D", song.cover_name).image


def embed_metadata(music_file: io.BytesIO, cover_image: PIL.Image.Image, song: Song) -> None:
    """Add metadata to extracted OGG files.

    For details on the METADATA_BLOCK_PICTURE struct format, see
    https://xiph.org/flac/format.html#metadata_block_picture
    """
    music_file.seek(0)
    audio = mutagen.oggvorbis.OggVorbis(music_file)
    audio["title"] = song.title
    audio["artist"] = song.artist
    audio["album"] = song.album_name
    audio["tracknumber"] = str(song.track_number)
    audio["tracktotal"] = str(song.track_total)
    if song.genre is not None:
        audio["genre"] = song.genre
    picture = mutagen.flac.Picture()

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


def normalize_path_segment(segment: str) -> str:
    """Remove illegal characters from a path"""
    for char in ILLEGAL_FILENAME_CHARS:
        segment = segment.replace(char, "_")
    return segment


def songs_to_csv(songs: List[Song], csv_file: TextIO) -> None:
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


def export_song(
    *,
    game_dir: pathlib.Path,
    catalog_list: List[str],
    output_dir: pathlib.Path,
    album_dirs: bool,
    save_covers: bool,
    song: Song,
) -> str:
    """Rip a single song"""
    album_dirname = normalize_path_segment(song.album_name)
    song_filestem = normalize_path_segment(song.title)
    music = extract_music(game_dir, catalog_list, song)
    cover = extract_cover(game_dir, catalog_list, song)
    embed_metadata(music, cover, song)
    if album_dirs:
        (output_dir / album_dirname).mkdir(parents=True, exist_ok=True)
        music_filename = output_dir / album_dirname / (song_filestem + ".ogg")
    else:
        music_filename = output_dir / (song_filestem + ".ogg")
    with music_filename.open("wb") as music_file:
        music_file.write(music.getvalue())
    if save_covers:
        if album_dirs:
            (output_dir / "covers" / album_dirname).mkdir(parents=True, exist_ok=True)
            cover_filename = output_dir / "covers" / album_dirname / (song_filestem + ".png")
        else:
            cover_filename = output_dir / "covers" / (song_filestem + ".png")
        with cover_filename.open("wb") as cover_file:
            cover.save(cover_file, format="png")
    return f"Exported song: {song.title} by {song.artist}"


def rip(
    *,
    game_dir: pathlib.Path,
    output_dir: pathlib.Path,
    language: str,
    album_dirs: bool,
    save_covers: bool,
    save_songs_csv: bool,
    progress: Callable[[float], None],
    stop_event: threading.Event,
) -> bool:
    """Rip the soundtrack from an installation of Muse Dash"""
    progress(0)

    # validate input
    if not (game_dir / "MuseDash.exe").exists():
        raise UserError(
            "Could not find MuseDash.exe in game folder. Did you select the right folder?"
        )

    logger.info("Starting rip...")
    logger.info("game_dir: %s", game_dir)
    logger.info("output_dir: %s", output_dir)
    logger.info("language: %s", language)
    logger.info("album_dirs: %s", album_dirs)
    logger.info("save_covers: %s", save_covers)
    logger.info("save_songs_csv: %s", save_songs_csv)

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Parsing game config...")
    catalog = load_catalog(game_dir)
    songs = parse_config(
        game_dir, catalog, language, progress=lambda x: progress(x * CONFIG_PARSE_PROGRESS / 100)
    )
    fix_songs(songs)
    if save_songs_csv:
        logger.info("Saving songs.csv...")
        with (output_dir / "songs.csv").open("wt", encoding="utf-8", newline="") as csv_file:
            songs_to_csv(songs, csv_file)
    normalize_songs(songs)
    if save_covers:
        (output_dir / "covers").mkdir(parents=True, exist_ok=True)
    num_albums = len(set(song.album_number for song in songs))
    logger.info("%s songs in %s albums found.", len(songs), num_albums)
    if stop_event.is_set():
        return False

    done_counter = 0

    def log_exported(message: str) -> None:
        """Callback for parallel exporting of songs"""
        nonlocal done_counter
        done_counter += 1
        progress(CONFIG_PARSE_PROGRESS + (100 - CONFIG_PARSE_PROGRESS) * done_counter / len(songs))
        logger.info(message)

    logger.info("Exporting songs...")
    with concurrent.futures.ProcessPoolExecutor() as executor:
        if not parallel_execute(
            executor=executor,
            stop_event=stop_event,
            func=export_song,
            kwargs={
                "game_dir": game_dir,
                "catalog_list": catalog,
                "output_dir": output_dir,
                "album_dirs": album_dirs,
                "save_covers": save_covers,
            },
            iterable=songs,
            done_callback=log_exported,
        ):
            return False

    logger.info("Done!")
    return True
