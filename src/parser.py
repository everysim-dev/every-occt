from clang import cindex

def is_public(cursor: cindex.Cursor) -> bool:
    c = cursor

    # if LVALUEREFERENCE
    if c.kind == cindex.TypeKind.LVALUEREFERENCE:
        c = c.get_pointee()

    if hasattr(c, 'access_specifier'):
        if c.access_specifier == cindex.AccessSpecifier.PRIVATE or c.access_specifier == cindex.AccessSpecifier.PROTECTED:
            return False
    
    return True
