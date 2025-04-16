from pygccxml import declarations

from wasmGenerator.Common import (
    SkipException,
    getPublicMemberFunctions,
    isAbstractClass,
    getMethodOverloadPostfix,
    unwrapType,
)
from Common import console
from typing import Union, Optional, Dict
from typing import Optional
from typeguard import typechecked
from pygccxml import declarations
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


def isCString(type_obj: Union[declarations.declaration_t]):
    return isinstance(type_obj, declarations.pointer_t) and "char" in str(
        unwrapType(type_obj)
    )


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


def detect_template_type_simple(class_name):
    result = {
        "is_template_type": False,
        "template_pattern": None,
        "key_type": None,
        "value_type": None,
    }
    if (
        "NCollection_IndexedDataMap" in class_name
        and "<" in class_name
        and ">" in class_name
    ):
        result["is_template_type"] = True
        result["template_pattern"] = "IndexedDataMap"
        args_part = class_name[class_name.find("<") + 1 : class_name.rfind(">")]
        args = [arg.strip() for arg in args_part.split(",")]
        if len(args) >= 2:
            result["key_type"] = args[0]
            result["value_type"] = args[1]
    return result


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

        isAbstract = isAbstractClass(theClass)

        if not isAbstract:
            output += self.processSimpleConstructor(theClass)

        for method in getPublicMemberFunctions(theClass):
            method: declarations.member_function_t

            try:
                output += self.processMethodOrProperty(
                    theClass, method, className=className
                )
            except SkipException as e:
                console.print(str(e))
        output += self.processFinalizeClass()
        if not isAbstract:
            try:
                output += self.processOverloadedConstructors(
                    theClass, None, templateDecl, templateArgs, className=className
                )
            except SkipException as e:
                console.print(str(e))
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

        bindings_name = make_bindings_identifier(lastToken)
        output += (
            f"EMSCRIPTEN_BINDINGS({bindings_name}) {{\n"
            + f'  class_<{className}>("{lastToken}")\n'
            + self.processClassInner(
                theClass, templateDecl, templateArgs, className=className
            )
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

    def processSimpleConstructor(self, theClass: declarations.class_t) -> str:
        output = ""

        if theClass.name.startswith('NCollection_'):
            return output

        constructors = []

        if hasattr(theClass, "constructors"):
            constructors = theClass.constructors(allow_empty=True)

        publicConstructors = [
            constructor
            for constructor in constructors
            if constructor.access_type == "public"
        ]

        if len(publicConstructors) == 0:
            return ""

        if len(publicConstructors) != 1:
            return output

        standardConstructor = publicConstructors[0]

        def argTypeToString(arg: declarations.argument_t):
            result = f"{arg.decl_type.decl_string}"

            if result.startswith("::"):
                result = result[2:]

            return result

        argTypesBindings = ", ".join(
            list(
                map(
                    argTypeToString,
                    list(standardConstructor.arguments),
                )
            )
        )

        output += "    .constructor<" + argTypesBindings + ">()\n"
        return output

    @typechecked
    def processMethodOrProperty(
        self,
        theClass: declarations.class_t,
        method: declarations.member_function_t,
        className: str = None,
    ) -> str:
        output = ""

        if method.has_inline:
            return ""

        if not className:
            className = getClassName(theClass)

        [overloadPostfix, numOverloads] = getMethodOverloadPostfix(theClass, method)

        # 여러 함수 포인터 인자(static 함수) 바인딩: 제너럴 trampoline 활용
        funcptr_indices = []
        funcptr_types = []
        funcptr_tramp_templates = []
        for idx, arg in enumerate(method.arguments):
            t = arg.decl_type
            if isinstance(t, declarations.pointer_t) and isinstance(
                t.base, declarations.calldef_type_t
            ):
                funcptr_indices.append(idx)
                funcptr_types.append(t)
                tramp_args = [safe_type_name(p) for p in t.base.arguments_types]
                funcptr_tramp_templates.append(
                    f"GenericFunctionPointerTrampoline<int, {', '.join(tramp_args)}>"
                )
        has_funcptr_arg = len(funcptr_indices) > 0

        # TODO 완성 필요
        if has_funcptr_arg and method.has_static:
            func_name = method.name
            wrapper_func_name = f"{func_name}_js"
            # 인자 선언부 및 호출 인자 생성
            arg_decls = []
            call_args = []
            for i, arg in enumerate(method.arguments):
                t = arg.decl_type
                if i in funcptr_indices:
                    arg_decls.append(f"emscripten::val arg{i}")
                    tramp_idx = funcptr_indices.index(i)
                    call_args.append(
                        f"{funcptr_tramp_templates[tramp_idx]}::get(arg{i})"
                    )
                else:
                    arg_decls.append(f"{safe_type_name(t)} {arg.name}")
                    call_args.append(arg.name)
            arg_decl_str = ", ".join(arg_decls)
            call_arg_str = ", ".join(call_args)
            ret_type = safe_type_name(method.return_type)
            wrapper = (
                f"\nstatic {ret_type} {wrapper_func_name}({arg_decl_str}) {{\n"
                + f"    return {className}::{func_name}({call_arg_str});\n"
                + "}\n"
            )
            return output
            output = wrapper + output
            output += f'{indent(2)}.class_function("{func_name}{overloadPostfix}", &{wrapper_func_name}, allow_raw_pointers())\n'
            return output

        for type in method.argument_types:
            if isinstance(type, declarations.reference_t):
                type = type.base

            # print(unwrapType(type), unwrapType(type).__class__.__name__)

            # 스트림 타입 임시 비활성화
            # TODO: 스트림 타입을 처리할 수 있는 방법을 찾아야 함
            if any(
                term in unwrapType(type).decl_string
                for term in ["AVStream", "ostream", "istream", "fstream", "ssteam"]
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

        # const T& + 복사 생성자 private이면, 람다에서 T* 반환(나머지 래핑 로직은 그대로)
        def needsConstRefReturnWithPrivateCopyCtor():
            if not isinstance(method.return_type, declarations.reference_t):
                return False

            baseType = method.return_type.base

            if isinstance(baseType, declarations.declarated_t):
                baseType = unwrapType(baseType, withBase=False)

            if isinstance(baseType, declarations.const_t):
                baseType = unwrapType(baseType.base, withBase=False)

            if not isinstance(baseType, declarations.class_t):
                return False

            ctors = baseType.constructors(allow_empty=True)

            for ctor in ctors:
                ctor: declarations.constructor_t
                args = ctor.arguments

                if len(args) != 1:
                    continue

                if ctor.access_type != "private":
                    continue

                argType = args[0].decl_type

                if not isinstance(argType, declarations.reference_t):
                    continue

                argType = argType.base

                if not isinstance(argType, declarations.const_t):
                    continue

                argType = unwrapType(argType)

                if not isinstance(argType, declarations.class_t):
                    continue

                if argType.decl_string == baseType.decl_string:
                    return True

            return False

        args = list(method.arguments)
        argsNeedingWrapper = list(map(lambda arg: needsWrapper(arg), args))
        # TODO 추후 복구해야하는지 확인 필요
        returnNeedsWrapper = needsWrapper(method.return_type)

        # TODO optional_override 사용하도록 수정해야 할지 알아보기
        if (
            any(argsNeedingWrapper)
            or returnNeedsWrapper
            or needsConstRefReturnWithPrivateCopyCtor()
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
                    lambda x: pick(x[1], "emscripten::val", replaceTemplateArgs(x)),
                    enumerate(argsNeedingWrapper),
                ),
            )
            wrappedParamTypesAndNames = merge(
                ", ",
                *map(
                    lambda x: pick(
                        x[1],
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
                if x[1]:
                    arg_type = args[x[0]]
                    pointee_type = (
                        arg_type.base
                        if isinstance(arg_type, declarations.reference_t)
                        else None
                    )

                    if (
                        pointee_type
                        and pointee_type.declaration.name in builtInTypes
                        and not isinstance(pointee_type, declarations.const_t)
                    ):
                        return f"ref_{getArgName(x)}"

                    if pointee_type:
                        template_info = detect_template_type_simple(pointee_type.name)
                        if template_info["is_template_type"]:
                            return f"ref_{getArgName(x)}"

                    if not isCString(args[x[0]]):
                        return f"ref_{getArgName(x)}"
                    elif (
                        "const" not in args[x[0]].declaration.base.qualifiers
                        or "const" in args[x[0]].qualifiers
                    ):
                        return f"{getArgName(x)}.isNull() ? nullptr : strdup({getArgName(x)}.as<std::string>().c_str())"
                    else:
                        return f"{getArgName(x)}.isNull() ? nullptr : {getArgName(x)}.as<std::string>().c_str()"
                else:
                    return getArgName(x)

            return_type_obj = method.return_type

            # 반환 타입 결정: const T& + 복사 생성자 private이면 const T*, 아니면 기존 로직
            if needsConstRefReturnWithPrivateCopyCtor():
                # 람다 반환 타입은 const T*
                ret_type = method.return_type
                base_type = (
                    ret_type.base.base if hasattr(ret_type.base, "base") else None
                )
                resultTypeSpelling = (
                    f"const {base_type.decl_string}*"
                    if base_type and hasattr(base_type, "decl_string")
                    else "void*"
                )
            else:
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
                    f"{indent(4)}return const_cast<{safe_type_name(unwrapType(method.return_type))}*>(&ret);\n"
                    if needsConstRefReturnWithPrivateCopyCtor()
                    else pick(
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

    # TODO 리팩토링 필요
    # 템플릿 관련된 부분 pygccxml을 통해 해결 가능
    def processOverloadedConstructors(
        self,
        theClass: declarations.class_t,
        children=None,
        templateDecl=None,
        templateArgs=None,
        className: str = None,
    ):
        output = ""

        return output

        constructors = list(
            filter(
                lambda x: x.access_type == "public",
                theClass.constructors(),
            )
        )

        # 오버로딩할 생성자가 1개 이하면 처리 중단 (이미 processSimpleConstructor에서 처리했거나 오버로딩 불필요)
        if len(constructors) <= 1:
            return output

        constructorBindings = ""

        valid_constructors_for_binding = constructors

        # 바인딩 가능한 생성자가 1개 이하이고, 그 중 인자 없는 생성자가 있다면 오버로딩 불필요
        if len(valid_constructors_for_binding) <= 1 and any(
            len(list(c.arguments)) == 0 for c in valid_constructors_for_binding
        ):
            return output

        # 템플릿 타입 감지
        if not className:
            className = getClassName(theClass)
        template_info = detect_template_type_simple(className)

        # 생성자 인덱스 매핑 (일관된 이름 부여용)
        constructor_indices = {con: idx for idx, con in enumerate(constructors)}

        name = getClassTypeName(theClass, templateDecl)

        # 바인딩 가능한 생성자들에 대해 루프 실행
        for constructor in valid_constructors_for_binding:
            overload_index = constructor_indices.get(constructor, -1)
            if overload_index == -1:
                continue  # 혹시 모를 오류 방지

            overloadPostfix = "_" + str(overload_index + 1)

            processed_args_for_struct_def = []
            processed_arg_types_for_embind = []
            processed_arg_names_for_init = []

            constructor_args = list(constructor.arguments)

            param_info_list = []
            if template_info["is_template_type"]:
                param_info_list = detect_template_type_simple(
                    template_info, constructor_args
                )
                # console.print(f"DEBUG: 특수 처리 필요 매개변수: {len(param_info_list)}개")

            # 매개변수 정보 인덱스별 사전 생성
            param_info_map = {info["index"]: info for info in param_info_list}

            # 각 생성자 인자에 대해 처리
            for x_idx, x in enumerate(constructor_args):
                # pygccxml용 네임스페이스 포함 완전 수식 타입명 얻기
                resolved_type_str = get_fully_qualified_type_name_pygccxml(x)
                arg_name = x.name if x.name else f"arg{x_idx}"

                # 템플릿 특수 처리가 필요한 경우 타입 오버라이드
                final_type_for_binding = resolved_type_str
                if x_idx in param_info_map:
                    override_type = detect_template_type_simple(param_info_map[x_idx])
                    if override_type:
                        # HArray/HSequence의 초기값 생성자인지 확인
                        if param_info_map[x_idx]["description"] == "defaultValue":
                            # 여기서 ElementType으로 타입을 강제 지정
                            final_type_for_binding = (
                                f"const {template_info['value_type'].name} &"
                            )
                            console.print(
                                f"DEBUG: Constructor init value type override: {final_type_for_binding}"
                            )
                        else:
                            final_type_for_binding = override_type

                # 배열 참조 처리
                if "(&)" in final_type_for_binding and "[" in final_type_for_binding:
                    final_type_for_struct_def = final_type_for_binding.replace(
                        "(&)", f"(&{arg_name})"
                    )
                    processed_args_for_struct_def.append(final_type_for_struct_def)
                else:
                    processed_args_for_struct_def.append(
                        f"{final_type_for_binding} {arg_name}"
                    )

                processed_arg_types_for_embind.append(final_type_for_binding)
                processed_arg_names_for_init.append(arg_name)

            # 템플릿 인자가 미치환된 채 남아있는지 검사하여, 있으면 이 생성자 바인딩 skip
            has_unresolved_template = False
            if templateArgs:
                for t in processed_arg_types_for_embind:
                    for key in templateArgs.keys():
                        if key in t:
                            has_unresolved_template = True
                            break
                    if has_unresolved_template:
                        break
            # 그래도 못 잡는 경우, 흔한 미치환 패턴인 'T' 또는 '<...>' 포함 여부 추가 검사
            if not has_unresolved_template:
                for t in processed_arg_types_for_embind:
                    if "T" in t or ("<" in t and ">" in t):
                        has_unresolved_template = True
                        break
            if has_unresolved_template:
                console.print(
                    f"Skipping constructor overload {name}{overloadPostfix} due to unresolved template parameters"
                )
                continue

            # 인자 중 정의가 없는 타입이 있으면 skip (forward 선언 등)
            has_undefined_type = False
            for arg in constructor_args:
                decl = arg.related_class.get_declaration()
                if not decl or not decl.is_definition():
                    has_undefined_type = True
                    break
            if has_undefined_type:
                console.print(
                    f"Skipping constructor overload {name}{overloadPostfix} due to undefined argument type"
                )
                continue

            # 리스트를 문자열로 조합
            args = ", ".join(processed_args_for_struct_def)
            argTypes = ", ".join(processed_arg_types_for_embind)
            argNames = ", ".join(processed_arg_names_for_init)

            # 헬퍼 구조체 및 Embind 클래스 바인딩 코드 생성
            constructorBindings += (
                f"{indent(4)}struct {name}{overloadPostfix} : public {name} {{\n"
                + f"{indent(6)}{name}{overloadPostfix}({args}) : {name}({argNames}) {{}}\n"
                + f"{indent(4)}}};\n"
                + f'{indent(4)}class_<{name}{overloadPostfix}, base<{name}>>("{name}{overloadPostfix}")\n'
                + f"{indent(6)}.constructor<{argTypes}>()\n"
                + f"{indent(4)};\n"
            )

        output += constructorBindings
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
