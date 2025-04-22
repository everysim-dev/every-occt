from pygccxml import declarations

from wasmGenerator.Common import (
    SkipException,
    getPublicMemberFunctions,
    getMethodOverloadPostfix,
    unwrapType,
)
from Common import console
from typing import Union, Optional, Dict
from typing import Optional
from typeguard import typechecked
import re


def merge(sep: str, *strings: str) -> str:
    return sep.join(strings)


def pick(condition: bool, strTrue: str, strFalse: str):
    return strTrue if condition else strFalse


def pickWrap(condition: bool, wrapStart: list[str], center: str, wrapEnd: list[str]):
    return (
        (wrapStart[0] if condition else wrapStart[1])
        + center
        + (wrapEnd[0] if condition else wrapEnd[1])
    )


def indent(level: int):
    return " " * level * 2


builtInTypes = [  # according to https://en.cppreference.com/w/cpp/language/types
    # Integer types
    "int",
    "short",
    "short int",
    "signed short",
    "signed short int",
    "unsigned short",
    "unsigned short int",
    "signed",
    "signed int",
    "unsigned",
    "unsigned int",
    "long",
    "long int",
    "signed long",
    "signed long int",
    "unsigned long",
    "unsigned long int",
    "long long",
    "long long int",
    "signed long long",
    "signed long long int",
    "unsigned long long",
    "unsigned long long int",
    # Boolean type
    "bool",
    # Character types
    "char",
    "signed char",
    "unsigned char",
    "wchar_t",
    "char16_t",
    "char32_t",
    "char8_t",
    # Floating point types
    "float",
    "double",
    "long double",
]

special_template_types = [
    "NCollection_LocalArray",
    "NCollection_Sequence",
    "NCollection_List",
    "NCollection_Vector",
    "NCollection_Array1",
    "NCollection_Array2",
    "TColStd_Array1OfReal",
]


def isCString(type: Union[declarations.declaration_t]):
    baseType = unwrapType(type, withBase=False)

    if isinstance(baseType, declarations.reference_t):
        return False
    
    if isinstance(baseType, declarations.const_t):
        baseType = baseType.base

    if isinstance(baseType, declarations.pointer_t):
        baseType = baseType.base
    
    # string이 아니고 char 타입이면 False 반환
    if isinstance(baseType, declarations.char_t):
        return False

    return isinstance(unwrapType(type), declarations.char_t)

def get_canonical(decl: declarations.declaration_t) -> declarations.declaration_t:
    """pygccxml declaration의 canonical type 접근 함수"""
    result = decl
    while hasattr(result, "declaration") and result.declaration is not result:
        result = result.declaration
    return result


@typechecked
def getClassName(decl: declarations.class_t) -> str:
    """
    pygccxml class_t로부터 네임스페이스 포함 클래스 이름 반환
    """
    if hasattr(decl, "decl_string") and decl.decl_string:
        return decl.decl_string
    if hasattr(decl, "name"):
        return decl.name
    return str(decl)


def make_bindings_identifier(name: str) -> str:
    # <, >, ,, 공백 등 템플릿 관련 문자를 _로 치환
    return re.sub(r"[<>,\s]", "_", name).replace("__", "_").strip("_")


def get_fully_qualified_type_name_pygccxml(
    type_obj: Union[declarations.type_t, declarations.declaration_t],
) -> str:
    """
    pygccxml type_t 또는 declaration_t 로부터 네임스페이스 포함 완전 수식 타입명 생성
    """
    # typedef_t인 경우 underlying_type 재귀
    if hasattr(type_obj, "declaration"):
        type_obj = type_obj.declaration

    if hasattr(type_obj, "decl_type"):
        return str(type_obj.decl_type)

    # declaration_t인 경우
    if hasattr(type_obj, "decl_string"):
        return type_obj.decl_string

    # fallback
    return str(type_obj)


def getClassTypeName(
    theClass: declarations.class_t,
    templateDecl: Optional[declarations.typedef_t] = None,
) -> str:
    return templateDecl.name if templateDecl is not None else theClass.name


def safe_type_name(
    type_obj: Union[declarations.type_t, declarations.declaration_t, None],
) -> str:
    if type_obj is None:
        return "void"

    try:
        return get_fully_qualified_type_name_pygccxml(type_obj)
    except AttributeError:
        return str(type_obj)


class Bindings:
    pass


class EmbindBindings(Bindings):
    def processClassInner(
        self,
        theClass: declarations.class_t,
        templateDecl: Optional[declarations.typedef_t] = None,
        templateArgs: Optional[
            Dict[str, Union[declarations.type_t, declarations.declaration_t]]
        ] = None,
        className: str = None,
    ) -> str:
        output = ""

        if not className:
            className = getClassTypeName(theClass, templateDecl)

        for method in getPublicMemberFunctions(theClass):
            method: declarations.member_function_t

            try:
                output += self.processMethodOrProperty(
                    theClass, method, className=className
                )
            except SkipException as e:
                console.print(str(e))

        output += self.processFinalizeClass()

        if theClass.is_abstract:
            return output
        
        # 템플릿 타입 컨스트럭처 생성 X
        if theClass.name != theClass.partial_name and not className:
            return output
        
        output += self.processConstructors(theClass, className)

        return output

    def processClass(
        self,
        theClass: declarations.class_t,
        templateDecl=None,
        templateArgs=None,
        className=None,
    ):
        output = ""

        if className is None:
            className = getClassName(theClass)

        if className.startswith("::"):
            className = className[2:]

        tokens = className.split("::")
        lastToken = tokens[-1]

        base = None

        for b in theClass.bases:
            b: declarations.hierarchy_info_t 

            if b.related_class:
                if declarations.is_struct(b.related_class):
                    continue
                base = b
                break

        classBinding = className

        if base:
            baseBinding = base.related_class.decl_string
            classBinding = f"{classBinding}, base<{baseBinding}>"

        bindings_name = make_bindings_identifier(lastToken)
        output += (
            f"EMSCRIPTEN_BINDINGS({bindings_name}) {{\n"
            + f'  class_<{classBinding}>("{lastToken}")\n'
            + self.processClassInner(
                theClass, templateDecl, templateArgs, className=className
            )
            + "\n  register_optional<Message_ProgressRange>();\n"
            + "}\n\n"
        )

        decls = list(theClass.declarations)

        # Epilog
        nonPublicDestructor = any(
            isinstance(x, declarations.destructor_t) and x.access_type != "public"
            for x in decls
        )
        placementDelete = (
            next(
                (
                    x
                    for x in decls
                    if x.name == "operator delete" and len(list(x.arguments)) == 2
                ),
                None,
            )
            is not None
        )
        if nonPublicDestructor or placementDelete:
            output += f"namespace emscripten {{ namespace internal {{ template<> void raw_destructor<{className}>({className}* ptr) {{ /* do nothing */ }} }} }}\n"
        return output

    def processFinalizeClass(self):
        return "  ;\n"

    @typechecked
    def processConstructor(self, constructor: declarations.constructor_t, className: str, index: int) -> str:
        @typechecked
        def argToString(arg: declarations.argument_t, withType = True, withName: bool = False, onlyName: bool = False):
            result = ""
            type = arg.decl_type

            if onlyName:
                if isCString(type):
                    if isinstance(type, declarations.const_t):
                        return f"{arg.name}.isNull() ? nullptr : strdup({arg.name}.as<std::string>().c_str())"
                    else:
                        return f"{arg.name}.isNull() ? nullptr : {arg.name}.as<std::string>().c_str()"

            if withType:
                result = "emscripten::val" if isCString(type) else f"{arg.decl_type.decl_string}"

            if withName:
                result = f"{result} {arg.name}" if result else arg.name

            if result.startswith("::"):
                result = result[2:]

            return result

        args = list(constructor.arguments)
        
        for arg in args:
            arg: declarations.argument_t
            argType = unwrapType(arg)

            # emcc 컴파일 시 직접 생성해보기 때문에 public 하지 않을 경우 오류 발생
            if hasattr(argType, 'parent'):
                if isinstance(argType.parent, declarations.class_t):
                    if argType not in argType.parent.public_members:
                        return ""

        argTypesBindings = ", ".join([argToString(arg) for arg in args])
        argNameBindings = ", ".join([argToString(arg, withType=False, withName=True, onlyName=True) for arg in args])
        argBindings = ", ".join([argToString(arg, withName=True) for arg in args])

        name = f"{make_bindings_identifier(className)}_{index + 1}"

        output = ""
        output += f"  struct {name}: public {className} {{\n"
        output += f"    {name}({argBindings}): {className}({argNameBindings}) {{}}\n"
        output += "  };\n"
        output += f'  class_<{name}, base<{className}>>("{name}")\n'
        output += f"    .constructor<{argTypesBindings}>();\n"

        return output


    @typechecked
    def processConstructors(self, theClass: declarations.class_t, className: str) -> str:
        output = ""

        if declarations.is_union(theClass):
            return output

        constructors = []

        if hasattr(theClass, "constructors"):
            constructors = theClass.constructors(allow_empty=True)

        publicConstructors = [
            constructor
            for constructor in constructors
            if constructor.access_type == "public" and constructor.parent is theClass
        ]

        for index in range(len(publicConstructors)):
            constructor: declarations.constructor_t = publicConstructors[index]

            output += self.processConstructor(constructor, className, index)

        return output
    

    @typechecked
    def processMethodOrProperty(
        self,
        theClass: declarations.class_t,
        method: declarations.member_function_t,
        className: str = None,
    ) -> str:
        output = ""

        # if method.has_inline:
        #     return ""

        # 존재하지 않는 메소드임
        if method.name == 'ClearTangents':
            return ""

        if not className:
            className = getClassName(theClass)

        [overloadPostfix, numOverloads] = getMethodOverloadPostfix(theClass, method)

        for type in method.argument_types:
            if isinstance(type, declarations.reference_t):
                type = type.base

            if any(
                term in unwrapType(type).decl_string
                for term in ["stringstream","AVStream", "ostream", "istream", "fstream", "ssteam"]
            ):
                return ""
            
        @typechecked
        def needsWrapper(
            type: Union[
                declarations.type_t, declarations.declaration_t, declarations.argument_t
            ],
        ):
            unwrapedType = unwrapType(type, withBase=False)
            baseType = unwrapType(type)

            # LValueReference가 아니면 래핑 필요 없음
            if not isinstance(unwrapedType, declarations.reference_t):
                return False
            else:
                unwrapedType = unwrapType(unwrapedType.base, withBase=False)

            # 상수 참조는 래핑 필요 없음 - 데이터 수정 불가
            if isinstance(unwrapedType, declarations.const_t):
                return False

            if isinstance(unwrapedType, declarations.pointer_t):
                return True

            if baseType and isinstance(baseType, declarations.enumeration_t):
                return True

            # 기본 타입(int, float 등)은 래핑 필요
            # 이는 값 변경이 포인터를 통해 전달되어야 하기 때문
            if isinstance(baseType, declarations.fundamental_t):
                return True

            return False


        args = list(method.arguments)
        if method.name == "Center":
            for arg in args:
                arg: declarations.argument_t

                print(method.name, arg.name, arg.decl_type)

        for arg in args:
            arg: declarations.argument_t
            argType = unwrapType(arg)

            # emcc 컴파일 시 직접 생성해보기 때문에 public 하지 않을 경우 오류 발생
            if hasattr(argType, 'parent'):
                if isinstance(argType.parent, declarations.class_t):
                    if argType not in argType.parent.public_members:
                        return ""
                    
        if hasattr(method.return_type, "parent"):
            returnType = unwrapType(method.return_type.parent)
            if isinstance(returnType, declarations.class_t):
                if returnType not in returnType.parent.public_members:
                    return ""

        argsNeedingWrapper = list(map(lambda arg: needsWrapper(arg), args))
        argsNeedingCharWrapper = list(map(lambda arg: isCString(arg), args))
        returnNeedsWrapper = needsWrapper(method.return_type)

        # TODO optional_override 사용하도록 수정해야 할지 알아보기
        if (
            any(argsNeedingWrapper) or
            any(argsNeedingCharWrapper) or
            returnNeedsWrapper
        ):
            def replaceTemplateArgs(x: tuple):
                argIndex = x[0]
                arg = args[argIndex]

                return str(arg.decl_type)

            def getArgName(x):
                argIndex = x[0]
                arg = args[argIndex]

                return arg.name if arg.name else f"argNo{argIndex}"

            def getArgTypeName(type: declarations.argument_t):
                return type.decl_type

            wrappedParamTypes = merge(
                ", ",
                *map(
                    lambda x: pick(x[1] or isCString(args[x[0]]), "emscripten::val", replaceTemplateArgs(x)),
                    enumerate(argsNeedingWrapper),
                ),
            )
            wrappedParamTypesAndNames = merge(
                ", ",
                *map(
                    lambda x: pick(
                        x[1] or isCString(args[x[0]]),
                        f"emscripten::val {getArgName(x)}",
                        f"{replaceTemplateArgs(x)} {getArgName(x)}",
                    ),
                    enumerate(argsNeedingWrapper),
                ),
            )

            def generateGetReferenceValue(x):
                argType = getArgTypeName(args[x[0]])

                if hasattr(argType, "base"):
                    argType = argType.base

                if x[1] and not isCString(args[x[0]]):
                    return merge(
                        "",
                        indent(4),
                        "auto ref_",
                        pick(
                            not args[x[0]].name == "",
                            args[x[0]].name,
                            f"argNo{str(x[0])}",
                        ),
                        f" = getReferenceValue<{argType}>({getArgName(x)});\n",
                    )
                else:
                    return ""

            def generateUpdateReferenceValue(x):
                argType = getArgTypeName(args[x[0]])

                if hasattr(argType, "base"):
                    argType = argType.base

                if x[1] and not isCString(args[x[0]]):
                    return f"{indent(4)}updateReferenceValue<{argType}>({getArgName(x)}, ref_{getArgName(x)});\n"
                else:
                    return ""

            def generateInvocationArgs(x):
                arg: declarations.argument_t = args[x[0]]

                if isCString(arg):
                    if isinstance(unwrapType(arg, withBase=False), declarations.const_t):
                        return f"{getArgName(x)}.isNull() ? nullptr : strdup({getArgName(x)}.as<std::string>().c_str())"
                    else:
                        return f"{getArgName(x)}.isNull() ? nullptr : {getArgName(x)}.as<std::string>().c_str()"

                if x[1]:
                    return f"ref_{getArgName(x)}"
                else:
                    return getArgName(x)

            return_type_obj = method.return_type

            resultTypeSpelling = pick(
                returnNeedsWrapper,
                "emscripten::val",
                safe_type_name(return_type_obj),
            )

            functionBindingHead = merge(
                "",
                "\n",
                indent(3),
                pickWrap(
                    not method.has_static,
                    [
                        f"std::function<{resultTypeSpelling}(",
                        f"(({resultTypeSpelling} (*)(",
                    ],
                    merge(
                        "",
                        pick(not method.has_static, f"{className}&", ""),
                        pick(
                            not method.has_static and len(args) > 0,
                            ", ",
                            "",
                        ),
                        wrappedParamTypes,
                    ),
                    [")>(", "))"],
                ),
                merge(
                    "",
                    "[](",
                    pick(not method.has_static, f"{className}& that", ""),
                    pick(not method.has_static and len(args) > 0, ", ", ""),
                    wrappedParamTypesAndNames,
                    ")",
                ),
                f" -> {resultTypeSpelling} {{\n",
                merge(
                    "",
                    *map(
                        lambda x: generateGetReferenceValue(x),
                        enumerate(argsNeedingWrapper),
                    ),
                ),
            )
            functionBindingBody = merge(
                "",
                indent(4),
                pick(
                    not method.return_type.decl_string == "void",
                    merge(
                        "",
                        pick(
                            not isCString(method.return_type)
                            and (
                                isinstance(method.return_type, declarations.const_t)
                                or isinstance(method.return_type, declarations.const_t)
                            ),
                            "const ",
                            "",
                        ),
                        "auto",
                        pick(
                            not isCString(method.return_type)
                            and isinstance(
                                method.return_type, declarations.reference_t
                            ),
                            "& ",
                            " ",
                        ),
                        "ret = ",
                    ),
                    "",
                ),
                merge(
                    "",
                    pick(
                        not method.has_static,
                        "that.",
                        f"{theClass.name}::",
                    ),
                    f'{method.name}({merge(", ", *map(lambda x: generateInvocationArgs(x), enumerate(argsNeedingWrapper)))})',
                ),
                ";\n",
                merge(
                    "",
                    *map(
                        lambda x: generateUpdateReferenceValue(x),
                        enumerate(argsNeedingWrapper),
                    ),
                ),
                # 반환부: const T& + 복사 생성자 private이면 &ret, 아니면 기존 로직
                (
                    pick(
                        method.return_type.decl_string == "void",
                        "",
                        pick(
                            returnNeedsWrapper,
                            pick(
                                isinstance(method.return_type, declarations.pointer_t),
                                merge(
                                    "",
                                    indent(4),
                                    "return ret == nullptr ? emscripten::val::null() : emscripten::val(static_cast<",
                                    pick(
                                        isCString(method.return_type),
                                        "std::string",
                                        method.return_type.decl_string,
                                    ),
                                    ">(ret));\n",
                                ),
                                f"{indent(4)}return emscripten::val(ret);\n",
                            ),
                            f"{indent(4)}return ret;\n",
                        ),
                    )
                ),
            )
            functionBinding = merge(
                "",
                functionBindingHead,
                functionBindingBody,
                f"{indent(3)}}}\n",
                f"{indent(2)})",
            )
        else:
            # TODO 추후 수정 필요
            if False and numOverloads == 1:
                functionBinding = f" &{className}::{method.name}"
            else:
                argumentBinding = merge(
                    ", ",
                    *map(
                        lambda arg: arg.decl_type.decl_string,
                        list(method.arguments),
                    ),
                )

                if "?unknown?" in argumentBinding:
                    return ""
                
                if "?unknown?" in method.return_type.decl_string:
                    return ""

                constBinding = pick(method.has_const, " const", "")
                classBinding = pick(not method.has_static, f", {className}", "")
                functionBinding = merge(
                    "",
                    f" select_overload<{method.return_type.decl_string}({argumentBinding}){constBinding}{classBinding}>",
                    f"(&{className}::{method.name})",
                )

        if method.has_static:
            functionCommand = "class_function"
        else:
            functionCommand = "function"

        output += f'{indent(2)}.{functionCommand}("{method.name}{overloadPostfix}",{functionBinding}, allow_raw_pointers())\n'
        if (
            isinstance(method, declarations.variable_t)
            and method.access_type == "public"
        ):
            if isinstance(method, declarations.array_t):
                console.print(
                    f"Cannot handle array properties, skipping {className}::{method.name}"
                )
            elif not (getattr(method, "base", None) is None):
                console.print(
                    f"Cannot handle pointer properties, skipping {className}::{method.name}"
                )
            else:
                output += f'{indent(2)}.property("{method.name}", &{className}::{method.name})\n'
        return output


    def processEnum(self, theEnum: declarations.enumeration_t) -> str:
        decl_string = theEnum.decl_string

        if decl_string.startswith("::"):
            decl_string = decl_string[2:]

        output = f"EMSCRIPTEN_BINDINGS({theEnum.name}) {{\n"

        enumChildren = theEnum.values
        prefix = f"{decl_string}::" if theEnum.name else ""
        bindingsOutput = f'  enum_<{decl_string}>("{theEnum.name}")\n'
        for enumChild in enumChildren:
            bindingsOutput += f'    .value("{enumChild[0]}", {prefix}{enumChild[0]})\n'
        bindingsOutput += "  ;\n"
        output += bindingsOutput
        output += "}\n\n"
        return output
