#!/usr/bin/python3

import os
import json
import time
import yaml
from generateBindings import generateCustomCodeBindings
from compileBindings import compileCustomCodeBindings
from cerberus import Validator
from argparse import ArgumentParser
from Common import ocIncludePaths, additionalIncludePaths
from plumbum import local
from Common import buildOptions, console

parser = ArgumentParser()
parser.add_argument(dest="filename", help="Custom build input file (.yml)", metavar="FILE.yml")
args = parser.parse_args()

LIBRARY_BASE_PATH = "/opencascade.js/build"

mkdirp = local["mkdir"]["-p"]
rmrf = local["rm"]["-rf"]

buildConfig = yaml.safe_load(open(args.filename, "r"))
schema = eval(open("/opencascade.js/src/customBuildSchema.py", "r").read())

v = Validator(schema)
if not v.validate(buildConfig, schema):
  raise Exception(v.errors)
buildConfig = v.normalized(buildConfig)

# rmrf(f"{LIBRARY_BASE_PATH}/bindings/myMain.h")

# generateCustomCodeBindings(buildConfig["additionalCppCode"])
# compileCustomCodeBindings({
#   "threading": os.environ['threading'],
# })

def verifyBinding(binding) -> bool:
  for dirpath, dirnames, filenames in os.walk(f"{LIBRARY_BASE_PATH}/bindings"):
    for item in filenames:
      if item.endswith(".cpp.o") and binding["symbol"] == item[:-6]:
        return True
  return False

def verifyBindings(bindings) -> bool:
  fails = []
  for binding in bindings:
    if not verifyBinding(binding):
      fails.append(binding)
  if fails:
    raise Exception(f"Requested binding {json.dumps(fails)} does not exist!")

# verifyBindings(buildConfig["mainBuild"]["bindings"])
# for extraBuild in buildConfig["extraBuilds"]:
#   verifyBindings(extraBuild)

def shouldProcessSymbol(symbol: str, bindings) -> bool:
  if len(bindings) == 0:
    return True
  entry = next((b for b in bindings if b["symbol"] == symbol), None)
  if not entry is None:
    return True
  return False

def runBuild(build):
  def getAdditionalBindCodeO():
    if "additionalBindCode" in build:
      try:
        mkdirp(f"{LIBRARY_BASE_PATH}/additionalBindCode")
      except Exception:
        pass
      additionalBindCodeFileName = f"{LIBRARY_BASE_PATH}/additionalBindCode/{build['name']}.cpp"
      with open(additionalBindCodeFileName, "w") as f:
        f.write(build["additionalBindCode"])
      console.print(f"building {additionalBindCodeFileName}")
      emcc = local["ccache"]["emcc"][
        *buildOptions,
        "-pthread" if os.environ["threading"] == "multi-threaded" else "",
        *list(map(lambda x: "-I" + x, ocIncludePaths + additionalIncludePaths)),
        "-c", additionalBindCodeFileName,
        "-o", f"{additionalBindCodeFileName}.o",
      ]

      emcc()
      
      return f"{additionalBindCodeFileName}.o"
    else:
      return None
  additionalBindCodeO = getAdditionalBindCodeO()
  console.print(f"Running build: {build['name']}")
  bindingsO = []
  for dirpath, dirnames, filenames in os.walk(f"{LIBRARY_BASE_PATH}/bindings"):
    for item in filenames:
      arr = [
        'TCollection_ExtendedString'
        # 'TCollection',
        # 'TopoDS_',
        # 'BRep',
        # 'Message_ProgressRange',
        # "Handle_",
        # 'BRepFilletAPI_MakeChamfer',
        
        # 'ChFiDS_ChamfMode',
      ]

      if False and any(map(lambda x: item.startswith(x) and item.endswith('.cpp.o'), arr)):
        bindingsO.append(f"{dirpath}/{item}")
      elif item.endswith(f".cpp.o") and shouldProcessSymbol(item[:-6], build["bindings"]):
        bindingsO.append(f"{dirpath}/{item}")
  sourcesO = []
  for dirpath, dirnames, filenames in os.walk(f"{LIBRARY_BASE_PATH}/sources"):
    for item in filenames:
      if item.endswith(".o"):
        sourcesO.append(dirpath + "/" + item)
  print(f"Bindings: {len(bindingsO)}, Sources: {len(sourcesO)}")
  emcc = local['ccache']["emcc"][
    "-lembind",
    ("" if additionalBindCodeO is None else additionalBindCodeO),
    *bindingsO,
    *sourcesO,
    # TODO 타입스크립트 사용 시 오류 발생
    # "--emit-tsd", "interface.d.ts",
    "-o", f"{os.getcwd()}/{build['name']}",
    "-pthread" if os.environ["threading"] == "multi-threaded" else None,
    '-Os',
    '-sEXPORT_ES6=1',
    '-sMODULARIZE=1',
    "-sEXPORTED_RUNTIME_METHODS=['FS']",
    "-sINITIAL_MEMORY=100MB",
    "-sMAXIMUM_MEMORY=4GB",
    "-sALLOW_MEMORY_GROWTH=1",
    "-sUSE_FREETYPE=1",
    # *build["emccFlags"],
  ]
  emcc()
  console.print("Build finished")

runBuild(buildConfig["mainBuild"])
for extraBuild in buildConfig["extraBuilds"]:
  runBuild(extraBuild)
