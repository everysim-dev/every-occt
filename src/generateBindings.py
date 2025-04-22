...
# ... previous code ...

def processChildren(
    ns: declarations.namespace_t,
    buildType: str,
    extension: str,
) -> None:
    children = (
        list(ns.typedefs())
        + list(ns.enumerations())
        + list(ns.declarations)
        + list(ns.classes())
    )

    console.print(f"Children length is {len(children)}")

    for child in children:
        [originalName, partialName] = getTypeName(child)

        if originalName not in cache:
            cache[originalName] = []

        cache[originalName].append(child)

    console.print(f"Completed caching")

    futures = []
    parallel = Parallel(n_jobs=-1, backend="threading")

    processed = set()

    for child in children:
        [originalName, childName] = getTypeName(child)

        if not filterCommon(child):
            continue

        if childName in processed:
            continue

        if not originalName:
            continue

        # if originalName != "Message_ProgressScope":
        #     continue

        processFunction = None

        if filterClasses(child):
            processFunction = embindGenerationFuncClasses
        elif filterTemplates(child):
            processFunction = embindGenerationFuncTemplates
        elif filterEnums(child):
            processFunction = embindGenerationFuncEnums
        else:
            continue

        processed.add(childName)

        func = delayed(processChild)

        futures.append(
            func(
                child,
                buildType,
                extension,
                processFunction,
            )
        )

    out = parallel(futures)

    print(f"Processed {len(out)} children")


@typechecked
def getIncludeFiles(
    decl: Union[declarations.declaration_t, declarations.cpptypes.type_t],
) -> str | None:
    while hasattr(decl, "base"):
        decl = decl.base

    if isinstance(decl, declarations.declarated_t):
        decl = decl.declaration

    queue = [decl]
    result = set()
    checked = {}

    while len(queue):
        d = queue.pop()

        if isinstance(d, declarations.fundamental_t):
            continue

        [originalName, partialName] = getTypeName(d)

        if originalName in checked:
            continue

        checked[originalName] = True

        # FIXME
        # founds = getattr(cache, originalName, [])
        # print(founds, originalName, founds.__class__.__name__)
        # queue.extend(founds)

        # if declarations.templates.is_instantiation(originalName):
        #     _, params = declarations.templates.split(originalName)

        #     for param in params:
        #         founds = getattr(cache, param, [])
        #         queue.extend(founds)

        if hasattr(d, "location"):
            if d.location is not None:
                fileName: str = d.location.file_name

                fileName = fileName.replace(".lxx", ".hxx")

                if fileName.startswith(OCCT_SRC_PATH) or fileName.endswith(HEADER_PATH):
                    result.add(os.path.basename(fileName))

    return result
