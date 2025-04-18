import tempfile
from filter.filterIncludeFiles import filterIncludeFile
from typing import Set
from rich.console import Console
console = Console()
import os

occtBasePath = "/occt/src/"


def getGlobalIncludes() -> list[list[str]]:
    includeFiles = list()
    additionalIncludePaths = list()
    for dirpath, dirnames, filenames in os.walk(occtBasePath):
        additionalIncludePaths.append(str(dirpath))
        for item in filenames:
            if filterIncludeFile(item):
                includeFiles.append(str(os.path.join(dirpath, item)))
    return [includeFiles, additionalIncludePaths]


TMP_DIR = tempfile.gettempdir()
HEADER_NAME = "myMain"
HEADER_PATH = os.path.join(TMP_DIR, f"{HEADER_NAME}.h")

[ocIncludeFiles, ocIncludePaths] = getGlobalIncludes()

additionalIncludePaths = [
    "/rapidjson/include",
    "/freetype/include/freetype",
    "/freetype/include",
]

includePathArgs = (
    list(dict.fromkeys(map(lambda x: "-I" + x, ocIncludePaths)))
    + list(
        map(
            lambda x: "-I" + x,
            [
                "/emsdk/upstream/emscripten/system/include/",
                "/emsdk/upstream/emscripten/system/lib/libcxx/include/__support/newlib/",
            ],
        )
    )
    + list(map(lambda x: "-I" + x, ocIncludePaths + additionalIncludePaths))
    + [f"-I {TMP_DIR}"]
)

buildOptions = [
    # "-flto",
    "-fexceptions",
    "-sDISABLE_EXCEPTION_CATCHING=0",
    "-DOCCT_NO_PLUGINS",
    "-frtti",
    "-DHAVE_RAPIDJSON",
    "-DHAVE_TBB",
    "-DHAVE_DRACO",
    "-sMALLOC=emmalloc",
    "-Wno-deprecated-declarations",
    "-Wno-delete-abstract-non-virtual-dtor",
    # "-std=c++20",
    "-Os",
]

