#!/usr/bin/python3

import os

from filter.filterSourceFiles import filterSourceFile
from filter.filterPackages import filterPackages
from plumbum import local
from Common import buildOptions, console, tryExcept
from joblib import delayed
from parallelProgress import ParallelProgress
from Common import includePathArgs

from argparse import ArgumentParser

LIBRARY_BASE_PATH = "/opencascade.js/build/sources"

# Potentially problematic packages, when used with dynamic linking
# These files contain function pointer definitions and header files and are therefore likely to cause problems.
# https://github.com/emscripten-core/emscripten/issues/13241
# "AdvApp2Var"
# "BRepGProp"
# "BRepMesh"
# "BSplSLib"
# "CPnts"
# "DDF"
# "Draw"
# "Graphic3d"
# "IFSelect"
# "Interface"
# "MoniTool"
# "NCollection"
# "OpenGl"
# "OSD"
# "ShapeProcess"
# "Standard"
# "StdObjMgt"
# "TDF

SOURCE_BASE_PATH = "/occt/src/"

mkdirp = local["mkdir"]["-p"]

# @tryExcept
def buildObjectFiles(file, args):
  relativeFile = file.replace(SOURCE_BASE_PATH, "")
  mkdirp(f"{LIBRARY_BASE_PATH}/{os.path.dirname(relativeFile)}")

  emcc = local['ccache']["emcc"][
    *buildOptions,
    *(["-pthread", "-DHAVE_TBB"] if args["threading"] == "multi-threaded" else []),
    "-I/emsdk/upstream/emscripten/cache/sysroot/include/c++/v1",
    "-I/emsdk/upstream/emscripten/cache/sysroot/include/compat",
    "-I/emsdk/upstream/emscripten/cache/sysroot/include",
    *includePathArgs,
    "-c", file,
    "-o", f"{LIBRARY_BASE_PATH}/{relativeFile}.o"
  ]

  if not os.path.exists(f"{LIBRARY_BASE_PATH}/{relativeFile}.o"):
    console.print(f"Building {relativeFile}")
    return emcc()
  else:
    return None

allModules = {}
for dirpath, dirnames, filenames in os.walk(SOURCE_BASE_PATH):
  if not any(x for x in filenames if x == "PACKAGES"):
    continue
  allModules[os.path.basename(dirpath)] = []
  with open(f"{dirpath}/PACKAGES", "r") as a_file:
    for package in a_file:
      packageName = package.strip()
      allModules[os.path.basename(dirpath)].append(packageName)
def getModuleNameByPackageName(inputPackageName):
  for moduleName in allModules:
    for package in allModules[moduleName]:
      packageName = package.strip()
      if packageName == inputPackageName:
        return moduleName
  return ""

filesToBuild = []
for dirpath, dirnames, filenames in os.walk(SOURCE_BASE_PATH):
  packageOrModuleName = os.path.basename(dirpath.replace(SOURCE_BASE_PATH, ""))
  for item in filenames:
    if not filterPackages(packageOrModuleName) or not filterPackages(getModuleNameByPackageName(packageOrModuleName)):
      continue
    if 'IGESDraw_NetworkSubfigureDef' in item:
      print('IGESDraw_NetworkSubfigureDef')
    if filterSourceFile(f"{dirpath}/{item}"):
      filesToBuild.append(f"{dirpath}/{item}")

if __name__ == "__main__":
  parser = ArgumentParser()
  parser.add_argument(dest="threading", choices=["single-threaded", "multi-threaded"], help="Build in single vs. multi-threaded mode", nargs="*", default="single-threaded")
  args = parser.parse_args()

  mkdirp(LIBRARY_BASE_PATH)

  def myBuildFunction(x):
    return buildObjectFiles(x, {
      "threading": args.threading,
    })

  func = delayed(myBuildFunction)
  parallel = ParallelProgress(n_jobs=-1, backend="threading", total_tasks=len(filesToBuild), desc="Compiling sources")
  futures = [func(x) for x in filesToBuild]
  parallel(futures)
