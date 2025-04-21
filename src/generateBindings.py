#!/usr/bin/python3

from typing import Callable, Union
from bindings import EmbindBindings
import os
from wasmGenerator.Common import SkipException
from Common import ocIncludeFiles, includePathArgs, console, HEADER_NAME, HEADER_PATH
from plumbum import local
from pygccxml import parser, declarations, utils
import os
from joblib import Parallel, delayed
from typeguard import typechecked

LIBRARY_BASE_PATH = os.environ.get(
    "OCJS_BINDINGS_PATH", "/opencascade.js/build/bindings"
)
BUILD_DIRECTORY = os.environ.get("OCJS_BUILD_PATH", "/opencascade.js/build")
OCCT_SRC_PATH = os.environ.get("OCCT_SRC_PATH", "/occt/src/")
OCCT_INCLUDE_STATEMENTS = os.linesep.join(
    map(lambda x: f"#include <{os.path.basename(x)}>", list(sorted(ocIncludeFiles)))
)

mkdirp = local["mkdir"]["-p"]
rmrf = local["rm"]["-rf"]


referenceTypeTemplateDefs = """
#include <emscripten/bind.h>
#include <functional>
#include <type_traits>
#include <array>
#include <stdexcept>

using namespace emscripten;

// C++17 if constexpr 기반 통합 getReferenceValue/updateReferenceValue
template<typename T>
auto getReferenceValue(const val& v) {
  if constexpr (std::is_array_v<T>) {
    using U = std::remove_extent_t<T>;
    constexpr size_t N = std::extent_v<T>;
    std::array<U, N> arr;
    for (size_t i = 0; i < N; ++i) {
      arr[i] = v[i].template as<U>(allow_raw_pointers());
    }
    return arr;
  }
  else if constexpr (std::is_pointer_v<T> && std::is_function_v<std::remove_pointer_t<T>>) {
    if (v.typeOf().as<std::string>() == "function") {
      using FnType = std::remove_pointer_t<T>;
      auto cb = v;  
      return reinterpret_cast<T>(+[cb](auto&&... args) -> decltype(auto) {
        return cb(std::forward<decltype(args)>(args)...)
            .template as<decltype(cb(std::forward<decltype(args)>(args)...))>();
      });
    }
    throw std::runtime_error("Unsupported function pointer type");
  }
  else {
    if (v.typeOf().as<std::string>() != "object")
      return v.as<T>(allow_raw_pointers());
    if (v.hasOwnProperty("current"))
      return v["current"].as<T>(allow_raw_pointers());
    throw std::runtime_error("Unsupported type");
  }
}

template<typename T>
void updateReferenceValue(val& v, const T& ref) {
  if constexpr (std::is_array_v<T>) {
    constexpr size_t N = std::extent_v<T>;
    val arr = v["current"];
    for (size_t i = 0; i < N; ++i) {
      arr.set(i, ref[i]);
    }
  }
  else if constexpr (!(std::is_pointer_v<T> && std::is_function_v<std::remove_pointer_t<T>>)) {
    if (v.hasOwnProperty("current")) {
      v.set("current", ref);
    }
  }
  // 함수 포인터인 경우 no-op
}
"""

cache = {}


@typechecked
def getClass(decl: declarations.declaration_t) -> declarations.class_t | None:
    while isinstance(decl, declarations.typedef_t):
        decl = decl.decl_type
        if hasattr(decl, "declaration"):
            decl = decl.declaration

    if isinstance(decl, declarations.class_t):
        return decl

    return None


@typechecked
def filterCommon(decl: declarations.declaration_t) -> bool:
    if not decl.location:
        return False

    fileName = decl.location.file_name

    if fileName.endswith(HEADER_PATH):
        return True

    if not fileName or not fileName.startswith(OCCT_SRC_PATH):
        return False

    if isinstance(decl.parent, declarations.class_t):
        return any(map(lambda x: x is decl, decl.parent.public_members))

    return True


@typechecked
def filterClasses(decl: declarations.declaration_t) -> bool:
    if not isinstance(decl, declarations.class_t):
        return False

    if isinstance(decl.parent, declarations.class_t) or isinstance(
        decl.parent, declarations.class_declaration_t
    ):
        return False

    if decl.name.startswith("basic_fstream"):
        return False

    return True


@typechecked
def filterTemplates(decl: declarations.declaration_t) -> bool:
    theClass = getClass(decl)

    if theClass is None:
        return False

    return filterClasses(theClass)


@typechecked
def filterEnums(decl: declarations.declaration_t) -> bool:
    return isinstance(decl, declarations.enumeration_t)


@typechecked
def processHeaders(decl: declarations.declaration_t):
    [originalName, childName] = getTypeName(decl)

    includeFiles = set()

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
        "BRepApprox_ParLeastSquareOfMyGradientOfTheComputeLineBezierOfApprox": [
            "BRepApprox_TheMultiLineOfApprox"
        ],
        "AdvApp2Var_ApproxAFunc2Var": ["AdvApp2Var_Criterion"],
        "BRepApprox_ResConstraintOfMyGradientbisOfTheComputeLineOfApprox": [
            "AppParCurves_MultiCurve"
        ],
        "BRepExtrema_TriangleSet": ["AppParCurves_MultiCurve"],
        "AppDef_MyBSplGradientOfBSplineCompute": ["AppDef_MultiLine"],
        "BRepApprox_MyBSplGradientOfTheComputeLineOfApprox": [
            "BRepApprox_TheMultiLineOfApprox"
        ],
        "BRepMesh_GeomTool": ["BRepAdaptor_Curve"],
        "BRepBuilderAPI_MakeSolid": ["TopoDS_CompSolid"],
        "BRepBlend_AppFuncRst": ["Blend_SurfRstFunction"],
    }

    REQUIRED_HEADERS = [
        "TopoDS_Shape",
        "Adaptor2d_Curve2d",
        "BOPDS_PaveBlock",
        "Standard_TypeDef",
        "BRepGProp_Face",
        "BRepGProp_Domain",
        "gp",
        "Message_ProgressRange",
        "math_Matrix",  # BRep
        "BOPAlgo_PaveFiller",  # BRepAlgoAPI
    ]
    defaultHeaders = HEADERS[childName] if childName in HEADERS else []

    headers = [
        f"{header}.hxx"
        for header in [
            *REQUIRED_HEADERS,
            *defaultHeaders,
        ]
    ]

    includeFiles.update(headers)

    aliases = getattr(decl, "aliases", [])

    targets = [decl, *filter(lambda a: a.name not in ("base_type"), aliases)]

    if isinstance(decl, declarations.class_t):
        for method in decl.member_functions(allow_empty=True):
            method: declarations.member_function_t

            if method.access_type != "public":
                continue

            targets.append(method)
            targets.append(method.return_type)

            for argType in method.argument_types:
                targets.append(argType)

    for target in targets:
        founds = getIncludeFiles(target)

        if founds:
            includeFiles.update(founds)

    # Standard가 가장 먼저 include되고 TopoDS가 그 다음으로 include 되어야 함.
    # 모든 정렬 기준을 순차적으로 적용
    includeFiles = sorted(
        includeFiles,
        key=lambda x: (
            not x.startswith("Standard_"),
            not x.startswith("TopoDS_"),
            all(map(lambda h: not x.startswith(h), REQUIRED_HEADERS)),
            x,
        ),
    )
    includeFiles.append(f"sanitizer/lsan_interface.h")

    return "\n".join(
        map(
            lambda x: (
                f'#include "{x}"' if x == f"{HEADER_NAME}.h" else f"#include <{x}>"
            ),
            includeFiles,
        )
    )


@typechecked
def processChild(
    decl: declarations.declaration_t,
    buildType: str,
    extension: str,
    processFunction: Callable[..., str],
) -> None:
    [originalName, childName] = getTypeName(decl)

    file_path = None
    if decl.location is not None:
        file_path = decl.location.file_name

    if file_path and file_path.startswith(OCCT_SRC_PATH):
        relOcFileName = file_path.replace(OCCT_SRC_PATH, "")
    elif file_path:
        relOcFileName = os.path.basename(file_path)
    else:
        relOcFileName = "unknown_header"

    mkdirp(f"{BUILD_DIRECTORY}/{buildType}/{relOcFileName}")
    filename = f"{BUILD_DIRECTORY}/{buildType}/{relOcFileName}/{childName}{extension}"

    includes = processHeaders(decl)

    preamble = f"{includes}\n{referenceTypeTemplateDefs}"

    if True or not os.path.exists(filename):
        try:
            output = processFunction(preamble, decl)
            with open(filename, "w") as bindingsFile:
                bindingsFile.write(output)
            console.print(f"Generated {filename}")
        except SkipException as e:
            console.print(str(e))
        except Exception as e:
            console.print_exception(show_locals=False)
            raise e


@typechecked
def strip_template_params(full_name: str) -> str:
    idx = full_name.find("<")
    return full_name[:idx] if idx != -1 else full_name


@typechecked
def getTypeName(
    decl: Union[declarations.declaration_t, declarations.cpptypes.type_t],
) -> list[str]:
    name = ""

    if hasattr(decl, "base"):
        base = decl.base

        if hasattr(base, "name"):
            name = base.name
        elif hasattr(base, "decl_string"):
            name = base.decl_string
    elif hasattr(decl, "name"):
        name = decl.name
    elif hasattr(decl, "decl_string"):
        name = decl.decl_string

    return [name, strip_template_params(name)]


@typechecked
def processChildren(
    ns: declarations.namespace_t,
    buildType: str,
    extension: str,
) -> None:
    children = (
        list(ns.typedefs())
        + list(ns.enumerations())
        + list(ns.declarations)
        + list(ns.classes())
    )

    console.print(f"Children length is {len(children)}")

    for child in children:
        [originalName, partialName] = getTypeName(child)

        if originalName not in cache:
            cache[originalName] = []

        cache[originalName].append(child)

    console.print(f"Completed caching")

    futures = []
    parallel = Parallel(n_jobs=-1, backend="threading")

    processed = set()

    for child in children:
        [originalName, childName] = getTypeName(child)

        if not filterCommon(child):
            continue

        if childName in processed:
            continue

        if not originalName:
            continue

        # if originalName != "OSD_Parallel":
        #     continue

        processFunction = None

        if filterClasses(child):
            processFunction = embindGenerationFuncClasses
        elif filterTemplates(child):
            processFunction = embindGenerationFuncTemplates
        elif filterEnums(child):
            processFunction = embindGenerationFuncEnums
        else:
            continue

        processed.add(childName)

        func = delayed(processChild)

        futures.append(
            func(
                child,
                buildType,
                extension,
                processFunction,
            )
        )

    out = parallel(futures)

    print(f"Processed {len(out)} children")


@typechecked
def getIncludeFiles(
    decl: Union[declarations.declaration_t, declarations.cpptypes.type_t],
) -> str | None:
    while hasattr(decl, "base"):
        decl = decl.base

    if isinstance(decl, declarations.declarated_t):
        decl = decl.declaration

    queue = [decl]
    result = set()
    checked = {}

    while len(queue):
        d = queue.pop()

        if isinstance(d, declarations.fundamental_t):
            continue

        [originalName, partialName] = getTypeName(d)

        if originalName in checked:
            continue

        checked[originalName] = True

        # FIXME
        # founds = getattr(cache, originalName, [])
        # print(founds, originalName, founds.__class__.__name__)
        # queue.extend(founds)

        # if declarations.templates.is_instantiation(originalName):
        #     _, params = declarations.templates.split(originalName)

        #     for param in params:
        #         founds = getattr(cache, param, [])
        #         queue.extend(founds)

        if hasattr(d, "location"):
            if d.location is not None:
                fileName: str = d.location.file_name

                fileName = fileName.replace(".lxx", ".hxx")

                if fileName.startswith(OCCT_SRC_PATH) or fileName.endswith(HEADER_PATH):
                    result.add(os.path.basename(fileName))

    return result


@typechecked
def embindGenerationFuncClasses(
    preamble: str,
    child: declarations.class_t,
    className: str = None,
) -> str:
    embindings = EmbindBindings()

    output = embindings.processClass(child, className=className)

    return preamble + output


@typechecked
def embindGenerationFuncTemplates(
    preamble: str,
    child: declarations.declaration_t,
) -> str:
    templateClass = child

    # pygccxml typedef_t 기반 템플릿 인스턴스 처리
    templateClass = getClass(child)

    if isinstance(templateClass, declarations.class_t):
        return embindGenerationFuncClasses(
            preamble, templateClass, className=child.decl_string
        )

    return ""


@typechecked
def embindGenerationFuncEnums(
    preamble: str,
    child: declarations.enumeration_t,
) -> str:
    embindings = EmbindBindings()

    output = embindings.processEnum(child)

    return preamble + output


@typechecked
def process(extension: str, customCode: str):
    tu = parse(customCode)

    processChildren(
        tu,
        "bindings",
        extension,
    )


@typechecked
def parse(additionalCppCode: str = ""):
    """
    CastXML + pygccxml 기반으로 헤더 파싱 및 global_namespace 반환
    """
    generator_path, generator_name = utils.find_xml_generator()

    xml_generator_config = parser.xml_generator_configuration_t(
        xml_generator_path=generator_path,
        xml_generator=generator_name,
        compiler_path="/emsdk/upstream/bin/clang++",
        keep_xml=True,
        # content_type=parser.CONTENT_TYPE.CACHED_SOURCE_FILE
    )

    # include path 인자 구성 + Emscripten 전용 플래그 추가
    args = [*includePathArgs]
    extra_flags = [
        "-D__EMSCRIPTEN__",
        "-std=c++17",
    ]

    xml_generator_config.cflags = " ".join(args + extra_flags)

    # 가상 헤더 파일 내용 생성
    header_content = OCCT_INCLUDE_STATEMENTS + "\n" + additionalCppCode

    console.print("Writing header file...")

    # 임시 헤더 파일 생성
    with open(HEADER_PATH, "w") as f:
        f.write(header_content)

    file_config = parser.file_configuration_t(
        data=HEADER_PATH, content_type=parser.CONTENT_TYPE.CACHED_SOURCE_FILE
    )

    project_reader = parser.project_reader_t(
        xml_generator_config, cache=parser.directory_cache_t
    )

    console.print("Parsing header file...")

    # pygccxml 파싱 수행
    decls = project_reader.read_files(
        [file_config], compilation_mode=parser.COMPILATION_MODE.ALL_AT_ONCE
    )
    global_ns = declarations.get_global_namespace(decls)

    global_ns.init_optimizer()

    return global_ns


@typechecked
def generateCustomCodeBindings(customCode: str):
    mkdirp(LIBRARY_BASE_PATH)

    process(".cpp", customCode)


if __name__ == "__main__":
    rmrf(LIBRARY_BASE_PATH)
    mkdirp(LIBRARY_BASE_PATH)

    process(".cpp", "")
