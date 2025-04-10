from typing import List
from pygccxml import declarations


class SkipException(Exception):
    pass


def isAbstractClass(theClass: declarations.class_t):
    if hasattr(theClass, "is_abstract"):
        return theClass.is_abstract

    return False


def shouldProcessClass(child, headerFiles, filterClass):
    if child.get_definition() is None or not child == child.get_definition():
        return False

    if not filterClass(child):
        return False

    if child.__class__.__name__ == "class_t":
        if not hasattr(child, "decl_type"):
            return False

        if not child.decl_type.get_num_template_arguments() == -1:
            print("Cannot handle template classes (must be typedef'd): " + child.name)
            return False

        baseSpec = list(
            filter(
                lambda x: x.__class__.__name__ == "base_class_t"
                and x.access_type == "public",
                child.declarations,
            )
        )
        if len(baseSpec) > 1:
            print("cannot handle multiple base classes (" + child.name + ")")
            return False

        return True

    return False


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


def unwrap_type(decl: declarations.declaration_t):
    # typedef_t 체인을 따라 underlying declaration 추출
    while hasattr(decl, 'declaration') and isinstance(decl.declaration, declarations.typedef_t):
        decl = decl.declaration.decl_type # typedef_t의 원래 타입의 declaration
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


def ignoreDuplicateTypedef(typedef):
    if typedef.underlying_typedef_type.name in [
        "long",
        "unsigned long",
        "unsigned char",
        "unsigned short",
        "unsigned int",
        "signed char",
        "short",
        "int",
        "__int8_t",
        "__uint8_t",
        "__int16_t",
        "__uint16_t",
        "__int32_t",
        "__uint32_t",
        "__int64_t",
        "__uint64_t",
        "void *",
        "char *",
        "double",
        "float",
        "char",
        "size_t",
        "char16_t",
        "struct _IO_FILE",
        "Standard_Character *",
        "Standard_Integer",
        "BVH_Box<Standard_Real, 3>",
        "Standard_ExtCharacter *",
        "int (*)(...)",
        "doublereal (*)(...)",
        "void (*)(...)",
        "void",
        "XID",
        "XKeyEvent",
        "XButtonEvent",
        "XCrossingEvent",
        "XFocusChangeEvent",
        "struct _XOC *",
        "Standard_Byte *",
        "Standard_Boolean (*)(const opencascade::handle<TCollection_HAsciiString> &)",
        "Standard_Real",
    ]:
        return True

    # --> underlying_typedef_type.name
    # ----> type1.name
    # ----> type2.name

    # --> opencascade::handle<NCollection_BaseAllocator>
    # ----> Handle_NCollection_BaseAllocator
    # ----> TDF_HAllocator
    # ----> IntSurf_Allocator
    if (
        typedef.underlying_typedef_type.name
        == "opencascade::handle<NCollection_BaseAllocator>"
        and typedef.name in ["TDF_HAllocator", "IntSurf_Allocator"]
    ):
        return True

    # --> NCollection_Vec3<Standard_Real>
    # ----> Graphic3d_Vec3d
    # ----> Select3D_Vec3
    # ----> SelectMgr_Vec3
    if (
        typedef.underlying_typedef_type.name == "NCollection_Vec3<Standard_Real>"
        and typedef.name in ["Select3D_Vec3", "SelectMgr_Vec3"]
    ):
        return True

    # --> NCollection_Vec4<Standard_Real>
    # ----> Graphic3d_Vec4d
    # ----> SelectMgr_Vec4
    if (
        typedef.underlying_typedef_type.name == "NCollection_Vec4<Standard_Real>"
        and typedef.name in ["SelectMgr_Vec4"]
    ):
        return True

    # --> NCollection_Mat4<Standard_Real>
    # ----> Graphic3d_Mat4d
    # ----> SelectMgr_Mat4
    if (
        typedef.underlying_typedef_type.name == "NCollection_Mat4<Standard_Real>"
        and typedef.name in ["SelectMgr_Mat4"]
    ):
        return True

    # --> void (*)(NCollection_ListNode *, opencascade::handle<NCollection_BaseAllocator> &)
    # ----> NCollection_DelMapNode
    # ----> NCollection_DelListNode
    if (
        typedef.underlying_typedef_type.name
        == "void (*)(NCollection_ListNode *, opencascade::handle<NCollection_BaseAllocator> &)"
        and typedef.name in ["NCollection_DelMapNode"]
    ):
        return True

    # --> NCollection_List<TopoDS_Shape>
    # ----> TopoDS_ListOfShape
    # ----> TopTools_ListOfShape
    if (
        typedef.underlying_typedef_type.name == "NCollection_List<TopoDS_Shape>"
        and typedef.name in ["TopoDS_ListOfShape"]
    ):
        return True

    # --> NCollection_List<TopoDS_Shape>::Iterator
    # ----> TopoDS_ListIteratorOfListOfShape
    # ----> TopTools_ListIteratorOfListOfShape
    if (
        typedef.underlying_typedef_type == "NCollection_List<TopoDS_Shape>::Iterator"
        and typedef.name in ["TopoDS_ListIteratorOfListOfShape"]
    ):
        return True

    # --> NCollection_UBTree<Standard_Integer, Bnd_Box>
    # ----> BRepBuilderAPI_BndBoxTree
    # ----> BRepClass3d_BndBoxTree
    # ----> ShapeAnalysis_BoxBndTree
    if (
        typedef.underlying_typedef_type.name
        == "NCollection_UBTree<Standard_Integer, Bnd_Box>"
        and typedef.name in ["BRepClass3d_BndBoxTree", "ShapeAnalysis_BoxBndTree"]
    ):
        return True

    # --> NCollection_IndexedDataMap<TCollection_AsciiString, Standard_Integer, TCollection_AsciiString>
    # ----> StdStorage_MapOfTypes
    # ----> Storage_PType
    if (
        typedef.underlying_typedef_type.name
        == "NCollection_IndexedDataMap<TCollection_AsciiString, Standard_Integer, TCollection_AsciiString>"
        and typedef.name in ["StdStorage_MapOfTypes"]
    ):
        return True

    # --> opencascade::handle<BVH_Tree<Standard_ShortReal, 3, BVH_QuadTree> >
    # ----> QuadBvhHandle
    # ----> Handle_Handle_QuadBvhHandle
    if (
        typedef.underlying_typedef_type.name
        == "opencascade::handle<BVH_Tree<Standard_ShortReal, 3, BVH_QuadTree> >"
        and typedef.name in ["QuadBvhHandle"]
    ):
        return True

    return False
