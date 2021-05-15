# Muse Dash Ripper

A simple GUI program to rip the Muse Dash soundtrack.

# Development

## Notes on dependencies

* [decrunch](https://github.com/HearthSim/decrunch) currently has a [bug](https://github.com/HearthSim/decrunch/issues/22) preventing it from being installed via pip
* [python-fsb5](https://github.com/hearthsim/python-fsb5) currently has a relative import bug. Fixed in [my fork](https://github.com/HearthSim/python-fsb5/pull/17).
* [python-fsb5](https://github.com/hearthsim/python-fsb5) requires `libogg` and `libvorbis` to unpack Ogg Vorbis sound files.
* [unitypack](https://github.com/HearthSim/UnityPack) uses `__file__`, which is [not compatible with PyOxidizer](https://pyoxidizer.readthedocs.io/en/latest/oxidized_importer_resource_files.html?highlight=__file__#support-for-file). Patched out in [my fork](https://github.com/lauhayden/UnityPack/commit/13cb499d282022ed76292b47fe8aec3593804d7e).
* [unitypack](https://github.com/HearthSim/UnityPack) uses `pkg_resources`, which is [buggy when used with PyOxidizier](https://github.com/indygreg/PyOxidizer/issues/378). Patched in [my fork](https://github.com/lauhayden/UnityPack/commit/8b69e72bb4a5fa571a4cba4c5d4b0ea27f45515c).

Tools used:

* Packaging: [Poetry](https://python-poetry.org/)
* Freezing: [PyOxidizer](https://pyoxidizer.readthedocs.io/en/stable/index.html)
* Formatter: [Black](https://github.com/psf/black)
* Testing: what tests? We don't have no tests.