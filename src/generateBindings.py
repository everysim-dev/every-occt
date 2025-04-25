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
    templateTypes: dict[str, str] = {},
) -> str:
    for key, value in templateTypes.items():
        typeName = f" {typeName} ".replace(f" {key} ", f" {value} ")
        typeName = re.sub(f"<{key}>", f"<{value}>", typeName)
        typeName = re.sub(fr",(\s?){key},", lambda m: f",{m.group(1)}{value},", typeName)
        typeName = re.sub(fr",(\s?){key}>", lambda m: f",{m.group(1)}{value}>", typeName)
        typeName = re.sub(f"<{key},", f"<{value},", typeName)

    return typeName.strip()


@typechecked
def get_qualified_type(cursorType: cindex.Type, templateTypes: dict[str, str] = {}, replaces: dict[str, str] = {}):
    pointee = cursorType.get_pointee()
    pointee_decl = pointee.get_declaration()

    names = []
    locations = set()

    if pointee_decl.kind == cindex.CursorKind.NO_DECL_FOUND:
        pointee_decl = cursorType.get_declaration()

    decl = pointee_decl.semantic_parent

    if pointee_decl.location.file:
        locations.add(pointee_decl.location.file.name)

    isNeedTemplate = (
        pointee_decl.type.kind
        in [
            cindex.TypeKind.UNEXPOSED,
            cindex.TypeKind.ELABORATED,
            cindex.TypeKind.INVALID,
        ]
        and templateTypes
    )

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

    result = cursorType.spelling

    prefix = "::".join(reversed(names))
    if prefix not in result:
        result = result.replace(
            pointee_decl.spelling, f"{prefix}::{pointee_decl.spelling}"
        )

    result = applyTemplate(result, templateTypes) if isNeedTemplate else result

    for key, value in replaces.items():
        result = result.replace(key, value)

    return result, locations


def getIsPrivateCopyConstructor(cursor: cindex.Cursor | None) -> bool:
    if cursor:
        if cursor.kind in [
            cindex.CursorKind.CLASS_DECL,
            cindex.CursorKind.CLASS_TEMPLATE,
            cindex.CursorKind.STRUCT_DECL,
        ]:
            for child in cursor.get_children():
                if child.is_copy_constructor() and child.access_specifier != cindex.AccessSpecifier.PUBLIC:
                    return True
                
                if child.kind == cindex.CursorKind.FIELD_DECL:
                    field_type = child.type
                    field_type_decl = field_type.get_declaration()
                    if getIsPrivateCopyConstructor(field_type_decl):
                        return True

    return False
        
@dataclass
class C_Type:
    name: str
    locations: set[str]
    withWrapper: bool = False
    isPointer: bool = False
    isVoid: bool = False
    isCString: bool = False
    isConst: bool = False
    isPrivateCopyConstructor: bool = False

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
            cindex.TypeKind.BOOL,
            cindex.TypeKind.CHAR_U,
            cindex.TypeKind.UCHAR,
            cindex.TypeKind.CHAR16,
            cindex.TypeKind.CHAR32,
            cindex.TypeKind.USHORT,
            cindex.TypeKind.UINT,
            cindex.TypeKind.ULONG,
            cindex.TypeKind.ULONGLONG,
            cindex.TypeKind.SHORT,
            cindex.TypeKind.INT,
            cindex.TypeKind.LONG,
            cindex.TypeKind.LONGLONG,
            cindex.TypeKind.FLOAT,
            cindex.TypeKind.DOUBLE,
            cindex.TypeKind.LONGDOUBLE,
        }:
            return True
        return False

    @classmethod
    def fromCursor(
        cls, cursor: cindex.Cursor, templateTypes: dict[str, str], replaces: dict[str, str]
    ) -> "C_Type":
        return cls.fromCursorType(cursor.type, templateTypes, replaces)

    @classmethod
    def fromCursorType(
        cls, cursorType: cindex.Type, templateTypes: dict[str, str], replaces: dict[str, str]
    ) -> "C_Type":
        name, locations = get_qualified_type(cursorType, templateTypes, replaces)

        decl = cursorType.get_pointee().get_declaration()
        if decl.kind == cindex.CursorKind.NO_DECL_FOUND:
            decl = cursorType.get_declaration()
        if decl.kind == cindex.CursorKind.TYPEDEF_DECL:
            decl = decl.get_definition()

        isPrivateCopyConstructor = getIsPrivateCopyConstructor(decl)

        return cls(
            name=name,
            locations=locations,
            withWrapper=cls.needsWrapper(cursorType),
            isPointer=cursorType.kind == cindex.TypeKind.POINTER,
            isPrivateCopyConstructor=isPrivateCopyConstructor,
            isVoid=cursorType.kind == cindex.TypeKind.VOID,
        )


@dataclass
class C_ReturnType:
    type: C_Type

    @property
    def spelling(self) -> str:

        # 참조 반환 타입이 private 복사 생성자를 가지면 포인터로 변환
        if self.type.isPrivateCopyConstructor:
            name = self.type.name.replace("&", "*").replace("const ", "")

            if 'const' not in name:
                name = "const " + name

            return name

        return self.type.spelling

    @property
    def withWrapper(self) -> bool:
        return self.type.withWrapper or self.type.isPrivateCopyConstructor

    @property
    def locations(self) -> set[str]:
        return self.type.locations

    @property
    def innerBinding(self):
        if self.type.isVoid:
            return "      "

        constBinding = "const " if self.type.isConst else ""
        pointerBinding = " &" if self.type.isPointer else ""
        rightPointerBinding = "&" if self.type.isPrivateCopyConstructor else ""

        return f"      {constBinding}auto{pointerBinding} ret = {rightPointerBinding}"

    @property
    def finalBinding(self):
        if self.type.isVoid:
            return f""
        if not self.type.withWrapper:
            return f"\n      return ret;"
        if self.type.isPointer:
            return f"\n      return ret == nullptr ? emscripten::val::null() : emscripten::val(static_cast<{self.type.spelling}>(ret));"
        
        return f"\n      return emscripten::val(ret);"


@dataclass
class C_Argument:
    name: str
    type: C_Type

    @property
    def locations(self):
        return self.type.locations

    @property
    def getBinding(self):
        return f"      auto ref_{self.name} = getReferenceValue<{self.type.name.replace(' &', '')}>({self.name});"

    @property
    def updateBinding(self):
        return f"      updateReferenceValue<{self.type.name.replace(' &', '')}>({self.name}, ref_{self.name});"

    def process(self, withName: bool = False, withType: bool = False, withRef: bool = False):
        prefix = ""

        if withRef and self.type.withWrapper:
            prefix = "ref_"

        if withType and withName:
            return f"{self.type.spelling} {prefix}{self.name}"
        elif withType:
            return self.type.spelling
        elif withName:
            return f"{prefix}{self.name}"
        raise ValueError("Either withName or withType must be True")


@dataclass
class C_Method:
    name: str
    suffix: str
    isStatic: bool
    args: list[C_Argument]
    returnType: C_ReturnType
    isConst: bool

    @property
    def withWrapper(self) -> bool:
        return (
            any(arg.type.withWrapper for arg in self.args)
            or self.returnType.withWrapper
        )

    @property
    def locations(self) -> set[str]:
        return {
            loc for arg in self.args for loc in arg.locations
        } | self.returnType.locations

    def processInner(self, className: str):
        thatType = C_Type(name=f"{className}&", locations=set(),isConst=True, withWrapper=False)
        thatArg = C_Argument(
            name="that", type=thatType
        )

        args = self.args.copy()

        withThat = self.withWrapper and not self.isStatic

        if withThat:
            args.insert(0, thatArg)

        argNamesBinding = ", ".join([arg.process(withName=True, withRef=True) for arg in (args[1:] if withThat else args)])
        argTypesBinding = ", ".join([arg.process(withType=True) for arg in args])
        argsBinding = ", ".join(
            [arg.process(withName=True, withType=True) for arg in args]
        )
        signatureBinding = f"{self.returnType.spelling}({argTypesBinding})"

        if not self.withWrapper:
            constBinding = " const" if self.isConst else ""
            classBinding = "" if self.isStatic else f", {className}"

            return f"select_overload<{signatureBinding}{constBinding}{classBinding}>(&{className}::{self.name})"

        argGetBindings = "\n".join(
            [arg.getBinding for arg in args if arg.type.withWrapper]
        )
        argUpdateBindings = "\n".join(
            [arg.updateBinding for arg in args if arg.type.withWrapper]
        )

        prefixBinding = f"{className}::" if self.isStatic else f"that."

        return f"""+[]({argsBinding}) -> {self.returnType.spelling} {{
{argGetBindings}
{self.returnType.innerBinding}{prefixBinding}{self.name}({argNamesBinding});
{argUpdateBindings}{self.returnType.finalBinding}
    }}""".replace("\n\n", "\n")

    def process(self, className: str):
        functionBinding = "class_function" if self.isStatic else "function"

        return f"""
    .{functionBinding}("{self.name}{self.suffix}", {self.processInner(className)}, allow_raw_pointers())"""


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
    isAbstract: bool
    isPrivateDestructor: bool
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
                *(location for location in self.locations if location == '/tmp/myMain.h' or (location.startswith(OCCT_SRC_PATH) and location.endswith(".hxx"))),
            ]
        ]
        if 'myMain.h' in headers:
            print(headers)

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
        constructorBindings = ""
        destructorBindings = ""

        if self.isPrivateDestructor:
            destructorBindings = f"""
namespace emscripten {{ namespace internal {{ template<> void raw_destructor<{self.name}>({self.name}* ptr) {{ /* do nothing */ }} }} }}
"""

        if not self.isAbstract:
            constructorBindings = "\n" + "".join(
                constructor.process(self.name, index)
                for index, constructor in enumerate(self.constructors)
            )
        baseBinding = f", base<{self.base}>" if self.base else ""

        return f"""{self.includes}
{referenceTypeTemplateDefs}
        
EMSCRIPTEN_BINDINGS({self.name}) {{
  class_<{self.name}{baseBinding}>("{self.name}"){methodBindings};{constructorBindings}
}}
{destructorBindings}
"""

    def process(self):
        if not self.fileName:
            return

        basePath = f"{LIBRARY_BASE_PATH}/{self.fileName.replace(OCCT_SRC_PATH, '').replace('/tmp', '')}"
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

        basePath = f"{LIBRARY_BASE_PATH}/{self.fileName.replace(OCCT_SRC_PATH, '')}"
        path = f"{basePath}/{self.name}.cpp"

        if not os.path.exists(path):
            os.makedirs(basePath, exist_ok=True)

            with open(path, "w") as f:
                f.write(self.binding)


LITERAL_TYPES = [
    cindex.CursorKind.INTEGER_LITERAL,
    cindex.CursorKind.FLOATING_LITERAL,
    cindex.CursorKind.STRING_LITERAL,
    cindex.CursorKind.CHARACTER_LITERAL
]

@typechecked
def processChild(cursor: cindex.Cursor):
    locations = set()
    templateTypes = {}

    name = cursor.spelling

    locations.add(cursor.location.file.name)

    fileName = cursor.get_definition().location.file.name

    if 'BitByBitDev' in name:
        print('fooooooo', name, cursor.kind, cursor.spelling, fileName)

    if cursor.kind == cindex.CursorKind.TYPEDEF_DECL:
        type = cursor.underlying_typedef_type

        if (
            type.kind == cindex.TypeKind.ELABORATED
            or type.kind == cindex.TypeKind.UNEXPOSED
        ):
            children = list(cursor.get_children())

            templateRefs = list(
                filter(
                    lambda x: x.kind == cindex.CursorKind.TEMPLATE_REF,
                    children,
                )
            )

            if len(templateRefs) == 1:
                templateRef = templateRefs[0]

                templateDecl = templateRef.get_definition()
                
                templateArgs = []
                templateArgTypes = []

                for child in templateDecl.get_children():
                    if child.kind in [
                        cindex.CursorKind.TEMPLATE_TYPE_PARAMETER,
                        cindex.CursorKind.TEMPLATE_NON_TYPE_PARAMETER,
                        cindex.CursorKind.TEMPLATE_TEMPLATE_PARAMETER
                    ]:
                        templateArgTypes.append(child.spelling)

                for child in cursor.get_children():
                    if child.kind in [cindex.CursorKind.TEMPLATE_REF, cindex.CursorKind.NAMESPACE_REF]:
                        continue

                    if name == 'Select3D_BVHBuilder3d':
                        print(name, child.kind, child.spelling)

                    if child.kind in LITERAL_TYPES:
                        templateArgs += [token.spelling for token in child.get_tokens()]
                    else:
                        templateArgs.append(child.type.spelling or child.spelling)

                    if len(templateArgs) == len(templateArgTypes):
                        break

                # if name == "BOPTools_Box2dTreeSelector":
                #     print(cursor.type.get_num_template_arguments(), templateRef.type.get_num_template_arguments(), templateDecl.type.get_num_template_arguments())
                #     print(cursor.spelling, cursor.kind, templateRef.spelling, templateRef.kind, templateDecl.spelling, templateDecl.kind)
                templateArgs = [
                    cursor.type.get_template_argument_type(index).spelling or templateArgs[index]
                    for index in range(cursor.type.get_num_template_arguments())
                ]

                templateTypes = dict(zip(templateArgTypes, templateArgs))

                if name == 'Select3D_BVHBuilder3d':
                    print(name, templateArgs, templateArgTypes, templateTypes)

                cursor = templateDecl

    if not cursor or not cursor.location.file:
        return None
    
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
    
    replaces = {
        cursor.spelling: name
    }

    if (
        cursor.kind == cindex.CursorKind.CLASS_DECL
        or cursor.kind == cindex.CursorKind.CLASS_TEMPLATE
    ):
        methods, constructors = getPublicMembers(cursor, templateTypes, replaces)

        base = None
        isPrivateDestructor = False

        for child in cursor.get_children():
            if child.kind == cindex.CursorKind.DESTRUCTOR:
                if child.access_specifier != cindex.AccessSpecifier.PUBLIC:
                    isPrivateDestructor = True

            if child.kind == cindex.CursorKind.CXX_BASE_SPECIFIER:
                base = child
                
        if base and base.location.file:
            locations.add(base.location.file.name)

        if not cursor or not cursor.location.file:
            return None

        locations.add(cursor.location.file.name)

        theClass = C_Class(
            name=name,
            base=applyTemplate(base.spelling, templateTypes) if base else None,
            methods=methods,
            constructors=constructors,
            isAbstract=cursor.is_abstract_record(),
            fileName=fileName,
            isPrivateDestructor=isPrivateDestructor,
            _locations=locations,
        )

        theClass.process()

        return theClass

    return None


@typechecked
def getPublicMembers(
    class_cursor: cindex.Cursor,
    templateTypes: dict[str, str],
    replaces: dict[str, str]
) -> tuple[list[C_Method], list[C_Constructor]]:
    """
    주어진 클래스 커서에 대해 public 메서드와 생성자 목록을 반환합니다.
    """
    methods: list[C_Method] = []
    ctors: list[C_Constructor] = []

    memo = {}

    for child in class_cursor.get_children():
        if not is_public(child):
            continue

        if child.kind == cindex.CursorKind.CXX_METHOD:
            method = child

            if method.is_pure_virtual_method():
                continue

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
                C_Argument(arg.spelling if arg.spelling else f"arg{idx}", C_Type.fromCursor(arg, templateTypes, replaces))
                for idx, arg in enumerate(raw_args)
            ]

            returnType = C_Type.fromCursorType(method.result_type, templateTypes, replaces)

            if name not in memo:
                memo[name] = 0
            else:
                memo[name] += 1

            suffix = f"_{memo[name]}" if memo[name] > 0 else ""

            methods.append(
                C_Method(
                    name=name,
                    suffix=suffix,
                    isStatic=isStatic,
                    args=args,
                    returnType=C_ReturnType(returnType),
                    isConst=method.is_const_method(),
                )
            )
        elif child.kind == cindex.CursorKind.CONSTRUCTOR:
            constructor = child

            raw_args = [arg for arg in constructor.get_arguments()]

            if any(map(lambda x: not is_public(x), raw_args)):
                continue

            args = [
                C_Argument(arg.spelling, C_Type.fromCursor(arg, templateTypes, replaces))
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

        if definition.location.file.name != "/tmp/myMain.h" and not definition.location.file.name.startswith(OCCT_SRC_PATH):
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
