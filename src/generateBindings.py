#!/usr/bin/python3

from dataclasses import dataclass
import re
import os
from parser import is_public
from wasmGenerator.Common import SkipException
from Common import (
    ocIncludeFiles,
    includePathArgs,
    console,
    HEADER_NAME,
    HEADER_PATH,
    HEADERS,
    REQUIRED_HEADERS,
)
from plumbum import local
import os
from typeguard import typechecked
from clang import cindex
from filter.filterPackages import filterPackages

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
}"""

cache = {}


@typechecked
def applyTemplate(
    typeName: str,
    templateTypes: list[cindex.Type],
) -> str:
    if len(templateTypes):
        templateType = templateTypes[0]
        typeName = re.sub("<T>", f"<{templateType.spelling}>", typeName)
        typeName = re.sub(r"type-parameter-\d-\d", templateType.spelling, typeName)

    return typeName


@typechecked
def get_qualified_type(
    cursorType: cindex.Type, templateTypes: list[cindex.Type] = []
):
    canonical = cursorType.get_canonical()
    pointee = cursorType.get_pointee()
    pointee_decl = pointee.get_declaration()

    names = []
    locations = set()

    decl = pointee_decl.semantic_parent

    if pointee_decl.location.file:
        locations.add(pointee_decl.location.file.name)

    isNeedTemplate = pointee_decl.type.kind in [cindex.TypeKind.UNEXPOSED, cindex.TypeKind.ELABORATED, cindex.TypeKind.INVALID] and templateTypes

    while decl is not None and decl.kind not in [
        cindex.CursorKind.NO_DECL_FOUND,
        cindex.CursorKind.TRANSLATION_UNIT,
    ]:
        if decl.spelling:
            if decl.location.file:
                locations.add(decl.location.file.name)
            names.append(decl.spelling)

        if decl.kind in [cindex.CursorKind.NAMESPACE]:
            break

        decl = decl.semantic_parent

    result = canonical.spelling if isNeedTemplate else cursorType.spelling
    
    prefix = "::".join(reversed(names))
    if prefix not in result:
        result = result.replace(pointee_decl.spelling, f"{prefix}::{pointee_decl.spelling}")

    return applyTemplate(result, templateTypes), locations


@dataclass
class C_Type:
    name: str
    locations: set[str]
    withWrapper: bool = False
    isPointer: bool = False
    isVoid: bool = False
    isCString: bool = False
    isConst: bool = False

    @property
    def spelling(self):
        return "emscripten::val" if self.withWrapper else self.name

    @classmethod
    def needsWrapper(cls, cursorType: cindex.Type) -> bool:
        canonical = cursorType.get_canonical()

        # LValueReference가 아니면 래핑 필요 없음
        if canonical.kind != cindex.TypeKind.LVALUEREFERENCE:
            return False
        
        # 참조 대상 타입 가져오기
        pointee = canonical.get_pointee()

        # const LValueReference는 래핑 불필요
        if pointee.is_const_qualified():
            return False
        # 포인터 참조이면 래핑 필요
        if pointee.kind == cindex.TypeKind.POINTER:
            return True
        # enum이면 래핑 필요
        if pointee.kind == cindex.TypeKind.ENUM:
            return True
        # 기본 타입(int, float 등)은 래핑 필요
        if pointee.kind in {
            cindex.TypeKind.BOOL, cindex.TypeKind.CHAR_U, cindex.TypeKind.UCHAR,
            cindex.TypeKind.CHAR16, cindex.TypeKind.CHAR32, cindex.TypeKind.USHORT,
            cindex.TypeKind.UINT, cindex.TypeKind.ULONG, cindex.TypeKind.ULONGLONG,
            cindex.TypeKind.SHORT, cindex.TypeKind.INT, cindex.TypeKind.LONG,
            cindex.TypeKind.LONGLONG, cindex.TypeKind.FLOAT, cindex.TypeKind.DOUBLE,
            cindex.TypeKind.LONGDOUBLE
        }:
            return True
        return False


    @classmethod
    def fromCursor(
        cls, cursor: cindex.Cursor, templateTypes: list[cindex.Type]
    ) -> "C_Type":
        name, locations = get_qualified_type(cursor.type, templateTypes)

        return cls(
            name=name, 
            locations=locations, 
            withWrapper=cls.needsWrapper(cursor.type), 
            isPointer=cursor.type.kind == cindex.TypeKind.POINTER,
            isVoid=cursor.type.kind == cindex.TypeKind.VOID,
        )

    @classmethod
    def fromCursorType(
        cls, cursorType: cindex.Type, templateTypes: list[cindex.Type]
    ) -> "C_Type":
        cursor = cursorType.get_declaration()

        if cursor.kind is not cindex.CursorKind.NO_DECL_FOUND:
            return cls.fromCursor(cursor, templateTypes)
        
        name, locations = get_qualified_type(cursorType, templateTypes)

        return cls(
            name=name, 
            locations=locations, 
            withWrapper=cls.needsWrapper(cursorType), 
            isPointer=cursorType.kind == cindex.TypeKind.POINTER,
            isVoid=cursorType.kind == cindex.TypeKind.VOID,
        )

@dataclass
class C_ReturnType:
    type: C_Type

    @property
    def spelling(self) -> str:
        return self.type.spelling
    
    @property
    def withWrapper(self) -> bool:
        return self.type.withWrapper
    
    @property
    def locations(self) -> set[str]:
        return self.type.locations
    
    @property
    def innerBinding(self):
        constBinding = "const " if self.type.isConst else ""
        pointerBinding = " &" if self.type.isPointer else ""

        return f"      {constBinding}auto{pointerBinding} ret"
    
    @property
    def finalBinding(self):
        if not self.type.withWrapper:
            return f"      return ret;"
        if self.type.isPointer:
            return f"      return ret == nullptr ? emscripten::val::null() : emscripten::val(static_cast<{self.type.spelling}>(ret));"
        elif self.type.isVoid:
            return f"      return;"
        else:
            return f"      return emscripten::val(ret);"


@dataclass
class C_Argument:
    name: str
    type: C_Type

    @property
    def locations(self):
        return self.type.locations
    
    @property
    def getBinding(self):
        return f"      auto ref_{self.name} = getReferenceValue<{self.type.spelling}>({self.name});"
    
    @property
    def updateBinding(self):
        return f"      updateReferenceValue<{self.type.spelling}>({self.name}, ref_{self.name});"

    def process(self, withName: bool = False, withType: bool = False):
        if withType and withName:
            return f"{self.type.spelling} {self.name}"
        elif withType:
            return self.type.spelling
        elif withName:
            return self.name
        raise ValueError("Either withName or withType must be True")


@dataclass
class C_Method:
    name: str
    isStatic: bool
    args: list[C_Argument]
    returnType: C_ReturnType
    isConst: bool

    @property
    def withWrapper(self) -> bool:
        return any(arg.type.withWrapper for arg in self.args) or self.returnType.withWrapper

    @property
    def locations(self) -> set[str]:
        return {
            loc for arg in self.args for loc in arg.locations
        } | self.returnType.locations
    
    def processInner(self, className: str):
        thatArg = C_Argument(name="that", type=C_Type(name=className, locations=set(), withWrapper=False))

        args = self.args.copy()

        if self.withWrapper and not self.isStatic:
            args.insert(0, thatArg)

        argNamesBinding = ", ".join([arg.process(withName=True) for arg in args])
        argTypesBinding = ", ".join([arg.process(withType=True) for arg in args])
        argsBinding = ", ".join([arg.process(withName=True, withType=True) for arg in args])
        signatureBinding = f"{self.returnType.spelling}({argTypesBinding})"

        if not self.withWrapper:
            constBinding = " const" if self.isConst else ""

            return f"select_overload<{signatureBinding}{constBinding}>(&{className}::{self.name})"

        argGetBindings = "\n".join(
            [arg.getBinding for arg in args if arg.type.withWrapper]
        )
        argUpdateBindings = "\n".join(
            [arg.updateBinding for arg in args if arg.type.withWrapper]
        )

        prefixBinding = f"{className}::" if self.isStatic else f"that."

        return f"""std::function<{signatureBinding}>([]({argsBinding}) -> {self.returnType.spelling} {{
{argGetBindings}
{self.returnType.innerBinding} = {prefixBinding}{self.name}({argNamesBinding});
{argUpdateBindings}
{self.returnType.finalBinding}
  }}
"""


    def process(self, className: str):
        functionBinding = "class_function" if self.isStatic else "function"

        return f"""
    .{functionBinding}("{self.name}", {self.processInner(className)}, allow_raw_pointers())"""


@dataclass
class C_Constructor:
    name: str
    args: list[C_Argument]

    @property
    def locations(self) -> set[str]:
        return {loc for arg in self.args for loc in arg.locations}

    def process(self, className: str, index: int):
        structName = f"{className}_{index + 1}"
        fullArgsBinding = ", ".join(
            [arg.process(withName=True, withType=True) for arg in self.args]
        )
        argNamesBinding = ", ".join([arg.process(withName=True) for arg in self.args])
        argTypesBinding = ", ".join([arg.process(withType=True) for arg in self.args])

        return f"""
  struct {structName}: public {className} {{
    {structName}({fullArgsBinding}): {className}({argNamesBinding}) {{}}
  }};
  class_<{structName}, base<{className}>>("{structName}")
    .constructor<{argTypesBinding}>();"""


@dataclass
class C_Class:
    name: str
    base: str
    methods: list[C_Method]
    constructors: list[C_Constructor]
    fileName: str
    _locations: set[str]

    @property
    def locations(self) -> set[str]:
        combined = (*self.methods, *self.constructors)
        return {
            loc for member in combined for loc in member.locations
        } | self._locations

    @property
    def defaultHeaders(self) -> set[str]:
        defaultHeaders = HEADERS.get(self.name, [])

        headers = [
            f"{header}.hxx"
            for header in [
                *REQUIRED_HEADERS,
                *defaultHeaders,
            ]
        ]

        return set(headers)

    @property
    def headers(self) -> str:
        headers = [
            os.path.basename(header)
            for header in [
                *self.defaultHeaders,
                *self.locations,
            ]
        ]

        return set(headers)

    @property
    def includes(self) -> str:
        # Standard가 가장 먼저 include되고 TopoDS가 그 다음으로 include 되어야 함.
        # 모든 정렬 기준을 순차적으로 적용
        includeFiles = sorted(
            self.headers,
            key=lambda x: (
                not x.startswith("Standard_"),
                not x.startswith("TopoDS_"),
                all(map(lambda h: not x.startswith(h), REQUIRED_HEADERS)),
                x,
            ),
        )

        return "\n".join(
            map(
                lambda x: (
                    f'#include "{x}"' if x == f"{HEADER_NAME}.h" else f"#include <{x}>"
                ),
                includeFiles,
            )
        )

    @property
    def binding(self) -> str:
        methodBindings = "".join(method.process(self.name) for method in self.methods)
        constructorBindings = "".join(
            constructor.process(self.name, index)
            for index, constructor in enumerate(self.constructors)
        )
        baseBinding = f", base<{self.base}>" if self.base else ""

        return f"""{self.includes}
{referenceTypeTemplateDefs}
        
EMSCRIPTEN_BINDINGS({self.name}) {{
  class_<{self.name}{baseBinding}>("{self.name}"){methodBindings};\n{constructorBindings}
}}
"""

    def process(self):
        if not self.fileName:
            return

        basePath = f"{LIBRARY_BASE_PATH}/{os.path.basename(self.fileName)}"
        path = f"{basePath}/{self.name}.cpp"

        if not os.path.exists(path):
            os.makedirs(basePath, exist_ok=True)

            with open(path, "w") as f:
                f.write(self.binding)


@dataclass
class C_Enum:
    name: str
    values: list[str]
    fileName: str

    @property
    def binding(self) -> str:
        enumBindings = "\n".join(
            f'    .value("{value}", {self.name}::{value})' for value in self.values
        )

        return f"""#include <gp_XY.hxx>
#include <gp_XYZ.hxx>
#include <{self.fileName}>
{referenceTypeTemplateDefs}
EMSCRIPTEN_BINDINGS({self.name}) {{
  enum_<{self.name}>("{self.name}")
{enumBindings};
}}"""

    def process(self):
        if not self.fileName:
            return

        basePath = f"{LIBRARY_BASE_PATH}/{os.path.basename(self.fileName)}"
        path = f"{basePath}/{self.name}.cpp"

        if not os.path.exists(path):
            os.makedirs(basePath, exist_ok=True)

            with open(path, "w") as f:
                f.write(self.binding)


@typechecked
def processChild(cursor: cindex.Cursor):
    locations = set()
    templateTypes = []

    name = cursor.spelling

    locations.add(cursor.location.file.name)

    if cursor.kind == cindex.CursorKind.TYPEDEF_DECL:
        type = cursor.underlying_typedef_type

        if (
            type.kind == cindex.TypeKind.ELABORATED
            or type.kind == cindex.TypeKind.UNEXPOSED
        ):
            children = cursor.get_children()

            templateRefs = list(
                filter(
                    lambda x: x.kind == cindex.CursorKind.TEMPLATE_REF,
                    children,
                )
            )

            if len(templateRefs) == 1:
                templateRef = templateRefs[0]

                templateDecl = templateRef.get_definition()
                templateTypes = [
                    cursor.type.get_template_argument_type(index)
                    for index in range(cursor.type.get_num_template_arguments())
                ]

                cursor = templateDecl

    if not cursor or not cursor.location.file:
        return None

    fileName = cursor.location.file.name

    if cursor.kind == cindex.CursorKind.ENUM_DECL:
        if cursor.is_anonymous():
            raise SkipException(f"Skip {fileName} because of anonymous enum")

        enumValues = []
        locations = set([fileName])

        for child in cursor.get_children():
            if child.kind != cindex.CursorKind.ENUM_CONSTANT_DECL:
                continue

            if child.location.file:
                locations.add(child.get_definition().location.file.name)

            enumValues.append(child.spelling)

        theEnum = C_Enum(name, enumValues, fileName)
        theEnum.process()

        return theEnum

    if (
        cursor.kind == cindex.CursorKind.CLASS_DECL
        or cursor.kind == cindex.CursorKind.CLASS_TEMPLATE
    ):
        if len(templateTypes) > 1:
            raise SkipException(f"Skip {name} because of multiple template types")

        methods, constructors = getPublicMembers(cursor, templateTypes)

        base = None

        for child in cursor.get_children():
            if child.kind == cindex.CursorKind.CXX_BASE_SPECIFIER:
                base = child.type.get_canonical().get_declaration()

        if base and base.location.file:
                locations.add(base.location.file.name)

        if not cursor or not cursor.location.file:
            return None

        fileName = cursor.location.file.name

        theClass = C_Class(
            name=name,
            base=base.spelling if base else None,
            methods=methods, 
            constructors=constructors, 
            fileName=fileName,
            _locations=locations
        )

        theClass.process()

        return theClass
    
    return None


@typechecked
def getPublicMembers(
    class_cursor: cindex.Cursor,
    templateTypes: list[cindex.Type] = [],
) -> tuple[list[C_Method], list[C_Constructor]]:
    """
    주어진 클래스 커서에 대해 public 메서드와 생성자 목록을 반환합니다.
    """
    methods: list[C_Method] = []
    ctors: list[C_Constructor] = []

    for child in class_cursor.get_children():
        if not is_public(child):
            continue

        if child.kind == cindex.CursorKind.CXX_METHOD:
            method = child

            name = method.spelling

            raw_args = [arg for arg in method.get_arguments()]

            if any(map(lambda x: not is_public(x), raw_args)):
                continue
            if not is_public(method.result_type):
                continue

            if method.spelling.startswith("operator"):
                continue

            isStatic = method.is_static_method()

            args = [
                C_Argument(arg.spelling, C_Type.fromCursor(arg, templateTypes))
                for arg in raw_args
            ]

            returnType = C_Type.fromCursorType(method.result_type, templateTypes)

            if method.spelling == 'GetNumberOfIntervals':
                print(returnType.spelling)

            methods.append(
                C_Method(name, isStatic, args, C_ReturnType(returnType), method.is_const_method())
            )
        elif child.kind == cindex.CursorKind.CONSTRUCTOR:
            constructor = child

            raw_args = [arg for arg in constructor.get_arguments()]

            if any(map(lambda x: not is_public(x), raw_args)):
                continue

            args = [
                C_Argument(arg.spelling, C_Type.fromCursor(arg, templateTypes))
                for arg in raw_args
            ]

            ctors.append(C_Constructor(constructor.spelling, args))

    return methods, ctors


@typechecked
def process(customCode: str):
    cindex.Config.set_library_file("/usr/lib/x86_64-linux-gnu/libclang-20.so.1")
    index = cindex.Index.create()

    print("Index created")

    header_content = OCCT_INCLUDE_STATEMENTS + "\n" + customCode

    console.print("Writing header file...")

    # 임시 헤더 파일 생성
    with open(HEADER_PATH, "w") as f:
        f.write(header_content)

    translationUnit = index.parse(
        HEADER_PATH,
        ["-x", "c++", "-D__EMSCRIPTEN__"] + includePathArgs,
    )

    results = []

    for cursor in translationUnit.cursor.get_children():
        definition = cursor.get_definition()

        if definition and definition != cursor:
            continue

        if not definition:
            continue

        if not definition.location.file:
            continue

        if not definition.location.file.name.startswith(OCCT_SRC_PATH):
            continue

        if not filterPackages(definition.location.file.name.split("/")[-2]):
            continue

        if not is_public(cursor):
            continue

        try:
            results.append(processChild(cursor))
        except SkipException as e:
            # console.print(e)
            continue

    print(f"Results: {len(list(filter(lambda x: x, results)))}")


@typechecked
def generateCustomCodeBindings(customCode: str):
    mkdirp(LIBRARY_BASE_PATH)

    process(customCode)


if __name__ == "__main__":
    rmrf(LIBRARY_BASE_PATH)
    mkdirp(LIBRARY_BASE_PATH)

    process("")
