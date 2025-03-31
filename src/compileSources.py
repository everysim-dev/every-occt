#!/usr/bin/python3

import os
import multiprocessing

from filter.filterSourceFiles import filterSourceFile
from filter.filterPackages import filterPackages
from plumbum import local

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

includePaths = []
includePaths.extend([
  "/rapidjson/include",
  "/freetype/include/freetype",
  "/freetype/include",
])
for dirpath, dirnames, filenames in os.walk(os.path.join(SOURCE_BASE_PATH)):
  includePaths.append(dirpath)

mkdirp = local["mkdir"]["-p"]

def buildObjectFiles(file, args):
  relativeFile = file.replace(SOURCE_BASE_PATH, "")
  mkdirp(f"{LIBRARY_BASE_PATH}/{os.path.dirname(relativeFile)}")

  emcc = local['ccache']["emcc"][
    "-flto",
    "-fexceptions",
    "-sDISABLE_EXCEPTION_CATCHING=0",
    "-DIGNORE_NO_ATOMICS=1",
    "-DOCCT_NO_PLUGINS",
    "-frtti",
    "-DHAVE_RAPIDJSON", 
    "-Os",
    "-Wno-deprecated-declarations",
    # "-g3",
    # "-gsource-map",
    # "--source-map-base=http://localhost:8080",
    # "-fPIC",
    "-pthread" if args["threading"] == "multi-threaded" else "",
    *list(map(lambda x: "-I" + x, includePaths)),
    "-c", file,
    "-o", f"{LIBRARY_BASE_PATH}/{relativeFile}.o"
  ]

  if not os.path.exists(f"{LIBRARY_BASE_PATH}/{relativeFile}.o"):
    print(f"Building {relativeFile}")
    return emcc()
  else:
    print(f"{relativeFile}.o already exists, skipping")
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
    if filterSourceFile(f"{dirpath}/{item}"):
      filesToBuild.append(f"{dirpath}/{item}")

if __name__ == "__main__":
  parser = ArgumentParser()
  parser.add_argument(dest="threading", choices=["single-threaded", "multi-threaded"], help="Build in single vs. multi-threaded mode", nargs="*", default="single-threaded")
  args = parser.parse_args()

  mkdirp(LIBRARY_BASE_PATH)

  def myBuildFunction(x):
    buildObjectFiles(x, {
      "threading": args.threading,
    })

  with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as p:
    p.map(myBuildFunction, filesToBuild)
