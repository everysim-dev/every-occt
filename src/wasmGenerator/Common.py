from typing import List
from pygccxml import declarations


class SkipException(Exception):
    pass


def getMethodOverloadPostfix(
    theClass: declarations.class_t, method: declarations.member_function_t
):
    allOverloads = list(theClass.member_functions(name=method.name))
    publicOverloads = list(filter(lambda x: x.access_type == "public", allOverloads))

    overloadPostfix = (
        ""
        if (not len(publicOverloads) > 1)
        else "_" + str(allOverloads.index(method) + 1)
    )

    return [overloadPostfix, len(allOverloads)]


def unwrapType(decl: declarations.declaration_t, withBase: bool = True):
    # typedef_t 체인을 따라 underlying declaration 추출
    while True:
        if withBase and hasattr(decl, "base"):
            decl = decl.base
        elif hasattr(decl, "declaration"):
            decl = decl.declaration
        elif hasattr(decl, "decl_type"):
            decl = decl.decl_type
        else:
            return decl


def getPublicMemberFunctions(
    theClass: declarations.class_t,
) -> List[declarations.member_function_t]:
    """pygccxml class_t에서 public member function만 필터링"""
    return list(
        filter(
            lambda x: x.access_type == "public" and x.parent is theClass,
            theClass.member_functions(allow_empty=True),
        )
    )
