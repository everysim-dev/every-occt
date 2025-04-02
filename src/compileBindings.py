#!/usr/bin/python3

from concurrent.futures import ProcessPoolExecutor, as_completed
import os
from Common import ocIncludePaths, additionalIncludePaths
from plumbum import local

from argparse import ArgumentParser
from Common import buildOptions

from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn, MofNCompleteColumn
from rich.console import Console

LIBRARY_BASE_PATH = "/opencascade.js/build/bindings"

console = Console()

def buildOneFile(args, item, debug=False):
    if not os.path.exists(f"{item}.o"):
        try:
            emcc = local["ccache"]["emcc"][
                *buildOptions,
                args["threading"] == "multi-threaded" and "-pthread" or "",
                *(f"-I{x}" for x in (ocIncludePaths + additionalIncludePaths)),
                "-c", item,
                "-o", f"{item}.o",
            ]

            console.print(f"building {item}")
            result = emcc()
            return (item, result)
        except Exception as e:
            console.print_exception(max_frames=0)
            console.print(f"failed to build {item}")
            return (item, None)
    else:
        console.print(f"file {item}.o already exists, skipping")
        return (item, None)


def compileCustomCodeBindings(args, file="myMain.h"):
    filesToBuild = []
    for dirpath, _, filenames in os.walk(f"{LIBRARY_BASE_PATH}/{file}"):
        filesToBuild.extend(
            map(
                lambda x: f"{dirpath}/{x}",
                filter(
                    lambda x: x.endswith(".cpp")
                    and not os.path.exists(f"{dirpath}/{x}.o"),
                    filenames,
                ),
            )
        )

    console.print(f"Building {len(filesToBuild)} files")

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Compiling", total=len(filesToBuild))
        with ProcessPoolExecutor() as executor:
            futures = [executor.submit(buildOneFile, args, item) for item in sorted(filesToBuild)]
            for future in as_completed(futures):
                item, result = future.result()
                if result is not None:
                    progress.update(task_id, description=f"Building {item}", advance=1)
                else:
                    progress.update(task_id, description=f"Skipped or Failed {item}", advance=1)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        dest="threading",
        choices=["single-threaded", "multi-threaded"],
        help="Build in single vs. multi-threaded mode",
        nargs="*",
        default="single-threaded",
    )
    args = parser.parse_args()

    compileArgs = {"threading": args.threading}

    compileCustomCodeBindings(compileArgs, "")
