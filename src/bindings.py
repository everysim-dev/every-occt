# import clang.cindex 제거됨
from pygccxml import declarations
import re

from wasmGenerator.Common import (
    SkipException,
    getPublicMemberFunctions,
    isAbstractClass,
    getMethodOverloadPostfix,
    unwrap_type,
)
from filter.filterClasses import filterClass
from filter.filterMethodOrProperties import filterMethodOrProperty
from Common import console
from typing import Union, Optional, Dict
from typing import Optional


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


def shouldProcessClass(decl: declarations.declaration_t):
    # 네임스페이스는 무시
    if isinstance(decl, declarations.namespace_t):
        return False

    return True


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

cStringTypes = [
    "const char *",
    "const char *const",
    "char *",
    "char *const",
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


def isCString(type_obj):
    return str(type_obj).strip() in cStringTypes


from pygccxml import parser, declarations


def get_canonical(decl: declarations.declaration_t) -> declarations.declaration_t:
    """pygccxml declaration의 canonical type 접근 함수"""
    result = decl
    while hasattr(result, "declaration") and result.declaration is not result:
        result = result.declaration
    return result


def get_class_type_name_pygccxml(decl):
    """
    pygccxml class_t로부터 네임스페이스 포함 클래스 이름 반환
    """
    if hasattr(decl, "decl_string") and decl.decl_string:
        return decl.decl_string
    if hasattr(decl, "name"):
        return decl.name
    return str(decl)


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
    def processClass(
        self,
        theClass: declarations.class_t,
        templateDecl: Optional[declarations.typedef_t] = None,
        templateArgs: Optional[
            Dict[str, Union[declarations.type_t, declarations.declaration_t]]
        ] = None,
    ) -> str:
        output = ""
        className = getClassTypeName(theClass, templateDecl)
        if className == "":
            className = theClass.related_class.declaration
        isAbstract = isAbstractClass(theClass)

        if not isAbstract:
            output += self.processSimpleConstructor(theClass)

        for method in getPublicMemberFunctions(theClass):
            method: declarations.member_function_t

            try:
                output += self.processMethodOrProperty(theClass, method, templateDecl)
            except SkipException as e:
                console.print(str(e))
        output += self.processFinalizeClass()
        if not isAbstract:
            try:
                output += self.processOverloadedConstructors(
                    theClass, None, templateDecl, templateArgs
                )
            except SkipException as e:
                console.print(str(e))
        return output


class EmbindBindings(Bindings):
    def processClass(
        self,
        theClass: declarations.class_t,
        templateDecl=None,
        templateArgs=None,
        className=None,
    ):
        output = ""
        if className is None:
            className = get_class_type_name_pygccxml(theClass)

        if className.startswith("::"):
            className = className[2:]

        tokens = className.split("::")
        lastToken = tokens[-1]

        output += (
            f"EMSCRIPTEN_BINDINGS({lastToken}) {{\n"
        )

        output += (
            f'  class_<{className}>("{lastToken}")\n'
        )

        output += super().processClass(theClass, templateDecl, templateArgs)

        output += "}\n\n"

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
            output += f"namespace emscripten {{ namespace internal {{ template<> void raw_destructor<{lastToken}>({lastToken}* ptr) {{ /* do nothing */ }} }} }}\n"
        return output

    def processFinalizeClass(self):
        return "  ;\n"

    def processSimpleConstructor(self, theClass: declarations.class_t) -> str:
        output = ""

        constructors = []

        if hasattr(theClass, "constructors"):
            constructors = theClass.constructors(allow_empty=True)

        publicConstructors = [
            constructor
            for constructor in constructors
            if constructor.access_type == "public"
        ]

        if len(publicConstructors) == 0:
            output += "    .constructor<>()\n"
            return output

        if len(publicConstructors) != 1:
            return output

        standardConstructor = publicConstructors[0]

        def argTypeToString(arg: declarations.argument_t):
            result = f"{arg.decl_type.decl_string}"

            if arg.default_value:
                result += f" = {arg.default_value}"

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

    def getSingleArgumentBinding(self, argNames=True):
        def f(arg: declarations.argument_t):
            argBinding = ""
            changed = False

            typename = get_fully_qualified_type_name_pygccxml(arg)

            argBinding = typename + ((" " + arg.name) if argNames else "")

            return [argBinding, changed]

        return f

    def processMethodOrProperty(
        self,
        theClass: declarations.class_t,
        method: declarations.member_function_t,
        templateDecl: Optional[declarations.typedef_t] = None,
    ) -> str:
        output = ""
        className = get_class_type_name_pygccxml(theClass)
        [overloadPostfix, numOverloads] = getMethodOverloadPostfix(theClass, method)

        for type in method.argument_types:
            if isinstance(type, declarations.reference_t):
                type = type.base
            
            # 스트림 타입 임시 비활성화
            # TODO: 스트림 타입을 처리할 수 있는 방법을 찾아야 함
            if any(
                term in unwrap_type(type).decl_string
                for term in ["ostream", "istream", "fstream", "ssteam"]
            ):
                return ""


        def needsWrapper(type: Union[declarations.argument_t, declarations.type_t, declarations.declarated_t, declarations.void_t]):
            # C 문자열 포인터는 항상 래핑 필요
            if isinstance(type, declarations.pointer_t) and isCString(type):
                return True
            
            decl_type = type.decl_type if hasattr(type, "decl_type") else type

            # LValueReference가 아니면 래핑 필요 없음
            if not isinstance(decl_type, declarations.reference_t):
                return False

            pointee: Union[declarations.const_t, declarations.declarated_t] = decl_type.base

            # 상수 참조는 래핑 필요 없음 - 데이터 수정 불가
            if isinstance(pointee, declarations.const_t):
                return False
            
            root_type = unwrap_type(pointee)

            # 기본 타입(int, float 등)은 래핑 필요
            # 이는 값 변경이 포인터를 통해 전달되어야 하기 때문
            if isinstance(root_type, declarations.fundamental_t):
                return True

            # 포인터에 대한 참조는 래핑 필요
            if isinstance(pointee, declarations.pointer_t):
                return True

            if isinstance(pointee, declarations.enumeration_t):
                return True

            # 때로는 열거형이 ELABORATED로 나올 수 있음
            if isinstance(pointee, declarations.elaborated_t):
                underlying_type = pointee.related_class
                return underlying_type and isinstance(
                    underlying_type, declarations.enumeration_t
                )

            # 정규화된 타입 확인
            if isinstance(pointee, declarations.enumeration_t):
                return True

            return False

        args = list(method.arguments)
        argsNeedingWrapper = list(map(lambda arg: needsWrapper(arg), args))
        returnNeedsWrapper = needsWrapper(method.return_type)

        if any(argsNeedingWrapper) or returnNeedsWrapper:

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

            classTypeName = getClassTypeName(theClass, templateDecl)
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
                        "const"
                        not in args[x[0]].declaration.base.qualifiers
                        or "const" in args[x[0]].qualifiers
                    ):
                        return f"{getArgName(x)}.isNull() ? nullptr : strdup({getArgName(x)}.as<std::string>().c_str())"
                    else:
                        return f"{getArgName(x)}.isNull() ? nullptr : {getArgName(x)}.as<std::string>().c_str()"
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
                        pick(not method.has_static, f"{classTypeName}&", ""),
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
                    pick(not method.has_static, f"{classTypeName}& that", ""),
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
            if numOverloads == 1:
                functionBinding = f" &{className}::{method.name}"
            else:
                argumentBinding = merge(
                    ", ",
                    *map(
                        lambda x: self.getSingleArgumentBinding(True)(x)[0],
                        list(method.arguments),
                    ),
                )
                constBinding = pick(method.has_const, " const", "")
                classBinding = pick(not method.has_static,f", {className}","")
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
                    "Cannot handle array properties, skipping "
                    + className
                    + "::"
                    + method.name
                )
            elif not (getattr(method, "base", None) is None):
                console.print(
                    "Cannot handle pointer properties, skipping "
                    + className
                    + "::"
                    + method.name
                )
            else:
                output += f'{indent(2)}.property("{method.name}", &{className}::{method.name})\n'
        return output

    def processOverloadedConstructors(
        self, theClass, children=None, templateDecl=None, templateArgs=None
    ):
        output = ""

        # 템플릿이 아닌 클래스는 템플릿 인자 사용하는 생성자 오버로딩 생략
        is_template_class = (
            hasattr(theClass, "template_args") and len(theClass.template_args) > 0
        ) or (
            hasattr(theClass, "get_num_template_arguments")
            and theClass.get_num_template_arguments() > 0
        )
        if not is_template_class:
            return ""
        if children is None:
            children = list(theClass.declarations)

        # 모든 public 생성자 가져오기
        constructors = list(
            filter(
                lambda x: isinstance(x, declarations.constructor_t)
                and x.access_type == "public",
                children,
            )
        )

        # 오버로딩할 생성자가 1개 이하면 처리 중단 (이미 processSimpleConstructor에서 처리했거나 오버로딩 불필요)
        if len(constructors) <= 1:
            return output

        constructorBindings = ""
        allOverloads = constructors  # 모든 public 생성자 리스트

        # 바인딩 가능한 생성자 필터링 (filterMethodOrProperty 적용)
        valid_constructors_for_binding = list(
            filter(lambda x: filterMethodOrProperty(theClass, x), allOverloads)
        )

        # 바인딩 가능한 생성자가 1개 이하이고, 그 중 인자 없는 생성자가 있다면 오버로딩 불필요
        if len(valid_constructors_for_binding) <= 1 and any(
            len(list(c.arguments)) == 0 for c in valid_constructors_for_binding
        ):
            return output

        # 템플릿 타입 감지
        class_name = get_class_type_name_pygccxml(theClass)
        template_info = detect_template_type_simple(class_name)

        # 생성자 인덱스 매핑 (일관된 이름 부여용)
        constructor_indices = {con: idx for idx, con in enumerate(allOverloads)}

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
                resolved_type_str = get_fully_qualified_type_name_pygccxml(
                    x.related_class
                )
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
                f"{indent(4)}struct {name}{overloadPostfix} : public {name} {{\n" +
                f"{indent(6)}{name}{overloadPostfix}({args}) : {name}({argNames}) {{}}\n" +
                f"{indent(4)}}};\n" +
                f'{indent(4)}class_<{name}{overloadPostfix}, base<{name}>>("{name}{overloadPostfix}")\n' +
                f"{indent(6)}.constructor<{argTypes}>()\n" +
                f"{indent(4)};\n"
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
