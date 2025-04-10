#!/usr/bin/python3

from typing import Callable
from bindings import EmbindBindings
import os
from wasmGenerator.Common import SkipException
from Common import ocIncludeFiles, includePathArgs, console
from plumbum import local
from pygccxml import parser, declarations, utils
import tempfile, os
from joblib import Parallel, delayed
from typeguard import typechecked

LIBRARY_BASE_PATH = os.environ.get(
    "OCJS_BINDINGS_PATH", "/opencascade.js/build/bindings"
)
BUILD_DIRECTORY = os.environ.get("OCJS_BUILD_PATH", "/opencascade.js/build")
OCCT_SRC_PATH = os.environ.get("OCCT_SRC_PATH", "/occt/src/")
OCCT_INCLUDE_STATEMENTS = os.linesep.join(
    map(lambda x: f'#include "{os.path.basename(x)}"', list(sorted(ocIncludeFiles)))
)

mkdirp = local["mkdir"]["-p"]
rmrf = local["rm"]["-rf"]


referenceTypeTemplateDefs = """
#include <emscripten/bind.h>
#include <functional>

using namespace emscripten;

template<typename T>
T getReferenceValue(const emscripten::val& v) {
  if(!(v.typeOf().as<std::string>() == "object")) {
    return v.as<T>(allow_raw_pointers());
  } else if(v.typeOf().as<std::string>() == "object" && v.hasOwnProperty("current")) {
    return v["current"].as<T>(allow_raw_pointers());
  }
  throw("unsupported type");
}

template<typename T>
void updateReferenceValue(emscripten::val& v, T& val) {
  if(v.typeOf().as<std::string>() == "object" && v.hasOwnProperty("current")) {
    v.set("current", val);
  }
}

"""

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

    file_name = decl.location.file_name
    if not file_name or not file_name.startswith(OCCT_SRC_PATH):
        return False

    if isinstance(decl.parent, declarations.class_t):
        return any(map(lambda x: x is decl, decl.parent.public_members))

    return True


@typechecked
def filterClasses(decl: declarations.declaration_t) -> bool:
    if not isinstance(decl, declarations.class_t):
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
def processChild(
    decl: declarations.declaration_t,
    buildType: str,
    extension: str,
    processFunction: Callable[..., str],
    preamble: str,
) -> None:
    # pygccxml declaration용 이름
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

    if not os.path.exists(filename):
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
    else:
        console.print(f"file {childName}.cpp already exists, skipping")


@typechecked
def strip_template_params(full_name: str) -> str:
    idx = full_name.find("<")
    return full_name[:idx] if idx != -1 else full_name


@typechecked
def getTypeName(decl: declarations.declaration_t) -> list[str]:
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
    preamble: str,
) -> None:
    children = (
        list(ns.declarations)
        + list(ns.classes())
        + list(ns.enumerations())
        + list(ns.typedefs())
    )

    futures = []
    parallel = Parallel(n_jobs=-1, backend="threading")

    processed = set()

    for child in children:
        if not filterCommon(child):
            continue

        [originalName, childName] = getTypeName(child)

        if childName in processed:
            continue

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

        console.log(f"Processing {childName}")

        func = delayed(processChild)

        futures.append(
            func(
                child,
                buildType,
                extension,
                processFunction,
                preamble,
            )
        )

    out = parallel(futures)

    print(f"Processed {len(out)} children")


@typechecked
def embindGenerationFuncClasses(
    preamble: str,
    child: declarations.class_t,
    className: str = None,
) -> str:
    embindings = EmbindBindings()

    if child.location is not None:
        file_path = child.location.file_name
        preamble = f'#include "{os.path.basename(file_path)}"\n{referenceTypeTemplateDefs}'

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
            preamble, templateClass, className=child.name
        )

    return ""


@typechecked
def embindGenerationFuncEnums(
    preamble: str,
    child: declarations.enumeration_t,
) -> str:
    embindings = EmbindBindings()

    if child.location is not None:
        file_path = child.location.file_name
        preamble = f'#include "{os.path.basename(file_path)}"\n{referenceTypeTemplateDefs}'

    output = embindings.processEnum(child)

    return preamble + output


@typechecked
def templateTypedefGenerator(ns: declarations.namespace_t):
    """
    pygccxml global_namespace에서 템플릿 인자를 가진 typedef만 반환
    """
    typedefs = []
    for td in ns.typedefs():
        try:
            underlying = td.decl_type
            # 템플릿 인자가 있는지 간단히 문자열로 판별
            if "<" in str(underlying) and ">" in str(underlying):
                typedefs.append(td)
        except:
            continue
    return typedefs


@typechecked
def typedefGenerator(ns: declarations.namespace_t):
    """
    pygccxml global_namespace에서 모든 typedef 반환
    """
    return list(ns.typedefs())


@typechecked
def process(extension: str, preamble: str, customCode: str):
    tu = parse(customCode)

    processChildren(
        tu,
        "bindings",
        extension,
        preamble,
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
    # HEADER_NAME = generate()
    HEADER_NAME = "myMain"
    header_path = f"{HEADER_NAME}.h"

    # 임시 헤더 파일 생성
    tmp_dir = tempfile.gettempdir()
    tmp_header_path = os.path.join(tmp_dir, header_path)
    with open(tmp_header_path, "w") as f:
        f.write(header_content)

    file_config = parser.file_configuration_t(
        data=tmp_header_path, content_type=parser.CONTENT_TYPE.CACHED_SOURCE_FILE
    )

    project_reader = parser.project_reader_t(
        xml_generator_config, cache=parser.directory_cache_t
    )

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

    embindPreamble = (
        f"{OCCT_INCLUDE_STATEMENTS}\n{referenceTypeTemplateDefs}\n{customCode}"
    )

    process(".cpp", embindPreamble, customCode)


if __name__ == "__main__":
    rmrf(LIBRARY_BASE_PATH)
    mkdirp(LIBRARY_BASE_PATH)

    embindPreamble = f"{OCCT_INCLUDE_STATEMENTS}\n{referenceTypeTemplateDefs}"

    process(".cpp", embindPreamble, "")
