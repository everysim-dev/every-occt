import json
import tempfile
from filter.filterIncludeFiles import filterIncludeFile
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
    + list(map(lambda x: "-I" + x, ocIncludePaths + additionalIncludePaths))
    + [f"-I{TMP_DIR}"]
)

IS_DEBUG = True

DEBUG_OPTIONS = [
    # 디버깅
    "-g",
    "-g3",
    "-gsource-map",
    "-fsanitize=address",
    "-O0",
] if IS_DEBUG else ["-Os"]

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



HEADERS = {
    "BRepFill_TrimShellCorner": ["TopoDS_Vertex"],
    "AIS_EqualDistanceRelation": ["TopoDS_Vertex", "TopoDS_Edge"],
    "BOPAlgo_EdgeInfo": ["BOPAlgo_WireSplitter", "TopTools_ListOfShape"],
    "IVtkDraw": ["Graphic3d_Vec2"],
    "IntPolyh_VectorOfType": ["IntPolyh_Edge"],
    "NCollection_IndexedDataMap": ["Graphic3d_CLight"],
    "NCollection_DoubleMap": ["XCAFPrs_Style"],
    "BRepBlend_ConstThroatWithPenetrationInv": ["math_Matrix"],
    "BRepBlend_Chamfer": ["math_Matrix"],
    "BRepBlend_ConstThroatInv": ["math_Matrix"],
    "BRepBlend_ConstThroatWithPenetration": ["math_Matrix"],
    "BRepBlend_ConstRad": ["Blend_Point"],
    "NCollection_CellFilter": ["BRepMesh_CircleInspector"],
    "BRepBlend_CSCircular": ["Blend_Point"],
    "TCollection_AsciiString": ["TCollection_ExtendedString"],
    "BRepAlgoAPI_BooleanOperation": ["BOPAlgo_PaveFiller"],
    "BRepAlgoAPI_BuilderAlgo": ["BOPAlgo_PaveFiller"],
    "BRepApprox_TheImpPrmSvSurfacesOfApprox": ["IntSurf_Quadric"],
    "AdvApp2Var_ApproxAFunc2Var": ["AdvApp2Var_Criterion", "AdvApprox_Cutting"],
    "BRepApprox_ResConstraintOfMyGradientbisOfTheComputeLineOfApprox": [
        "AppParCurves_MultiCurve"
    ],
    "BRepExtrema_TriangleSet": ["AppParCurves_MultiCurve"],
    "BRepMesh_GeomTool": ["BRepAdaptor_Curve"],
    "BRepBuilderAPI_MakeSolid": ["TopoDS_CompSolid"],
    "BRepBlend_AppFuncRst": ["Blend_SurfRstFunction"],
    "BRepBlend_CSConstRad": ["Blend_Point"],
    "AIS_Axis": ["Geom_Line", "Geom_Axis1Placement"],
    "AIS_Plane": ["Geom_Line", "Geom_Axis2Placement", "Geom_Plane"],
    "BRepBlend_AppFuncRstRst": ["Blend_RstRstFunction"],
    "BRepCheck_Wire": ["TopoDS_Wire"],
    "BRepFill_ShapeLaw": ["TopoDS_Wire"],
    "BRepPrimAPI_MakeHalfSpace": ["TopoDS_Shell"],
}

REQUIRED_HEADERS = [
    "TopoDS_Shape",
    "Adaptor2d_Curve2d",
    "AppDef_MultiLine",  # AppDef
    "BOPDS_PaveBlock",
    "Standard_TypeDef",
    "BRepGProp_Face",
    "BRepGProp_Domain",
    "gp",
    "Message_ProgressRange",
    "math_Matrix",  # BRep
    "BOPAlgo_PaveFiller",  # BRepAlgoAPI
    "BRepApprox_TheMultiLineOfApprox",  # BRepApprox
    "BRepAdaptor_Curve2d",
    "V3d_View",
]

LIBRARY_BASE_PATH = "/opencascade.js/build"

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