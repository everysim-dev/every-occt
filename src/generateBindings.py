#!/usr/bin/python3

from typing import Callable
from bindings import EmbindBindings, shouldProcessClass
import clang.cindex
import os
from filter.filterTypedefs import filterTypedef
from filter.filterEnums import filterEnum
from wasmGenerator.Common import ignoreDuplicateTypedef, SkipException
from Common import ocIncludeFiles, includePathArgs
import multiprocessing
import os
from filter.filterPackages import filterPackages
from functools import partial
from plumbum import local

LIBRARY_BASE_PATH = "/opencascade.js/build/bindings"
BUILD_DIRECTORY = "/opencascade.js/build"
OCCT_SRC_PATH = "/occt/src/"
OCCT_INCLUDE_STATEMENTS = os.linesep.join(
    map(lambda x: f'#include "{os.path.basename(x)}"', list(sorted(ocIncludeFiles)))
)

mkdirp = local["mkdir"]["-p"]
rmrf = local["rm"]["-rf"]


def filterClasses(child, customBuild):
    if customBuild:
        return child.location.file.name == "myMain.h" and shouldProcessClass(
            child, OCCT_SRC_PATH
        )
    return (
        child.extent.start.file.name.startswith(OCCT_SRC_PATH)
        and filterPackages(os.path.basename(os.path.dirname(child.location.file.name)))
        and shouldProcessClass(child, OCCT_SRC_PATH)
    )


def filterTemplates(child, customBuild):
    if customBuild:
        return (
            child.location.file.name == "myMain.h"
            and child.kind == clang.cindex.CursorKind.TYPEDEF_DECL
            and (
                child.underlying_typedef_type.kind == clang.cindex.TypeKind.ELABORATED
                or child.underlying_typedef_type.kind == clang.cindex.TypeKind.UNEXPOSED
            )
        )
    return (
        (
            child.extent.start.file.name.startswith(OCCT_SRC_PATH)
            and filterPackages(
                os.path.basename(os.path.dirname(child.location.file.name))
            )
        )
        and child.kind == clang.cindex.CursorKind.TYPEDEF_DECL
        and (
            child.underlying_typedef_type.kind == clang.cindex.TypeKind.ELABORATED
            or child.underlying_typedef_type.kind == clang.cindex.TypeKind.UNEXPOSED
        )
    )


def filterEnums(child, customBuild):
    if customBuild:
        return child.location.file.name == "myMain.h"
    return (
        child.extent.start.file.name.startswith(OCCT_SRC_PATH)
        and filterPackages(os.path.basename(os.path.dirname(child.location.file.name)))
    ) and child.kind == clang.cindex.CursorKind.ENUM_DECL


def processChildBatch(
    customCode,
    generator,
    buildType: str,
    extension: str,
    filterFunction: Callable[[any], bool],
    processFunction: Callable[[any, any], str],
    typedefGenerator: any,
    templateTypedefGenerator: any,
    preamble: str,
    customBuild: bool,
    batch,
):
    tu = parse(customCode)
    children = list(generator(tu)[batch.start : batch.stop])

    for child in children:
        if not filterFunction(child, customBuild) or child.spelling == "":
            continue

        relOcFileName: str = child.extent.start.file.name.replace(OCCT_SRC_PATH, "")
        mkdirp(f"{BUILD_DIRECTORY}/{buildType}/{os.path.dirname(relOcFileName)}")
        mkdirp(f"{BUILD_DIRECTORY}/{buildType}/{relOcFileName}")
        filename = (
            f"{BUILD_DIRECTORY}/{buildType}/{relOcFileName}/{child.spelling}{extension}"
        )

        if not os.path.exists(filename):
            print(f"Processing {child.spelling}")
            try:
                output = processFunction(
                    tu,
                    preamble,
                    child,
                    typedefGenerator(tu),
                    templateTypedefGenerator(tu),
                )
                with open(filename, "w") as bindingsFile:
                    bindingsFile.write(output)
            except SkipException as e:
                print(str(e))
        else:
            print(f"file {child.spelling}.cpp already exists, skipping")


def split(a, n):
    k, m = divmod(len(a), n)
    return (a[i * k + min(i, m) : (i + 1) * k + min(i + 1, m)] for i in range(n))


def processChildren(
    tu,
    generator,
    buildType: str,
    extension: str,
    filterFunction: Callable[[any], bool],
    processFunction: Callable[[any, any], str],
    typedefs: any,
    templateTypedefs: any,
    preamble: str,
    customCode,
    customBuild,
):
    func = partial(
        processChildBatch,
        customCode,
        generator,
        buildType,
        extension,
        filterFunction,
        processFunction,
        typedefs,
        templateTypedefs,
        preamble,
        customBuild,
    )
    if not customBuild:
        import concurrent.futures
        numthreads = os.cpu_count()
        batches = list(split(range(len(generator(tu))), numthreads))
        with concurrent.futures.ProcessPoolExecutor(max_workers=numthreads) as executor:
            futures = [executor.submit(func, batch) for batch in batches]
            for future in concurrent.futures.as_completed(futures):
                future.result()
    else:
        func(range(len(generator(tu))))


def processTemplate(child):
    templateRefs = list(
        filter(
            lambda x: x.kind == clang.cindex.CursorKind.TEMPLATE_REF,
            child.get_children(),
        )
    )
    if len(templateRefs) != 1:
        raise SkipException(
            f'The number of template refs for the template typedef "{child.spelling}" is not 1!'
        )

    templateClass = templateRefs[0].get_definition()
    if templateClass is None:
        raise SkipException(f"Template class is None ({child.spelling})")
    templateArgNames = list(
        filter(
            lambda x: x.kind == clang.cindex.CursorKind.TEMPLATE_TYPE_PARAMETER,
            templateClass.get_children(),
        )
    )
    templateArgs = {}
    for i, templateArgName in enumerate(templateArgNames):
        templateArgType = child.type.get_template_argument_type(i)
        if templateArgType.spelling == "":
            raise SkipException(
                f"Template argument type is empty for at least one argument. Is this class using default values for template arguments? This is currently not supported ({child.spelling})"
            )
        templateArgs[templateArgName.spelling] = templateArgType

    return [templateClass, templateArgs]


def embindGenerationFuncClasses(tu, preamble, child, typedefs, templateTypedefs) -> str:
    embindings = EmbindBindings(typedefs, templateTypedefs, tu)
    output = embindings.processClass(child)

    return preamble + output


def embindGenerationFuncTemplates(
    tu, preamble, child, typedefs, templateTypedefs
) -> str:
    [templateClass, templateArgs] = processTemplate(child)
    embindings = EmbindBindings(typedefs, templateTypedefs, tu)
    output = embindings.processClass(templateClass, child, templateArgs)

    return preamble + output


def embindGenerationFuncEnums(tu, preamble, child, typedefs, templateTypedefs) -> str:
    embindings = EmbindBindings(typedefs, templateTypedefs, tu)
    output = embindings.processEnum(child)

    return preamble + output


def templateTypedefGenerator(tu):
    return list(
        filter(
            lambda x: x.kind == clang.cindex.CursorKind.TYPEDEF_DECL
            and not (x.get_definition() is None or not x == x.get_definition())
            and filterTypedef(x)
            and x.type.get_num_template_arguments() != -1
            and not ignoreDuplicateTypedef(x),
            tu.cursor.get_children(),
        )
    )


def typedefGenerator(tu):
    return list(
        filter(
            lambda x: x.kind == clang.cindex.CursorKind.TYPEDEF_DECL,
            tu.cursor.get_children(),
        )
    )


def allChildrenGenerator(tu):
    return list(tu.cursor.get_children())


def enumGenerator(tu):
    return list(
        filter(
            lambda x: x.kind == clang.cindex.CursorKind.ENUM_DECL and filterEnum(x),
            tu.cursor.get_children(),
        )
    )


def process(extension, preamble, customCode, customBuild):
    generationFuncClasses = embindGenerationFuncClasses
    generationFuncTemplates = embindGenerationFuncTemplates
    generationFuncEnums = embindGenerationFuncEnums

    tu = parse(customCode)

    processChildren(
        tu,
        allChildrenGenerator,
        "bindings",
        extension,
        filterClasses,
        generationFuncClasses,
        typedefGenerator,
        templateTypedefGenerator,
        preamble,
        customCode,
        customBuild,
    )
    processChildren(
        tu,
        templateTypedefGenerator,
        "bindings",
        extension,
        filterTemplates,
        generationFuncTemplates,
        typedefGenerator,
        templateTypedefGenerator,
        preamble,
        customCode,
        customBuild,
    )
    processChildren(
        tu,
        enumGenerator,
        "bindings",
        extension,
        filterEnums,
        generationFuncEnums,
        typedefGenerator,
        templateTypedefGenerator,
        preamble,
        customCode,
        customBuild,
    )


def parse(additionalCppCode=""):
    index = clang.cindex.Index.create()
    translationUnit = index.parse(
        "myMain.h",
        [
            "-x",
            "c++",
            "-stdlib=libc++",
            "-D__EMSCRIPTEN__",
            "-std=c++17",
            "-Wno-deprecated-declarations",
        ]
        + includePathArgs,
        [["myMain.h", OCCT_INCLUDE_STATEMENTS + "\n" + additionalCppCode]],
    )

    diagnostics = [d for unit in translationUnit.diagnostics if "'bits/alltypes.h' file not found" not in unit.format()]

    if len(diagnostics) > 0:
        print("Diagnostic Messages:")
        for d in diagnostics:
            print("  " + d.format())

    return translationUnit


referenceTypeTemplateDefs = (
    "\n"
    + "#include <emscripten/bind.h>\n"
    + "using namespace emscripten;\n"
    + "#include <functional>\n"
    + "#include <type_traits>\n" 
    + "\n"
    + "// 복사 가능/불가능 타입을 분류하는 Type Traits\n"
    + "template<typename T>\n"
    + "struct is_non_copyable_type : std::false_type {};\n"
    + "\n"
    + "// 복사 가능한 타입을 위한 getReferenceValue\n"
    + "template<typename T>\n"
    + "typename std::enable_if<!is_non_copyable_type<T>::value && !std::is_arithmetic<T>::value, T>::type\n"
    + "getReferenceValue(const emscripten::val& v) {\n"
    + '  if(!(v.typeOf().as<std::string>() == "object")) {\n'
    + "    return v.as<T>(allow_raw_pointers());\n"
    + '  } else if(v.typeOf().as<std::string>() == "object" && v.hasOwnProperty("current")) {\n'
    + '    return v["current"].as<T>(allow_raw_pointers());\n'
    + "  }\n"
    + '  throw("unsupported type");\n'
    + "}\n"
    + "\n"
    + "// 복사 불가능한 타입을 위한 getReferenceValue\n"
    + "template<typename T>\n"
    + "typename std::enable_if<is_non_copyable_type<T>::value, T&>::type\n"
    + "getReferenceValue(const emscripten::val& v) {\n"
    + '  if(!(v.typeOf().as<std::string>() == "object")) {\n'
    + "    return *v.as<T*>(allow_raw_pointers());\n"
    + '  } else if(v.typeOf().as<std::string>() == "object" && v.hasOwnProperty("current")) {\n'
    + '    return *v["current"].as<T*>(allow_raw_pointers());\n'
    + "  }\n"
    + '  throw("unsupported type");\n'
    + "}\n"
    + "\n"
    + "// 일반 타입을 위한 updateReferenceValue\n"
    + "template<typename T>\n"
    + "typename std::enable_if<!is_non_copyable_type<T>::value && !std::is_arithmetic<T>::value>::type\n"
    + "updateReferenceValue(emscripten::val& v, T& val) {\n"
    + '  if(v.typeOf().as<std::string>() == "object" && v.hasOwnProperty("current")) {\n'
    + '    v.set("current", val);\n'
    + "  }\n"
    + "}\n"
    + "\n"
    + "// 복사 불가능한 타입을 위한 updateReferenceValue\n"
    + "template<typename T>\n"
    + "typename std::enable_if<is_non_copyable_type<T>::value>::type\n"
    + "updateReferenceValue(emscripten::val& v, T& val) {\n"
    + '  if(v.typeOf().as<std::string>() == "object" && v.hasOwnProperty("current")) {\n'
    + '    v.set("current", std::addressof(val));\n'
    + "  }\n"
    + "}\n"
    + "\n"
    + "// 기본 타입의 참조 매개변수를 처리하기 위한 특수 래퍼\n"
    + "template<typename T>\n"
    + "typename std::enable_if<std::is_arithmetic<T>::value, emscripten::val>::type\n"
    + "wrapReferenceParameter(T& value) {\n"
    + "  emscripten::val obj = emscripten::val::object();\n"
    + '  obj.set("value", value);\n'
    + "  return obj;\n"
    + "}\n"
    + "\n"
    + "// 기본 타입 참조 매개변수를 위한 getReferenceValue 특수화\n"
    + "template<typename T>\n"
    + "typename std::enable_if<std::is_arithmetic<T>::value, T&>::type\n"
    + "getReferenceValue(const emscripten::val& v) {\n"
    + "  static thread_local T temp;\n"  # 스레드 로컬 임시 변수 사용
    + '  if(v.typeOf().as<std::string>() == "object" && v.hasOwnProperty("value")) {\n'
    + '    temp = v["value"].as<T>();\n'
    + "    return temp;\n"
    + "  }\n"
    + "  temp = v.as<T>();\n"
    + "  return temp;\n"
    + "}\n"
    + "\n"
    + "// 기본 타입 참조 매개변수를 위한 updateReferenceValue 특수화\n"
    + "template<typename T>\n"
    + "typename std::enable_if<std::is_arithmetic<T>::value>::type\n"
    + "updateReferenceValue(emscripten::val& v, T& val) {\n"
    + '  if(v.typeOf().as<std::string>() == "object" && v.hasOwnProperty("value")) {\n'
    + '    v.set("value", val);\n'
    + "  } else {\n"
    + "    emscripten::val obj = emscripten::val::object();\n"
    + '    obj.set("value", val);\n'
    + '    v.set("current", obj);\n'
    + "  }\n"
    + "}\n"
)


def generateCustomCodeBindings(customCode):
    mkdirp(LIBRARY_BASE_PATH)

    embindPreamble = (
        f"{OCCT_INCLUDE_STATEMENTS}\n{referenceTypeTemplateDefs}\n{customCode}"
    )

    process(".cpp", embindPreamble, customCode, True)


if __name__ == "__main__":
    rmrf(LIBRARY_BASE_PATH)
    mkdirp(LIBRARY_BASE_PATH)

    embindPreamble = f"{OCCT_INCLUDE_STATEMENTS}\n{referenceTypeTemplateDefs}"

    process(".cpp", embindPreamble, "", False)
