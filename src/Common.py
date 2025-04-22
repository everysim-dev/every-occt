import tempfile
from filter.filterIncludeFiles import filterIncludeFile
from typing import Set
from rich.console import Console
console = Console()
import os

occtBasePath = "/occt/src/"

def tryExcept(func):
    def result(*args):
        try:
            return func(*args)
        except:
            return None
        
    return result

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
    "/opt/include",
]

includePathArgs = (
    list(dict.fromkeys(map(lambda x: "-I" + x, ocIncludePaths)))
    # + list(
    #     map(
    #         lambda x: "-I" + x,
    #         [
    #             "/emsdk/upstream/emscripten/cache/sysroot/include/c++/v1",
    #             "/emsdk/upstream/emscripten/cache/sysroot/include/compat",
    #             "/emsdk/upstream/emscripten/cache/sysroot/include",
    #             # "/emsdk/upstream/emscripten/system/lib/libcxx/include/__support/newlib/",
    #             # "/emsdk/upstream/emscripten/cache/sysroot/include/c++/v1/__type_traits/",
    #         ],
    #     )
    # )
    + list(map(lambda x: "-I" + x, ocIncludePaths + additionalIncludePaths))
    + [f"-I{TMP_DIR}"]
)

IS_DEBUG = True

DEBUG_OPTIONS = [
    # 디버깅
    "-gsource-map",
    "-fsanitize=address",
    "-Os" if IS_DEBUG else "O0",
] if IS_DEBUG else []

buildOptions = [
    "-flto",
    "-fexceptions",
    "-sDISABLE_EXCEPTION_CATCHING=0",
    "-DOCCT_NO_PLUGINS",
    "-frtti",
    "-DHAVE_RAPIDJSON",
    # "-DHAVE_DRACO",
    # "-sMALLOC=emmalloc",
    "-Wno-deprecated-declarations",
    "-Wno-delete-abstract-non-virtual-dtor",
    "-Wno-unused-command-line-argument",
    # "-std=c++14",
    *DEBUG_OPTIONS,
]


