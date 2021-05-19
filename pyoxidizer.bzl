def make_dist():
    return default_python_distribution(
        flavor="standalone_dynamic",
        build_target="x86_64-pc-windows-msvc",
        python_version="3.9",
    )

def make_exe(dist):
    policy = dist.make_python_packaging_policy()
    python_config = dist.make_python_interpreter_config()
    python_config.run_command = "from musedash_ripper.gui import run; run()"

    exe = dist.to_python_executable(
        name="musedash_ripper",
        packaging_policy=policy,
        config=python_config,
    )

    exe.tcl_files_path = "lib"
    exe.windows_subsystem = "windows"
    exe.add_python_resources(exe.pip_install([
	    "build/deps/fsb5-1.0-py3-none-any.whl",
        "build/deps/decrunch-0.4.0-cp39-cp39-win_amd64.whl",
        "dist/musedash_ripper-1.0.0-py3-none-any.whl"
	]))
    return exe

def make_embedded_resources(exe):
    return exe.to_embedded_resources()

def make_install(exe):
    # Create an object that represents our installed application file layout.
    files = FileManifest()

    # Add the generated executable to our install layout in the root directory.
    files.add_python_resource(".", exe)

    # add additional DLLs needed
    files.add_file(FileContent(path="build/deps/libogg.dll"))
    files.add_file(FileContent(path="build/deps/libvorbis.dll"))

    return files

# Tell PyOxidizer about the build targets defined above.
register_target("dist", make_dist)
register_target("exe", make_exe, depends=["dist"])
register_target("resources", make_embedded_resources, depends=["exe"], default_build_script=True)
register_target("install", make_install, depends=["exe"], default=True)

# Resolve whatever targets the invoker of this configuration file is requesting
# be resolved.
resolve_targets()

# END OF COMMON USER-ADJUSTED SETTINGS.
#
# Everything below this is typically managed by PyOxidizer and doesn't need
# to be updated by people.

PYOXIDIZER_VERSION = "0.16.0"
PYOXIDIZER_COMMIT = "4053178f2ba11d29f497d171289cb847cd07ed77"
