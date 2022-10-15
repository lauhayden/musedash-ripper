# Muse Dash Ripper

A simple GUI program to rip the Muse Dash soundtrack. Only supports Windows.

![Screenshot](/screenshot.png)

## Features

* extracts all sound files without re-encoding
* extracts cover images
* adds cover images and song metadata to the resulting `.ogg` files
* optionally exports cover images as `.png`
* optionally exports song metadata as `.csv`
* optionally puts each exported song and cover into a filter with the album name
* supports all languages that Muse Dash supports, with corresponding changes in song names, artist names, album names, etc.
	* Chinese Traditional
	* Chinese Simplified
	* English
	* Japanese
	* Korean
	* None (default): use the default names for everything

# Development

## Notes on dependencies

* [UnityPy](https://github.com/K0lb3/UnityPy) is used instead of [UnityPack](https://github.com/HearthSim/UnityPack) because the new versions of Muse Dash since around November/December 2021 use a newer version of Unity than `UnityPack` supports.
* We use [python-fsb5](https://github.com/hearthsim/python-fsb5) instead of `UnityPy`'s built-in `AudioClip` extraction method in order to get the original Ogg Vorbis-encoded sound files.
* [python-fsb5](https://github.com/hearthsim/python-fsb5) currently has a relative import bug. Fixed in [my fork](https://github.com/HearthSim/python-fsb5/pull/17).
* [python-fsb5](https://github.com/hearthsim/python-fsb5) requires `libogg` and `libvorbis` to unpack Ogg Vorbis sound files.

## Tools used:

* Packaging: [Poetry](https://python-poetry.org/)
* Freezing: [PyInstaller](https://pyinstaller.org/en/stable/)
* Formatter: [Black](https://github.com/psf/black)
	* Run using `poetry run black src`
* Linter: [Pylint](https://pylint.pycqa.org/en/latest/)
	* Run using `poetry run pylint src`
* Type checking: [mypy](https://mypy.readthedocs.io/en/stable/index.html)
    * Run using `poetry run mypy src`
* Testing: what tests? We don't have no tests.

## Building

1. Build `libogg.dll` and `libvorbis.dll` and place them in the root of the repository. See [this blog post](https://deltaepsilon.ca/posts/compiling-libogg-libvorbis-for-dummies/) for detailed instructions.
2. Download and install Poetry
3. Run `poetry install` to install dependencies and package
4. Run `poetry run pyinstaller -y musedash-ripper.spec` to freeze the application into a `.exe` under `dist/musedash-ripper.exe`
