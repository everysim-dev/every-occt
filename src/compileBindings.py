#!/usr/bin/python3

import os
from Common import ocIncludePaths, additionalIncludePaths
from plumbum import local

from argparse import ArgumentParser
from Common import buildOptions

from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    MofNCompleteColumn,
)
from Common import console
from joblib import delayed, Parallel

LIBRARY_BASE_PATH = "/opencascade.js/build/bindings"

def buildOneFile(args, item):
    emcc = local["ccache"]["emcc"][
        *buildOptions,
        args["threading"] == "multi-threaded" and "-pthread" or "",
        *(f"-I{x}" for x in (ocIncludePaths + additionalIncludePaths)),
        "-c",
        item,
        "-o",
        f"{item}.o",
    ]

    return emcc()


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
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Compiling", total=len(filesToBuild))

        func = delayed(buildOneFile)
        parallel = Parallel(n_jobs=-1, backend="threading")
        futures = []

        target = sorted(filesToBuild)

        for item in target:
            if not os.path.exists(f"{item}.o"):
                futures.append(func(args, item))
            else:
                console.print(f"file {item}.o already exists, skipping")

        results = parallel(futures)

        for item, result in zip(target, results):
            if result is not None:
                progress.update(task_id, description=f"Building {item}", advance=1)
            else:
                progress.update(
                    task_id, description=f"Skipped or Failed {item}", advance=1
                )


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
