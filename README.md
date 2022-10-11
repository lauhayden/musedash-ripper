# Muse Dash Ripper

A simple GUI program to rip the Muse Dash soundtrack. Only supports Windows.

![Screenshot](/screenshot.png)

## Features

* extracts all sound files without re-encoding
* extracts cover images
* adds cover images and track metadata to the resulting `.ogg` files
* optionally exports cover images as `.png`
* optionally exports track metadata as `.csv`
* supports song and album names in all languages that Muse Dash supports:
	* Chinese Traditional
	* Chinese Simplified
	* English
	* Japanese
	* Korean
	* "other" (default) - mostly english but don't translate explicitly

# Development

## Notes on dependencies

* [python-fsb5](https://github.com/hearthsim/python-fsb5) currently has a relative import bug. Fixed in [my fork](https://github.com/HearthSim/python-fsb5/pull/17).
* [python-fsb5](https://github.com/hearthsim/python-fsb5) requires `libogg` and `libvorbis` to unpack Ogg Vorbis sound files.

## Tools used:

* Packaging: [Poetry](https://python-poetry.org/)
* Freezing: [PyInstaller](https://pyinstaller.org/en/stable/)
* Formatter: [Black](https://github.com/psf/black)
* Testing: what tests? We don't have no tests.

## Building

1. Build `libogg.dll` and `libvorbis.dll` and place them in the root of the repository. See [this blog post](https://deltaepsilon.ca/posts/compiling-libogg-libvorbis-for-dummies/) for detailed instructions.
2. Download and install Poetry
3. Run `poetry install` to install dependencies and package
4. Run `poetry run pyinstaller -y musedash-ripper.spec` to freeze the application into a `.exe` under `dist/musedash-ripper.exe`
