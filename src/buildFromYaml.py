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
from Common import buildOptions, console, DEBUG_OPTIONS

parser = ArgumentParser()
parser.add_argument(dest="filename", help="Custom build input file (.yml)", metavar="FILE.yml")
args = parser.parse_args()

LIBRARY_BASE_PATH = "/opencascade.js/build"
SRC_PATH = os.path.dirname(os.path.abspath(__file__))
STUBS_PATH = os.path.join(SRC_PATH, "stubs")

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
  if entry is not None:
    return True
  return False

def compileStubFiles():
  stub_objects = []
  
  # 스텁 디렉토리에 있는 모든 .cpp 파일 컴파일
  if os.path.exists(STUBS_PATH):
    for filename in os.listdir(STUBS_PATH):
      if filename.endswith(".cpp"):
        stub_file = os.path.join(STUBS_PATH, filename)
        stub_obj = f"{stub_file}.o"
        
        console.print(f"컴파일 스텁 파일: {stub_file}")
        
        emcc = local["ccache"]["emcc"][
          *buildOptions,
          *(["-pthread", "-DHAVE_TBB"] if os.environ.get("threading", "") == "multi-threaded" else []),
          *list(map(lambda x: "-I" + x, ocIncludePaths + additionalIncludePaths)),
          "-c", stub_file,
          "-o", stub_obj,
        ]
        
        try:
          emcc()
          stub_objects.append(stub_obj)
        except Exception as e:
          console.print(f"스텁 파일 컴파일 실패: {stub_file}, 오류: {str(e)}")
  
  return stub_objects

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
        *(["-pthread", "-DHAVE_TBB"] if os.environ["threading"] == "multi-threaded" else []),
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
      if shouldProcessSymbol(item[:-6], build["bindings"]) and item.endswith(".cpp.o"):
        bindingsO.append(f"{dirpath}/{item}")
  
  sourcesO = []
  for dirpath, dirnames, filenames in os.walk(f"{LIBRARY_BASE_PATH}/sources"):
    for item in filenames:
      if item.endswith(".o"):
        sourcesO.append(dirpath + "/" + item)

  stub_objects = compileStubFiles()

  print(f"Bindings: {len(bindingsO)}, Sources: {len(sourcesO)}, Stub files: {len(stub_objects)}")

  threading = os.environ.get("threading", "single-threaded")

  emcc = local['ccache']["emcc"][
    "-lembind",
    # "-L/usr/lib/x86_64-linux-gnu",
    # "-ldraco",
    ("" if additionalBindCodeO is None else additionalBindCodeO),
    *bindingsO,
    *sourcesO,
    *stub_objects,  # Updated from *stub_files to *stub_objects
    # TODO 타입스크립트 사용 시 오류 발생
    # "--emit-tsd", "interface.d.ts",
    "-o", f"{os.getcwd()}/{build['name']}",
    "-pthread" if threading == "multi-threaded" else None,
    '-O0',
    '-sEXPORT_ES6=1',
    '-sMODULARIZE=1',
    "-sEXPORTED_RUNTIME_METHODS=['FS']",
    "-sINITIAL_MEMORY=100MB",
    "-sMAXIMUM_MEMORY=4GB",
    "-sALLOW_MEMORY_GROWTH=1",
    "-sUSE_FREETYPE=1",
    *DEBUG_OPTIONS,
    # *build["emccFlags"],
  ]
  emcc()
  console.print("Build finished")

runBuild(buildConfig["mainBuild"])
for extraBuild in buildConfig["extraBuilds"]:
  runBuild(extraBuild)
