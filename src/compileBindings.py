#!/usr/bin/python3

import os

from joblib import delayed
from Common import TMP_DIR, ocIncludePaths, additionalIncludePaths
from plumbum import local

from argparse import ArgumentParser
from Common import buildOptions

from Common import console

import sys

from parallelProgress import ParallelProgress

sys.path.append('/emsdk/upstream/emscripten')


LIBRARY_BASE_PATH = "/opencascade.js/build/bindings"

def tryExcept(func):
    def result(*args):
        try:
            return func(*args)
        except:
            return None
        
    return result

def buildOneFile(args, item):
    return local['ccache']['emcc']([
        *buildOptions,
        args["threading"] == "multi-threaded" and "-pthread" or "",
        *(f"-I{x}" for x in (ocIncludePaths + additionalIncludePaths + [TMP_DIR])),
        "-c",
        item,
        "-o",
        f"{item}.o",
    ])

def compileCustomCodeBindings(args, file="myMain.h"):
    filesToBuild = []
    for dirpath, _, filenames in os.walk(f"{LIBRARY_BASE_PATH}/{file}"):
        filesToBuild.extend(
            map(
                lambda x: f"{dirpath}/{x}",
                filter(
                    lambda x: x.endswith(".cpp")
                    # and x.endswith('AIS_DataMapOfShapeDrawer.cpp')
                    and not os.path.exists(f"{dirpath}/{x}.o"),
                    filenames,
                ),
            )
        )

    console.print(f"Building {len(filesToBuild)} files")

    func = delayed(buildOneFile)
    parallel = ParallelProgress(n_jobs=-1, backend="threading")
    futures = []

    target = sorted(filesToBuild)

    for item in target:
        if not os.path.exists(f"{item}.o"):
            futures.append(func(args, item))
        else:
            console.print(f"file {item}.o already exists, skipping")

    parallel(futures)



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
