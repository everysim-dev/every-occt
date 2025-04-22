#!/usr/bin/python3

from dataclasses import dataclass
from typing import Callable, Union
from bindings import EmbindBindings
import os
from parser import is_public
from wasmGenerator.Common import SkipException, unwrapType
from Common import ocIncludeFiles, includePathArgs, console, HEADER_NAME, HEADER_PATH
from plumbum import local
from pygccxml import parser, declarations, utils
import os
from joblib import Parallel, delayed
from typeguard import typechecked
from clang import cindex

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
#ifdef CONSTRUCTOR
#define CONSTRUCTOR_SAVED CONSTRUCTOR
#undef CONSTRUCTOR
#endif

#include <emscripten/bind.h>
#include <functional>
#include <type_traits>
#include <array>
#include <stdexcept>

// Emscripten 바인딩 사용 후 원래 매크로 복원
#ifdef CONSTRUCTOR_SAVED
#define CONSTRUCTOR CONSTRUCTOR_SAVED
#undef CONSTRUCTOR_SAVED
#endif

using namespace emscripten;

// std::array와 C 배열 간의 변환 유틸리티 함수
template<typename T, size_t N>
std::array<std::remove_cv_t<T>, N> toStdArray(const T (&arr)[N]) {
  std::array<std::remove_cv_t<T>, N> result;
  for (size_t i = 0; i < N; ++i) result[i] = arr[i];
  return result;
}

// std::array를 C 배열로 복사
template<typename T, size_t N>
void toCArray(T (&dest)[N], const std::array<std::remove_cv_t<T>, N>& src) {
  for (size_t i = 0; i < N; ++i) dest[i] = src[i];
}

// C++17 if constexpr 기반 통합 getReferenceValue/updateReferenceValue
template<typename T>
auto getReferenceValue(const val& v) {
  if constexpr (std::is_array_v<T>) {
    using U = std::remove_cv_t<std::remove_extent_t<T>>;
    constexpr size_t N = std::extent_v<T>;
    std::array<U, N> arr{};  // 초기화 추가
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
    using U = std::remove_cv_t<std::remove_extent_t<T>>;
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

// 배열 참조 매개변수를 위한 헬퍼 함수
template<typename T, size_t N>
void copyToArrayRef(T (&dest)[N], const std::array<std::remove_cv_t<T>, N>& src) {
  for (size_t i = 0; i < N; ++i) {
    dest[i] = src[i];
  }
}
"""

cache = {}


@typechecked
def getClass(decl: declarations.declaration_t) -> declarations.class_t | None:
    result = decl

    while isinstance(result, declarations.typedef_t):
        result = result.decl_type
        if hasattr(result, "declaration"):
            result = result.declaration

    if isinstance(result, declarations.class_t):
        return result

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
        "AdvApp2Var_ApproxAFunc2Var": ["AdvApp2Var_Criterion", "AdvApprox_Cutting"],
        "BRepApprox_ResConstraintOfMyGradientbisOfTheComputeLineOfApprox": ["AppParCurves_MultiCurve"],
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
        "AppDef_MultiLine" , # AppDef
        "BOPDS_PaveBlock",
        "Standard_TypeDef",
        "BRepGProp_Face",
        "BRepGProp_Domain",
        "gp",
        "Message_ProgressRange",
        "math_Matrix",  # BRep
        "BOPAlgo_PaveFiller",  # BRepAlgoAPI
        "BRepApprox_TheMultiLineOfApprox",  # BRepApprox
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
    # tu: cindex.TranslationUnit,
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

        print(f"Processing {childName}")

        if not filterCommon(child):
            continue

        if childName in processed:
            continue

        if not originalName:
            continue

        # if originalName != "Message_ProgressScope":
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
) -> set | None:
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


def get_public_methods_and_ctors(class_cursor: cindex.Cursor) -> tuple[list[str], list[str]]:
    """
    주어진 클래스 커서에 대해 public 메서드와 생성자 목록을 반환합니다.
    """
    methods:    list[C_Method] = []
    ctors:      list[C_Constructor] = []
    for child in class_cursor.get_children():
        if is_public(child):
            if child.kind == cindex.CursorKind.CXX_METHOD:
                name = child.spelling

                raw_args = [arg for arg in child.get_arguments()]

                if any(map(lambda x: not is_public(x), raw_args)):
                    continue
                if not is_public(child.result_type):
                    continue

                if child.spelling.startswith("operator"):
                    continue

                args = [C_Argument(arg.spelling, arg.type.spelling) for arg in raw_args]
                returnType = C_Type(child.result_type.spelling)

                methods.append(
                    C_Method(name, args, returnType)
                )
            elif child.kind == cindex.CursorKind.CONSTRUCTOR:
                raw_args = [arg for arg in child.get_arguments()]

                if any(map(lambda x: not is_public(x), raw_args)):
                    continue

                args = [C_Argument(arg.spelling, arg.type.spelling) for arg in raw_args]

                ctors.append(C_Constructor(child.spelling, args))
    return methods, ctors


@dataclass
class C_Type:
    name: str

@dataclass
class C_Argument:
    name: str
    type: C_Type

@dataclass
class C_Method:
    name: str
    args: list[C_Argument]
    returnType: C_Type

@dataclass
class C_Constructor:
    name: str
    args: list[C_Argument]

@dataclass
class C_Class:
    name: str
    methods: list[C_Method]
    constructors: list[C_Constructor]

@typechecked
def process(extension: str, customCode: str):    
    cindex.Config.set_library_file(
        "/usr/lib/x86_64-linux-gnu/libclang-20.so.1"
    )
    index = cindex.Index.create()

    print("Index created")

    translationUnit = index.parse(
        HEADER_PATH, [
        "-x",
        "c++",
        "-stdlib=libc++",
        "-D__EMSCRIPTEN__"
        ] + includePathArgs
    )

    classes = []

    for cursor in translationUnit.cursor.get_children():
        name = cursor.spelling

        if not name.startswith("Handle_"):
            continue

        if not cursor.kind == cindex.CursorKind.TYPEDEF_DECL:
            print("1", cursor.spelling, cursor.kind)

        if cursor.kind == cindex.CursorKind.TYPEDEF_DECL:
            cursor = cursor.underlying_typedef_type

        if not cursor.kind == cindex.TypeKind.ELABORATED:
            print("2", cursor.spelling, cursor.kind)

        if cursor.kind == cindex.TypeKind.ELABORATED:
            cursor = cursor.get_named_type()

        if not cursor.kind == cindex.TypeKind.UNEXPOSED:
            print("3", cursor.spelling, cursor.kind)

        if cursor.kind == cindex.TypeKind.UNEXPOSED:
            cursor = cursor.get_canonical()

        if not cursor.kind == cindex.TypeKind.RECORD:
            print("4", cursor.spelling, cursor.kind)

        if cursor.kind == cindex.TypeKind.RECORD:
            cursor = cursor.get_declaration()

        if not cursor.kind == cindex.CursorKind.CLASS_DECL:
            print("5", cursor.spelling, cursor.kind)

        if not is_public(cursor):
            continue

        # print(f"Class: {name}, Cursor: {cursor.spelling}, kind: {cursor.kind}")

        if cursor.kind == cindex.CursorKind.CLASS_DECL:
            methods, constructors = get_public_methods_and_ctors(cursor)
            theClass = C_Class(name, methods, constructors)
            classes.append(theClass)
            # print(f"{name}, methods: {methods}, Constructors: {constructors}")

    print(f"Classes: {len(classes)}")

    exit()

    ns = parse(customCode)

    processChildren(
        ns,
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
    )

    # include path 인자 구성 + Emscripten 전용 플래그 추가
    args = [
        "-I/emsdk/upstream/emscripten/system/include/",
        "-I/emsdk/upstream/emscripten/system/lib/libcxx/include/__support/newlib/",
        *includePathArgs,
    ]
    extra_flags = [
        "-D__EMSCRIPTEN__",
        # "-std=c++17",
    ]

    xml_generator_config.cflags = " ".join(args + extra_flags)

    # 가상 헤더 파일 내용 생성
    header_content = OCCT_INCLUDE_STATEMENTS + "\n" + additionalCppCode

    console.print("Writing header file...")

    # 임시 헤더 파일 생성
    with open(HEADER_PATH, "w") as f:
        f.write(header_content)

    console.print("Parsing header file...")

    file_config = parser.file_configuration_t(
        data=HEADER_PATH, content_type=parser.CONTENT_TYPE.CACHED_SOURCE_FILE
    )

    project_reader = parser.project_reader_t(
        xml_generator_config, cache=parser.directory_cache_t
    )

    # pygccxml 파싱 수행
    decls = project_reader.read_files(
        [file_config], compilation_mode=parser.COMPILATION_MODE.FILE_BY_FILE
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
