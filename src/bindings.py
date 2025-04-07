import clang.cindex
import re

from wasmGenerator.Common import (
    SkipException,
    isAbstractClass,
    getMethodOverloadPostfix,
)
from filter.filterClasses import filterClass
from filter.filterMethodOrProperties import filterMethodOrProperty
from Common import occtBasePath, console
from typing import Tuple, List


def merge(sep: str, *strings: List[str]):
    return sep.join(strings)


def pick(condition: bool, strTrue: str, strFalse: str):
    return strTrue if condition else strFalse


def pickWrap(
    condition: bool, wrapStart: Tuple[str, str], center: str, wrapEnd: Tuple[str, str]
):
    return (
        (wrapStart[0] if condition else wrapStart[1])
        + center
        + (wrapEnd[0] if condition else wrapEnd[1])
    )


def indent(level: int):
    return " " * level * 2

def shouldProcessClass(child: clang.cindex.Cursor, occtBasePath: str):
    if child.get_definition() is None or not child == child.get_definition():
        return False

    if not filterClass(child):
        return False

    if (
        child.kind == clang.cindex.CursorKind.CLASS_DECL
        or child.kind == clang.cindex.CursorKind.STRUCT_DECL
    ) and not child.type.get_num_template_arguments() == -1:
        return False

    if (
        child.kind == clang.cindex.CursorKind.CLASS_DECL
        or child.kind == clang.cindex.CursorKind.STRUCT_DECL
    ):
        baseSpec = list(
            filter(
                lambda x: x.kind == clang.cindex.CursorKind.CXX_BASE_SPECIFIER
                and x.access_specifier == clang.cindex.AccessSpecifier.PUBLIC,
                child.get_children(),
            )
        )
        if len(baseSpec) > 1:
            console.print("cannot handle multiple base classes (" + child.spelling + ")")
            return False

        return True

    return False


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
    "TColStd_Array1OfReal"
]

def isCString(type):
    return type.get_canonical().spelling in cStringTypes

def get_fully_qualified_type_name(type_obj):
    """
    libclang Type 또는 Cursor로부터 네임스페이스, 중첩 클래스, 템플릿 인자 포함한 완전 수식 타입명 생성
    """
    # Type이 아닌 Cursor가 들어오면, Cursor에서 Type 추출
    if isinstance(type_obj, clang.cindex.Cursor):
        type_obj = type_obj.type

    # 템플릿 인자가 있으면 재귀적으로 처리
    if hasattr(type_obj, 'get_num_template_arguments') and type_obj.get_num_template_arguments() > 0:
        base_name = type_obj.spelling.split('<')[0].strip()
        args = []
        for i in range(type_obj.get_num_template_arguments()):
            try:
                arg_type = type_obj.get_template_argument_type(i)
                if arg_type.kind != clang.cindex.TypeKind.INVALID:
                    args.append(get_fully_qualified_type_name(arg_type))
            except:
                continue
        return f"{base_name}<{', '.join(args)}>"
    
    # 이름이 비어있으면 INVALID
    spelling = type_obj.spelling.strip()
    if not spelling or spelling == 'void':
        return spelling

    # 중첩 클래스 처리
    decl = type_obj.get_declaration()
    if not decl or decl.kind == clang.cindex.CursorKind.NO_DECL_FOUND:
        return spelling

    names = []
    cursor = decl
    while cursor and cursor.kind != clang.cindex.CursorKind.TRANSLATION_UNIT:
        if cursor.spelling:
            names.append(cursor.spelling)
        cursor = cursor.lexical_parent

    fq_name = "::".join(reversed(names))
    return fq_name if fq_name else spelling


def getClassTypeName(theClass, templateDecl=None):
    return templateDecl.spelling if templateDecl is not None else theClass.spelling

class Bindings:
    def __init__(self, typedefs, templateTypedefs, translationUnit):
        self.templateTypedefs = templateTypedefs
        self.translationUnit = translationUnit
        self.typedefs = typedefs

    def getTypedefedTemplateTypeAsString(
        self, theTypeSpelling, templateDecl=None, templateArgs=None, type_obj=None
    ):
        # 우선 템플릿 인자 치환
        if templateDecl is None:
            typedefType = next(
                (
                    x
                    for x in self.typedefs
                    if x.location.file.name.startswith(occtBasePath)
                    and x.underlying_typedef_type.spelling == theTypeSpelling
                ),
                None,
            )
            typedefType = None if typedefType is None else typedefType.spelling
        else:
            templateType = self.replaceTemplateArgs(theTypeSpelling, templateArgs)
            rawTemplateType = templateType.replace("&", "").replace("const", "").strip()
            rawTypedefType = next(
                (
                    x
                    for x in self.templateTypedefs
                    if (
                        x.underlying_typedef_type.spelling == rawTemplateType
                        or x.underlying_typedef_type.spelling
                        == "opencascade::" + rawTemplateType
                    )
                ),
                None,
            )
            rawTypedefType = (
                rawTemplateType if rawTypedefType is None else rawTypedefType.spelling
            )
            typedefType = templateType.replace(rawTemplateType, rawTypedefType)

        # 템플릿 타입인 경우, 재귀적으로 fully qualified name 생성
        if type_obj is not None:
            fq_name = get_fully_qualified_type_name(type_obj)
            # IndexedDataMap 같은 템플릿 타입이 제대로 반환되지 않으면, canonical spelling 사용
            if (not fq_name or fq_name == "" or fq_name in ["int", "unsigned int", "long", "unsigned long"]) and hasattr(type_obj, 'get_canonical'):
                canonical = type_obj.get_canonical()
                canonical_name = canonical.spelling.strip()
                # 템플릿 타입이고, int 등 기본형이 아니면 canonical 사용
                if '<' in canonical_name and '>' in canonical_name:
                    return canonical_name
            if fq_name and fq_name != "":
                return fq_name

        if typedefType is not None:
            # IndexedDataMap 같은 템플릿 타입이 int 등으로 fallback되는 경우 방지
            if '<' in typedefType and '>' in typedefType:
                return typedefType

        # 마지막 fallback
        return theTypeSpelling

    def replaceTemplateArgs(self, string, templateArgs=None):
        newString = string
        if templateArgs is None:
            return newString
        for key in templateArgs:
            p = re.compile("(\\W+|^)" + key + "(\\W|$)")
            newString = p.sub("\\1" + templateArgs[key].spelling + "\\2", newString)
        return newString

    def processClass(self, theClass, templateDecl=None, templateArgs=None):
        output = ""
        className = getClassTypeName(theClass, templateDecl)
        if className == "":
             # Use canonical name as a fallback for the class itself
             className = self.get_canonical_spelling(theClass.type)
             # className = theClass.type.spelling # Original fallback
        isAbstract = isAbstractClass(theClass, self.translationUnit)

        if not isAbstract:
            output += self.processSimpleConstructor(theClass)
        for method in theClass.get_children():
            if not filterMethodOrProperty(theClass, method):
                continue
            try:
                output += self.processMethodOrProperty(
                    theClass, method, templateDecl, templateArgs
                )
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

class TemplateTypeDetector:
    """OpenCascade 템플릿 기반 타입 감지 및 처리 클래스"""
    
    def __init__(self, translation_unit):
        self.translation_unit = translation_unit
        self.type_cache = {}  # 중복 검색 방지를 위한 캐시
    
    def detect_template_type(self, class_name):
        """클래스 이름을 기반으로 템플릿 패턴을 감지하고 관련 정보를 반환"""
        # 캐시 확인
        if class_name in self.type_cache:
            return self.type_cache[class_name]
        
        result = {
            'is_template_type': False,
            'template_pattern': None,
            'base_type_name': None,
            'value_type': None,
            'item_type': None,
            'collection_type': None
        }

        if "opencascade::handle" in class_name:
            self.type_cache[class_name] = result
            return result
        
        # 패턴 감지
        if "HArray1Of" in class_name:
            result['is_template_type'] = True
            result['template_pattern'] = 'HArray1'
            result['base_type_name'] = class_name.replace("HArray1Of", "Array1Of")
        elif "HArray2Of" in class_name:
            result['is_template_type'] = True
            result['template_pattern'] = 'HArray2'
            result['base_type_name'] = class_name.replace("HArray2Of", "Array2Of")
        elif "HSequenceOf" in class_name:
            result['is_template_type'] = True
            result['template_pattern'] = 'HSequence'
            result['base_type_name'] = class_name.replace("HSequenceOf", "SequenceOf")
        # NCollection 기반 다른 컬렉션 타입들
        elif any(pattern in class_name for pattern in ["HListOf", "HMapOf", "HSetOf"]):
            for pattern, replacement in [
                ("HListOf", "ListOf"),
                ("HMapOf", "MapOf"),
                ("HSetOf", "SetOf")
            ]:
                if pattern in class_name:
                    result['is_template_type'] = True
                    result['template_pattern'] = pattern.replace("Of", "")
                    result['base_type_name'] = class_name.replace(pattern, replacement)
                    break
        # NCollection_IndexedDataMap 감지 추가
        elif "NCollection_IndexedDataMap" in class_name and '<' in class_name and '>' in class_name:
            result['is_template_type'] = True
            result['template_pattern'] = 'IndexedDataMap'
            result['base_type_name'] = class_name.split('<')[0].strip()
            args_part = class_name[class_name.find('<')+1:class_name.rfind('>')]
            args = [arg.strip() for arg in args_part.split(',')]
            if len(args) >= 2:
                result['key_type'] = args[0]
                result['value_type'] = args[1]
        elif '<' in class_name and '>' in class_name:
            base_part = class_name.split('<')[0].strip()
            args_part = class_name.split('<')[1].split('>')[0].strip()
            
            # 특수 템플릿 타입인지 확인
            if any(base_part.endswith(special_type) for special_type in special_template_types):
                result['is_template_type'] = True
                result['base_type_name'] = base_part
                result['value_type'] = args_part
        
        # 템플릿 타입이 아닌 경우 여기서 종료
        if not result['is_template_type']:
            self.type_cache[class_name] = result
            return result

        if result['base_type_name']:
            result['base_type_name'] = result['base_type_name'].replace("const", "").strip()
        
        # 기본 타입 찾기 (Array1, Array2, Sequence 등)
        console.print(f"DEBUG: 템플릿 기본 타입 '{result['base_type_name']}' 검색 중...")
        base_type_cursor = self._find_base_type_cursor(result['base_type_name'])
        
        if base_type_cursor:
            console.print(f"DEBUG: 기본 타입 커서 발견: {base_type_cursor.kind}")
            # 컬렉션 타입 결정 (NCollection_Array1, NCollection_Array2 등)
            underlying_type = None
            if base_type_cursor.kind == clang.cindex.CursorKind.TYPEDEF_DECL:
                underlying_type = base_type_cursor.underlying_typedef_type
                result['collection_type'] = underlying_type.spelling
                console.print(f"DEBUG: 컬렉션 타입: {result['collection_type']}")
            
            # 값 타입 결정 (템플릿 인자)
            if underlying_type and underlying_type.get_num_template_arguments() > 0:
                result['value_type'] = underlying_type.get_template_argument_type(0)
                console.print(f"DEBUG: value_type: {result['value_type'].spelling}")
                
                # 항목 타입이 있는 경우 (예: NCollection_Array2의 두 번째 템플릿 인자)
                if underlying_type.get_num_template_arguments() > 1:
                    result['item_type'] = underlying_type.get_template_argument_type(1)
                    console.print(f"DEBUG: item_type: {result['item_type'].spelling}")
        else:
            console.print(f"WARNING: 기본 타입 '{result['base_type_name']}'을 찾을 수 없습니다.")
            result['is_template_type'] = False
        
        # 결과 캐싱 및 반환
        self.type_cache[class_name] = result
        return result
    
    def _find_base_type_cursor(self, type_name):
        """주어진 타입 이름에 대한 커서 찾기"""
        for node in self.translation_unit.cursor.walk_preorder():
            if node.spelling == type_name:
                if node.kind in [
                    clang.cindex.CursorKind.CLASS_DECL, 
                    clang.cindex.CursorKind.STRUCT_DECL,
                    clang.cindex.CursorKind.TYPEDEF_DECL
                ]:
                    return node
        return None
    
    def get_constructor_params_info(self, template_info, constructor_args):
        """생성자 매개변수 정보 처리"""
        params_info = []
        
        if not template_info['is_template_type']:
            return params_info
        
        pattern = template_info['template_pattern']
        value_type = template_info['value_type']
        
        # 패턴별 생성자 매개변수 처리
        if pattern == 'HArray1':
            # HArray1 패턴 처리: (lower, upper, [value_type])
            if len(constructor_args) == 3 and value_type:
                params_info.append({
                    'index': 2,
                    'expected_type': value_type,
                    'description': 'defaultValue'
                })
        
        elif pattern == 'HArray2':
            # HArray2 패턴 처리: (rowLow, rowUpp, colLow, colUpp, [value_type])
            if len(constructor_args) == 5 and value_type:
                params_info.append({
                    'index': 4,
                    'expected_type': value_type,
                    'description': 'defaultValue'
                })
        
        elif pattern == 'HSequence':
            # HSequence 패턴 처리
            if len(constructor_args) > 0 and value_type:
                # 인자 개수에 따라 다른 생성자일 수 있음
                if len(constructor_args) == 1:
                    # 가능한 복사 생성자 혹은 초기 크기 생성자
                    arg_type = constructor_args[0].type.spelling
                    if "int" in arg_type.lower() or "integer" in arg_type.lower():
                        # 초기 크기 생성자 - 일반적으로 처리 필요 없음
                        pass
                    else:
                        # 복사 생성자일 가능성 - 타입 확인 필요
                        params_info.append({
                            'index': 0,
                            'expected_type': value_type,
                            'description': 'copyValue'
                        })
        
        # 다른 패턴에 대한 처리도 추가 가능
        
        return params_info
    
    def get_correct_type_for_param(self, param_info):
        """매개변수에 대한 올바른 타입 문자열 반환"""
        if not param_info or not param_info['expected_type']:
            return None
        
        # 간단한 경우: const Type&
        return f"const {param_info['expected_type'].spelling} &"


class EmbindBindings(Bindings):
    def __init__(self, typedefs, templateTypedefs, translationUnit):
        super().__init__(typedefs, templateTypedefs, translationUnit)
        self.template_detector = TemplateTypeDetector(translationUnit)

    def is_non_copyable_class(self, cursor):
        """클래스가 복사 불가능한지 확인합니다 (private 복사 생성자)"""
        for method in cursor.get_children():
            if (method.kind == clang.cindex.CursorKind.CONSTRUCTOR and 
                method.access_specifier == clang.cindex.AccessSpecifier.PRIVATE):
                # 복사 생성자인지 확인
                args = list(method.get_arguments())
                if (len(args) == 1 and 
                    args[0].type.get_canonical().spelling.find(cursor.spelling) != -1 and
                    "const" in args[0].type.spelling):
                    return True
        return False

    def processClass(self, theClass, templateDecl=None, templateArgs=None):
        output = ""
        className = getClassTypeName(theClass, templateDecl)
        if className == "":
            className = theClass.type.spelling

        # 템플릿 타입 감지
        template_info = self.template_detector.detect_template_type(className)
        if template_info.get('is_template_type') and template_info.get('template_pattern') == 'IndexedDataMap':
            key_type = template_info.get('key_type', 'TCollection_AsciiString')
            value_type = template_info.get('value_type', 'Standard_Integer')

            output += f"EMSCRIPTEN_BINDINGS({theClass.spelling if templateDecl is None else templateDecl.spelling}) {{\n"
            output += f"  class_<{className}>(\"{className}\")\n"
            output += f"    .constructor<>()\n"
            output += f"    .function(\"Size\", &{className}::Size)\n"
            output += f"    .function(\"Clear\", &{className}::Clear)\n"
            output += f"    .function(\"Add\", select_overload<void(const {key_type}&, const {value_type}&)>(&{className}::Add))\n"
            output += f"    .function(\"ChangeFromIndex\", &{className}::ChangeFromIndex, allow_raw_pointers())\n"
            output += f"    .function(\"FindFromKey\", &{className}::FindFromKey, allow_raw_pointers())\n"
            output += f"  ;\n"
            output += "}\n\n"
            return output

        is_non_copyable = self.is_non_copyable_class(theClass)

        baseSpec = list(
            filter(
                lambda x: x.kind == clang.cindex.CursorKind.CXX_BASE_SPECIFIER
                and x.access_specifier == clang.cindex.AccessSpecifier.PUBLIC,
                theClass.get_children(),
            )
        )

        if len(baseSpec) > 0:
            baseClassBinding = ", base<" + baseSpec[0].type.spelling + ">"
        else:
            baseClassBinding = ""

        output += (
            "EMSCRIPTEN_BINDINGS("
            + (theClass.spelling if templateDecl is None else templateDecl.spelling)
            + ") {\n"
        )

        if is_non_copyable:
            output += (
                "  // 복사 불가능한 클래스\n"
                + "  class_<" + className + baseClassBinding + '>("' + className + '")\n'
            )
        else:
            output += (
                "  class_<" + className + baseClassBinding + '>("' + className + '")\n'
            )

        output += super().processClass(theClass, templateDecl, templateArgs)

        output += "}\n\n"

        # Epilog
        nonPublicDestructor = any(
            x.kind == clang.cindex.CursorKind.DESTRUCTOR
            and not x.access_specifier == clang.cindex.AccessSpecifier.PUBLIC
            for x in theClass.get_children()
        )
        placementDelete = (
            next(
                (
                    x
                    for x in theClass.get_children()
                    if x.spelling == "operator delete"
                    and len(list(x.get_arguments())) == 2
                ),
                None,
            )
            is not None
        )
        if nonPublicDestructor or placementDelete:
            output += (
                f"namespace emscripten {{ namespace internal {{ template<> void raw_destructor<{theClass.spelling}>({theClass.spelling}* ptr) {{ /* do nothing */ }} }} }}\n"
            )
        return output

    def processFinalizeClass(self):
        return "  ;\n"

    def processSimpleConstructor(self, theClass):
        output = ""
        children = list(theClass.get_children())
        constructors = list(
            filter(lambda x: x.kind == clang.cindex.CursorKind.CONSTRUCTOR, children)
        )

        if len(constructors) == 0:
            output += "    .constructor<>()\n"
            return output
        publicConstructors = list(
            filter(
                lambda x: x.kind == clang.cindex.CursorKind.CONSTRUCTOR
                and x.access_specifier == clang.cindex.AccessSpecifier.PUBLIC,
                children,
            )
        )
        if len(publicConstructors) != 1:
            return output
        standardConstructor = publicConstructors[0]
        if not standardConstructor:
            return output
        
        argTypesBindings = ", ".join(
            list(
                map(
                    lambda x: self.getTypedefedTemplateTypeAsString(x.type.spelling, type_obj=x.type), 
                    list(standardConstructor.get_arguments())
                )
            )
        )

        output += "    .constructor<" + argTypesBindings + ">()\n"
        return output

    def getSingleArgumentBinding(
        self,
        argNames=True,
        isConstructor=False,
        templateDecl=None,
        templateArgs=None,
        className=None,
    ):
        def f(arg):
            argChildren = list(arg.get_children())
            argBinding = ""
            hasDefaultValue = any(x.spelling == "=" for x in list(arg.get_tokens()))
            isArray = (
                not hasDefaultValue
                and len(argChildren) > 1
                and argChildren[1].kind == clang.cindex.CursorKind.INTEGER_LITERAL
            )
            changed = False
            if isArray:
                const = (
                    "const " if list(arg.get_tokens())[0].spelling == "const" else ""
                )
                arrayCount = list(argChildren[1].get_tokens())[0].spelling
                argBinding = (
                    const
                    + argChildren[0].type.spelling
                    + " (&"
                    + (arg.spelling if argNames else "")
                    + ")["
                    + arrayCount
                    + "]"
                )
                changed = True
            else:
                typename = self.getTypedefedTemplateTypeAsString(
                    arg.type.spelling, templateDecl, templateArgs, type_obj=arg.type
                )

                if '<' in typename and '>' in typename:
                    template_info = self.template_detector.detect_template_type(typename)
                    if template_info['is_template_type']:
                        console.print(f"DEBUG: 템플릿 타입 처리: {typename}")
                        changed = True

                if arg.type.kind == clang.cindex.TypeKind.LVALUEREFERENCE:
                    tokenList = list(arg.get_tokens())
                    isConstRef = len(tokenList) > 0 and tokenList[0].spelling == "const"
                    if not isConstRef:
                        if typename[-2] == "*" or "".join(
                            typename.rsplit("&", 1)
                        ).strip() in [
                            "Standard_Boolean",
                            "Standard_Real",
                            "Standard_Integer",
                        ]:  # types that can be copied
                            typename = "".join(typename.rsplit("&", 1))
                            changed = True
                        else:
                            if isConstructor:
                                if className and str(typename).startswith("Iterator"):
                                    typename = f"{className}::{typename}"
                                typename = typename
                                changed = True
                            else:
                                typename = f"const {typename}"
                                changed = True
                argBinding = typename + ((" " + arg.spelling) if argNames else "")
            return [argBinding, changed]

        return f

    def processMethodOrProperty(
        self, theClass, method, templateDecl=None, templateArgs=None
    ):
        output = ""
        className = getClassTypeName(theClass, templateDecl)
        if className == "":
            className = theClass.type.spelling
        if (
            method.access_specifier == clang.cindex.AccessSpecifier.PUBLIC
            and method.kind == clang.cindex.CursorKind.CXX_METHOD
            and not method.spelling.startswith("operator")
        ):
            [overloadPostfix, numOverloads] = getMethodOverloadPostfix(theClass, method)

            def needsWrapper(type: clang.cindex.Type):
                # C 문자열 포인터는 항상 래핑 필요
                if type.get_canonical().kind == clang.cindex.TypeKind.POINTER and isCString(type):
                    return True

                # LValueReference가 아니면 래핑 필요 없음
                if type.kind != clang.cindex.TypeKind.LVALUEREFERENCE:
                    return False
                
                pointee = type.get_pointee()
                pointee_canonical = pointee.get_canonical()

                # 상수 참조는 래핑 필요 없음 - 데이터 수정 불가
                if pointee.is_const_qualified():
                    return False

                # 기본 타입(int, float 등)은 래핑 필요
                # 이는 값 변경이 포인터를 통해 전달되어야 하기 때문
                if pointee_canonical.spelling in builtInTypes:
                    return True
                
                # 포인터에 대한 참조는 래핑 필요
                if pointee.kind == clang.cindex.TypeKind.POINTER:
                    return True
                
                
                if pointee.kind == clang.cindex.TypeKind.ENUM:
                    return True

                # 때로는 열거형이 ELABORATED로 나올 수 있음
                if pointee.kind == clang.cindex.TypeKind.ELABORATED:
                    underlying_type = pointee.get_named_type()
                    return underlying_type and underlying_type.kind == clang.cindex.TypeKind.ENUM
                
                # 정규화된 타입 확인
                if pointee_canonical.kind == clang.cindex.TypeKind.ENUM:
                    return True
                    
                # 타입 선언 확인을 통한 열거형 감지
                for cursor in pointee.get_declaration().get_children():
                    if cursor.kind == clang.cindex.CursorKind.ENUM_CONSTANT_DECL:
                        return True
                
                # 스트림 타입은 래핑 불필요
                if any(term in pointee.spelling.lower() for term in ["stream", "ostream", "istream", "fstream", "ssteam"]):
                    return False

                is_user_defined_type = (
                    pointee.kind in [
                        clang.cindex.TypeKind.RECORD,
                        clang.cindex.TypeKind.ELABORATED,
                        clang.cindex.TypeKind.UNEXPOSED
                    ]
                )

                if is_user_defined_type:
                    template_info = self.template_detector.detect_template_type(pointee_canonical.spelling)
                    is_template = template_info and template_info['is_template_type']
                    
                    # 템플릿 인자 확인
                    is_template_arg = (
                        theClass and 
                        theClass.kind == clang.cindex.CursorKind.CLASS_TEMPLATE and
                        templateArgs and 
                        pointee_canonical.spelling in templateArgs
                    )
                    
                    # 템플릿 관련 타입은 래핑 필요
                    if is_template or is_template_arg:
                        return True
                
                # 이외의 모든 타입은 기본적으로 래핑하지 않음
                return False

            args = list(method.get_arguments())
            argsNeedingWrapper = list(map(lambda arg: needsWrapper(arg.type), args))
            returnNeedsWrapper = needsWrapper(method.result_type)

            if any(argsNeedingWrapper) or returnNeedsWrapper:
                def replaceTemplateArgs(x):
                    type_spelling = args[x[0]].type.spelling
                    
                    if '<' in type_spelling and '>' in type_spelling:
                        base_type = type_spelling.split('<')[0].strip()
                        if base_type in special_template_types:
                            return type_spelling
                    
                    if (
                        templateArgs is not None
                        and args[x[0]].type.get_pointee().spelling.replace("const ", "")
                        in templateArgs
                    ):
                        return args[x[0]].type.spelling.replace(
                            args[x[0]]
                            .type.get_pointee()
                            .spelling.replace("const ", ""),
                            templateArgs[
                                args[x[0]]
                                .type.get_pointee()
                                .spelling.replace("const ", "")
                            ].spelling,
                        )
                    else:
                        return args[x[0]].type.spelling

                def getArgName(x):
                    return pick(
                        not args[x[0]].spelling == "",
                        args[x[0]].spelling,
                        f"argNo{str(x[0])}",
                    )

                def getArgTypeName(type):
                    type_spelling = type.get_pointee().spelling
                    
                    if '<' in type_spelling and '>' in type_spelling:
                        base_type = type_spelling.split('<')[0].strip()
                        if base_type in special_template_types:
                            return type_spelling
                    
                    if (
                        templateArgs is not None
                        and type.get_pointee().spelling.replace("const ", "")
                        in templateArgs
                    ):
                        return type.get_pointee().spelling.replace(
                            type.get_pointee().spelling.replace("const ", ""),
                            templateArgs[
                                type.get_pointee().spelling.replace("const ", "")
                            ].spelling,
                        )
                    else:
                        return type.get_pointee().spelling

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
                    if x[1] and not isCString(args[x[0]].type):
                        return merge(
                            "",
                            indent(4),
                            "auto ref_",
                            pick(
                                not args[x[0]].spelling == "",
                                args[x[0]].spelling,
                                f"argNo{str(x[0])}",
                            ),
                            f" = getReferenceValue<{getArgTypeName(args[x[0]].type)}>({getArgName(x)});\n",
                        )
                    else:
                        return ""

                def generateUpdateReferenceValue(x):
                    if x[1] and not isCString(args[x[0]].type):
                        return f"{indent(4)}updateReferenceValue<{getArgTypeName(args[x[0]].type)}>({getArgName(x)}, ref_{getArgName(x)});\n"
                    else:
                        return ""

                def generateInvocationArgs(x):
                    if x[1]:
                        arg_type = args[x[0]].type
                        pointee_type = arg_type.get_pointee() if arg_type.kind == clang.cindex.TypeKind.LVALUEREFERENCE else None
        
                        if (pointee_type and
                            pointee_type.get_canonical().spelling in builtInTypes and
                            not pointee_type.is_const_qualified()):
                            return f"ref_{getArgName(x)}"

                        if pointee_type:
                            template_info = self.template_detector.detect_template_type(pointee_type.spelling)
                            if template_info['is_template_type']:
                                return f"ref_{getArgName(x)}"

                        if not isCString(args[x[0]].type):
                            return f"ref_{getArgName(x)}"
                        elif (
                            not args[x[0]]
                            .type.get_canonical()
                            .get_pointee()
                            .is_const_qualified()
                            or args[x[0]].type.is_const_qualified()
                        ):
                            return f"{getArgName(x)}.isNull() ? nullptr : strdup({getArgName(x)}.as<std::string>().c_str())"
                        else:
                            return f"{getArgName(x)}.isNull() ? nullptr : {getArgName(x)}.as<std::string>().c_str()"
                    else:
                        return getArgName(x)

                resultTypeSpelling = pick(
                    returnNeedsWrapper,
                    "emscripten::val",
                    self.getTypedefedTemplateTypeAsString(
                        method.result_type.spelling, templateDecl, templateArgs
                    ),
                )
                functionBindingHead = merge(
                    "",
                    "\n",
                    indent(3),
                    pickWrap(
                        not method.is_static_method(),
                        [
                            f"std::function<{resultTypeSpelling}(",
                            f"(({resultTypeSpelling} (*)(",
                        ],
                        merge(
                            "",
                            pick(
                                not method.is_static_method(), f"{classTypeName}&", ""
                            ),
                            pick(
                                not method.is_static_method() and len(args) > 0,
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
                        pick(
                            not method.is_static_method(), f"{classTypeName}& that", ""
                        ),
                        pick(not method.is_static_method() and len(args) > 0, ", ", ""),
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
                        not method.result_type.spelling == "void",
                        merge(
                            "",
                            pick(
                                not isCString(method.result_type)
                                and (
                                    method.result_type.is_const_qualified()
                                    or method.result_type.get_pointee().is_const_qualified()
                                ),
                                "const ",
                                "",
                            ),
                            "auto",
                            pick(
                                not isCString(method.result_type)
                                and method.result_type.kind
                                == clang.cindex.TypeKind.LVALUEREFERENCE,
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
                            not method.is_static_method(),
                            "that.",
                            f"{theClass.spelling}::",
                        ),
                        f'{method.spelling}({merge(", ", *map(lambda x: generateInvocationArgs(x), enumerate(argsNeedingWrapper)))})',
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
                        method.result_type.spelling == "void",
                        "",
                        pick(
                            returnNeedsWrapper,
                            pick(
                                method.result_type.kind
                                == clang.cindex.TypeKind.POINTER,
                                merge(
                                    "",
                                    indent(4),
                                    "return ret == nullptr ? emscripten::val::null() : emscripten::val(static_cast<",
                                    pick(
                                        isCString(method.result_type),
                                        "std::string",
                                        self.getTypedefedTemplateTypeAsString(
                                            method.result_type.spelling,
                                            templateDecl,
                                            templateArgs,
                                        ),
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
                    functionBinding = f" &{className}::{method.spelling}"
                else:
                    functionBinding = merge(
                        "",
                        " select_overload<",
                        self.getTypedefedTemplateTypeAsString(
                            method.result_type.spelling, templateDecl, templateArgs
                        ),
                        f'({merge(", ", *map(lambda x: self.getSingleArgumentBinding(True, True, templateDecl, templateArgs, className=className)(x)[0], list(method.get_arguments())))})',
                        pick(method.is_const_method(), "const", ""),
                        pick(
                            not method.is_static_method(),
                            f", {getClassTypeName(theClass, templateDecl)}",
                            "",
                        ),
                        f">(&{className}::{method.spelling})",
                    )

            if method.is_static_method():
                functionCommand = "class_function"
            else:
                functionCommand = "function"

            output += f'{indent(2)}.{functionCommand}("{method.spelling}{overloadPostfix}",{functionBinding}, allow_raw_pointers())\n'
        if (
            method.access_specifier == clang.cindex.AccessSpecifier.PUBLIC
            and method.kind == clang.cindex.CursorKind.FIELD_DECL
        ):
            if method.type.kind == clang.cindex.TypeKind.CONSTANTARRAY:
                print(
                    "Cannot handle array properties, skipping "
                    + className
                    + "::"
                    + method.spelling
                )
            elif not method.type.get_pointee().kind == clang.cindex.TypeKind.INVALID:
                print(
                    "Cannot handle pointer properties, skipping "
                    + className
                    + "::"
                    + method.spelling
                )
            else:
                output += f'{indent(2)}.property("{method.spelling}", &{className}::{method.spelling})\n'
        return output

    def processOverloadedConstructors(
        self, theClass, children=None, templateDecl=None, templateArgs=None
    ):
        output = ""

        # 템플릿이 아닌 클래스는 템플릿 인자 사용하는 생성자 오버로딩 생략
        is_template_class = (
            theClass.kind == clang.cindex.CursorKind.CLASS_TEMPLATE or
            (hasattr(theClass.type, 'get_num_template_arguments') and theClass.type.get_num_template_arguments() > 0)
        )
        if not is_template_class:
            return ""
        if children is None:
            children = list(theClass.get_children())
        
        # 모든 public 생성자 가져오기
        constructors = list(
            filter(
                lambda x: x.kind == clang.cindex.CursorKind.CONSTRUCTOR
                and x.access_specifier == clang.cindex.AccessSpecifier.PUBLIC,
                children,
            )
        )

        # 오버로딩할 생성자가 1개 이하면 처리 중단 (이미 processSimpleConstructor에서 처리했거나 오버로딩 불필요)
        if len(constructors) <= 1:
             return output

        constructorBindings = ""
        allOverloads = constructors # 모든 public 생성자 리스트

        # 바인딩 가능한 생성자 필터링 (filterMethodOrProperty 적용)
        valid_constructors_for_binding = list(filter(lambda x: filterMethodOrProperty(theClass, x), allOverloads))

        # 바인딩 가능한 생성자가 1개 이하이고, 그 중 인자 없는 생성자가 있다면 오버로딩 불필요
        if len(valid_constructors_for_binding) <= 1 and any(len(list(c.get_arguments())) == 0 for c in valid_constructors_for_binding):
             return output
        
         # 템플릿 타입 감지
        class_name = getClassTypeName(theClass, templateDecl)
        template_info = self.template_detector.detect_template_type(class_name)
        
        # 생성자 인덱스 매핑 (일관된 이름 부여용)
        constructor_indices = {con: idx for idx, con in enumerate(allOverloads)}

        name = getClassTypeName(theClass, templateDecl)

        # 바인딩 가능한 생성자들에 대해 루프 실행
        for constructor in valid_constructors_for_binding:
            overload_index = constructor_indices.get(constructor, -1)
            if overload_index == -1: continue # 혹시 모를 오류 방지

            overloadPostfix = "_" + str(overload_index + 1)

            processed_args_for_struct_def = []
            processed_arg_types_for_embind = []
            processed_arg_names_for_init = []

            constructor_args = list(constructor.get_arguments())

            param_info_list = []
            if template_info['is_template_type']:
                param_info_list = self.template_detector.get_constructor_params_info(
                    template_info, constructor_args
                )
                # print(f"DEBUG: 특수 처리 필요 매개변수: {len(param_info_list)}개")

            # 매개변수 정보 인덱스별 사전 생성
            param_info_map = {info['index']: info for info in param_info_list}
            
            # 각 생성자 인자에 대해 처리
            for x_idx, x in enumerate(constructor_args):
                # 기본 타입 바인딩 정보 얻기
                type_binding_info = self.getSingleArgumentBinding(
                    argNames=False,
                    isConstructor=True,
                    templateDecl=templateDecl,
                    templateArgs=templateArgs,
                    className=class_name
                )(x)
                
                resolved_type_str = type_binding_info[0]
                arg_name = x.spelling if x.spelling else f'arg{x_idx}'
                
                # 템플릿 특수 처리가 필요한 경우 타입 오버라이드
                final_type_for_binding = resolved_type_str
                if x_idx in param_info_map:
                    override_type = self.template_detector.get_correct_type_for_param(param_info_map[x_idx])
                    if override_type:
                        # HArray/HSequence의 초기값 생성자인지 확인
                        if param_info_map[x_idx]['description'] == 'defaultValue':
                            # 여기서 ElementType으로 타입을 강제 지정
                            final_type_for_binding = f"const {template_info['value_type'].spelling} &"
                            console.print(f"DEBUG: Constructor init value type override: {final_type_for_binding}")
                        else:
                            final_type_for_binding = override_type
                
                # 배열 참조 처리
                if "(&)" in final_type_for_binding and "[" in final_type_for_binding:
                    final_type_for_struct_def = final_type_for_binding.replace("(&)", f"(&{arg_name})")
                    processed_args_for_struct_def.append(final_type_for_struct_def)
                else:
                    processed_args_for_struct_def.append(f"{final_type_for_binding} {arg_name}")
                
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
                    if 'T' in t or ('<' in t and '>' in t):
                        has_unresolved_template = True
                        break
            if has_unresolved_template:
                console.print(f"Skipping constructor overload {name}{overloadPostfix} due to unresolved template parameters")
                continue

            # 리스트를 문자열로 조합
            args = ", ".join(processed_args_for_struct_def)
            argTypes = ", ".join(processed_arg_types_for_embind)
            argNames = ", ".join(processed_arg_names_for_init)

            # 헬퍼 구조체 및 Embind 클래스 바인딩 코드 생성
            constructorBindings += (
                "    struct " + name + overloadPostfix + " : public " + name + " {\n"
            )
            constructorBindings += (
                "      "
                + name
                + overloadPostfix
                + "("
                + args
                + ") : "
                + name
                + "("
                + argNames
                + ") {}\n"
            )
            constructorBindings += "    };\n"
            constructorBindings += (
                "    class_<"
                + name
                + overloadPostfix
                + ", base<"
                + name
                + '>>("'
                + name
                + overloadPostfix
                + '")\n'
            )
            constructorBindings += "      .constructor<" + argTypes + ">()\n"
            constructorBindings += "    ;\n"

        output += constructorBindings
        return output

    def processEnum(self, theEnum):
        output = "EMSCRIPTEN_BINDINGS(" + theEnum.spelling + ") {\n"

        bindingsOutput = (
            "  enum_<" + theEnum.spelling + '>("' + theEnum.spelling + '")\n'
        )
        enumChildren = list(theEnum.get_children())
        prefix = (theEnum.spelling + "::") if theEnum.is_scoped_enum() else ""
        for enumChild in enumChildren:
            bindingsOutput += (
                '    .value("'
                + enumChild.spelling
                + '", '
                + prefix
                + enumChild.spelling
                + ")\n"
            )
        bindingsOutput += "  ;\n"
        output += bindingsOutput

        output += "}\n\n"
        return output


class TypescriptBindings(Bindings):
    def __init__(self, typedefs, templateTypedefs, translationUnit):
        super().__init__(typedefs, templateTypedefs, translationUnit)
        self.imports = {}

        self.exports = []

    def processClass(self, theClass, templateDecl=None, templateArgs=None):
        output = ""
        baseSpec = list(
            filter(
                lambda x: x.kind == clang.cindex.CursorKind.CXX_BASE_SPECIFIER
                and x.access_specifier == clang.cindex.AccessSpecifier.PUBLIC,
                theClass.get_children(),
            )
        )
        baseClassDefinition = ""
        if len(baseSpec) > 0:
            if any(x in baseSpec[0].type.spelling for x in [":", "<"]):
                print(
                    f'Unsupported character for base class "{baseSpec[0].type.spelling}" ({theClass.spelling})'
                )
            else:
                baseClassDefinition = " extends " + baseSpec[0].type.spelling
                # self.addImportIfWeHaveTo(baseSpec[0].type.spelling)

        name = getClassTypeName(theClass, templateDecl)
        output += "export declare class " + name + baseClassDefinition + " {\n"
        self.exports.append(name)

        output += super().processClass(theClass, templateDecl, templateArgs)
        return output

    def processFinalizeClass(self):
        output = ""
        output += "  delete(): void;\n"
        output += "}\n\n"
        return output

    def processSimpleConstructor(self, theClass):
        output = ""
        children = list(theClass.get_children())
        constructors = list(
            filter(lambda x: x.kind == clang.cindex.CursorKind.CONSTRUCTOR, children)
        )

        if len(constructors) == 0:
            output += "  constructor();\n"
            return output
        publicConstructors = list(
            filter(
                lambda x: x.kind == clang.cindex.CursorKind.CONSTRUCTOR
                and x.access_specifier == clang.cindex.AccessSpecifier.PUBLIC,
                children,
            )
        )
        if len(publicConstructors) == 0 or len(publicConstructors) > 1:
            return output
        standardConstructor = publicConstructors[0]
        if not standardConstructor:
            return output

        argsTypescriptDef = ", ".join(
            list(
                map(
                    lambda x: self.getTypescriptDefFromArg(x),
                    list(standardConstructor.get_arguments()),
                )
            )
        )

        output += "  constructor(" + argsTypescriptDef + ")\n"
        return output

    def convertBuiltinTypes(self, typeName):
        if typeName in [
            "int",
            "int16_t",
            "unsigned",
            "uint32_t",
            "unsigned int",
            "unsigned long",
            "long",
            "long int",
            "unsigned short",
            "short",
            "short int",
            "float",
            "double",
        ]:
            return "number"

        if typeName in ["char", "unsigned char", "std::string"]:
            return "string"

        if typeName in ["bool"]:
            return "boolean"
        return typeName

    def getTypescriptDefFromResultType(self, res, templateDecl=None, templateArgs=None):
        if not res.spelling == "void":
            typedefType = self.getTypedefedTemplateTypeAsString(
                res.spelling.replace("&", "")
                .replace("const", "")
                .replace("*", "")
                .strip(),
                templateDecl,
                templateArgs,
            )
            resTypeName = (
                typedefType.replace("&", "")
                .replace("const", "")
                .replace("*", "")
                .strip()
            )
            resTypeName = self.convertBuiltinTypes(resTypeName)
        else:
            resTypedefType = (
                res.spelling.replace("&", "")
                .replace("const", "")
                .replace("*", "")
                .strip()
            )
            resTypeName = resTypedefType
        if (
            resTypeName == ""
            or "(" in resTypeName
            or ":" in resTypeName
            or "<" in resTypeName
        ):
            print(
                "could not generate proper types for type name '"
                + resTypeName
                + "', using 'any' instead."
            )
            resTypeName = "any"
        return resTypeName

    def getTypescriptDefFromArg(
        self, arg, suffix="", templateDecl=None, templateArgs=None
    ):
        argTypeName = self.getTypedefedTemplateTypeAsString(
            arg.type.spelling.replace("&", "")
            .replace("const", "")
            .replace("*", "")
            .strip(),
            templateDecl,
            templateArgs,
        )
        argTypeName = (
            argTypeName.replace("&", "").replace("const", "").replace("*", "").strip()
        )
        argTypeName = self.convertBuiltinTypes(argTypeName)
        if argTypeName == "" or "(" in argTypeName or ":" in argTypeName:
            print(
                "could not generate proper types for type name '"
                + argTypeName
                + "', using 'any' instead."
            )
            argTypeName = "any"

        argname = arg.spelling if not arg.spelling == "" else ("a" + str(suffix))
        if argname in ["var", "with", "super"]:
            argname += "_"
        return argname + ": " + argTypeName

    def processMethodOrProperty(
        self, theClass, method, templateDecl=None, templateArgs=None
    ):
        output = ""
        if (
            method.access_specifier == clang.cindex.AccessSpecifier.PUBLIC
            and method.kind == clang.cindex.CursorKind.CXX_METHOD
            and not method.spelling.startswith("operator")
        ):
            [overloadPostfix, numOverloads] = getMethodOverloadPostfix(theClass, method)

            args = ", ".join(
                list(
                    map(
                        lambda x: self.getTypescriptDefFromArg(
                            x[1], x[0], templateDecl, templateArgs
                        ),
                        enumerate(method.get_arguments()),
                    )
                )
            )
            returnType = self.getTypescriptDefFromResultType(
                method.result_type, templateDecl, templateArgs
            )

            output += (
                "  "
                + ("static " if method.is_static_method() else "")
                + method.spelling
                + overloadPostfix
                + "("
                + args
                + "): "
                + returnType
                + ";\n"
            )
        return output

    def processOverloadedConstructors(
        self, theClass, children=None, templateDecl=None, templateArgs=None
    ):
        output = ""
        if children is None:
            children = list(theClass.get_children())
        constructors = list(
            filter(
                lambda x: x.kind == clang.cindex.CursorKind.CONSTRUCTOR
                and x.access_specifier == clang.cindex.AccessSpecifier.PUBLIC,
                children,
            )
        )
        if len(constructors) == 1:
            return output

        constructorTypescriptDef = ""
        allOverloadedConstructors = []

        for constructor in filter(
            lambda x: filterMethodOrProperty(theClass, x), constructors
        ):
            [overloadPostfix, numOverloads] = getMethodOverloadPostfix(
                theClass, constructor, children
            )

            argsTypescriptDef = ", ".join(
                list(
                    map(
                        lambda x: self.getTypescriptDefFromArg(
                            x, "", templateDecl, templateArgs
                        ),
                        list(constructor.get_arguments()),
                    )
                )
            )
            name = getClassTypeName(theClass, templateDecl)
            constructorTypescriptDef += (
                "  export declare class "
                + name
                + overloadPostfix
                + " extends "
                + name
                + " {\n"
            )
            constructorTypescriptDef += "    constructor(" + argsTypescriptDef + ");\n"
            constructorTypescriptDef += "  }\n\n"
            allOverloadedConstructors.append(name + overloadPostfix)
        output += constructorTypescriptDef
        self.exports.extend(allOverloadedConstructors)
        return output

    def processEnum(self, theEnum):
        output = ""
        bindingsOutput = "export declare type " + theEnum.spelling + " = {\n"
        for enumChild in list(theEnum.get_children()):
            bindingsOutput += "  " + enumChild.spelling + ": {};\n"
        bindingsOutput += "}\n\n"
        output += bindingsOutput
        self.exports.append(theEnum.spelling)
        return output
