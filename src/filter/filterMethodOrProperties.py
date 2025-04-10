from typing import Union
from pygccxml import declarations


def filterMethodOrProperty(theClass: declarations.class_t, methodOrProperty: declarations.member_function_t) -> bool:
  # error: undefined symbol: _ZN16AppDef_MultiLine12SetParameterEid
  if theClass.name == "AppDef_MultiLine" and methodOrProperty.name == "SetParameter":
    return False

  # error: overload of method DN has no implementation
  if theClass.name == "BSplCLib" and methodOrProperty.name == "DN":
    return False

  # error: overload of method Knots has no implementation
  if theClass.name == "BlendFunc" and (
    methodOrProperty.name == "Knots" or
    methodOrProperty.name == "Mults"
  ):
    return False

  # error: overload of method Error has no implementation
  if (
    theClass.name == "AppDef_TheResol" or
    theClass.name == "AppDef_ResConstraintOfTheGradient" or
    theClass.name == "AppDef_ResConstraintOfMyGradientOfCompute" or
    theClass.name == "AppDef_ResConstraintOfMyGradientbisOfBSplineCompute"
  ) and methodOrProperty.name == "Error":
    return False

  # error: overload of method Dump has no implementation
  if theClass.name == "BinTools_Curve2dSet" and methodOrProperty.name == "Dump":
    return False

  # error: call to deleted constructor of 'std::istream'
  if (
    (theClass.name == "BinObjMgt_Persistent" and methodOrProperty.name == "Read") or
    (theClass.name == "BinTools" and methodOrProperty.name == "GetReal") or
    (theClass.name == "BinTools" and methodOrProperty.name == "GetShortReal") or
    (theClass.name == "BinTools" and methodOrProperty.name == "GetInteger") or
    (theClass.name == "BinTools" and methodOrProperty.name == "GetBool") or
    (theClass.name == "BinTools" and methodOrProperty.name == "GetExtChar") or
    (theClass.name == "BinTools_SurfaceSet" and methodOrProperty.name == "ReadSurface") or
    (theClass.name == "BinTools_Curve2dSet" and methodOrProperty.name == "ReadCurve2d") or
    (theClass.name == "BinTools_CurveSet" and methodOrProperty.name == "ReadCurve") or
    (theClass.name == "BinTools_IStream" and methodOrProperty.name == "Stream")
  ):
    return False

  # error: no matching function for call to object of type 'std::function<bool (MeshVS_DataSource &, int, bool, NCollection_Array1<double> &, emscripten::val, MeshVS_EntityType &)>'
  if \
    (theClass.name == "MeshVS_DataSource" and methodOrProperty.name == "GetGeom") or \
    (theClass.name == "MeshVS_DataSource" and methodOrProperty.name == "GetGeomType") or \
    (theClass.name == "MeshVS_DeformedDataSource" and methodOrProperty.name == "GetGeom") or \
    (theClass.name == "MeshVS_DeformedDataSource" and methodOrProperty.name == "GetGeomType") or \
    (theClass.name == "Interface_STAT" and methodOrProperty.name == "Description") or \
    (theClass.name == "Interface_STAT" and methodOrProperty.name == "Phase"):
    return False

  # error: calling a private constructor of class 'X'
  if \
    (theClass.name == "VrmlData_Node" and methodOrProperty.name == "Scene") or \
    (theClass.name == "Font_FTFont" and methodOrProperty.name == "GlyphImage") or \
    (theClass.name == "LDOMString" and methodOrProperty.name == "getOwnerDocument") or \
    (theClass.name == "LDOM_MemManager" and methodOrProperty.name == "Self") or \
    (theClass.name == "Aspect_VKeySet" and methodOrProperty.name == "Mutex") or \
    (theClass.name == "Image_VideoRecorder" and methodOrProperty.name == "ChangeFrame") or \
    (theClass.name == "StdPrs_BRepFont" and methodOrProperty.name == "Mutex") or \
    (theClass.name == "AdvApp2Var_Network" and methodOrProperty.name == "ChangePatch") or \
    (theClass.name == "AdvApp2Var_Framework" and methodOrProperty.name == "IsoU") or \
    (theClass.name == "LDOM_Node" and methodOrProperty.name == "getOwnerDocument") or \
    (theClass.name == "AdvApp2Var_Network" and methodOrProperty.name == "Patch") or \
    (theClass.name == "AdvApp2Var_Framework" and methodOrProperty.name == "IsoV"):
    return False

  # error: non-const lvalue reference to type 'X' cannot bind to a temporary of type 'X'
  if \
    (theClass.name == "Resource_Unicode") or \
    (theClass.name == "NCollection_DataMap" and methodOrProperty.name == "Find") or \
    (theClass.name == "OSD_Thread" and methodOrProperty.name == "Wait") or \
    (theClass.name == "TCollection_ExtendedString" and methodOrProperty.name == "ToUTF8CString") or \
    (theClass.name == "Message" and methodOrProperty.name == "ToOSDMetric") or \
    (theClass.name == "OSD" and methodOrProperty.name == "RealToCString") or \
    (theClass.name == "XmlObjMgt" and methodOrProperty.name == "GetInteger") or \
    (theClass.name == "NCollection_IndexedDataMap" and methodOrProperty.name == "FindFromKey") or \
    (theClass.name == "XmlObjMgt" and methodOrProperty.name == "GetReal") or \
    (theClass.name == "BOPAlgo_Tools" and methodOrProperty.name == "PerformCommonBlocks") or \
    (theClass.name == "Transfer_Finder" and methodOrProperty.name == "GetStringAttribute") or \
    (theClass.name == "MoniTool_TypedValue" and methodOrProperty.name == "Internals") or \
    (theClass.name == "MoniTool_AttrList" and methodOrProperty.name == "GetStringAttribute") or \
    (theClass.name == "MoniTool_CaseData" and methodOrProperty.name == "Text") or \
    (theClass.name == "StepData_StepReaderData" and methodOrProperty.name == "ReadEnumParam") or \
    (theClass.name == "XSControl_Vars") or \
    (theClass.name == "MeshVS_DataSource" and methodOrProperty.name == "GetGroup"):
    return False

  # Error during build
  # error: static_assert failed due to requirement '!std::is_pointer<void (*)(Graphic3d_CView *)>::value' "Implicitly binding raw pointers is illegal.  Specify allow_raw_pointer<arg<?>>"
  if theClass.name == "Graphic3d_GraduatedTrihedron" and methodOrProperty.name == "CubicAxesCallback":
    return False

  # Error during build: error: address of bit-field requested
  if str(theClass) == "MeshVS_TwoColors":
    return False
  
  # Error during build: error: address of bit-field requested
  if (
    theClass.name == "Graphic3d_CStructure" and
    methodOrProperty.name in [
      "IsInfinite",
      "stick",
      "highlight",
      "visible",
      "HLRValidation",
      "IsForHighlight",
      "IsMutable",
      "Is2dText",
    ]
  ):
    return False

  # error: call to implicitly-deleted copy constructor of 'Aspect_VKeySet'
  # error: rvalue reference to type 'Aspect_VKeySet' cannot bind to lvalue of type 'Aspect_VKeySet'
  # error: call to implicitly-deleted copy constructor of 'Aspect_VKeySet'
  if (
    theClass.name == "AIS_ViewController" and (
      methodOrProperty.name == "Keys" or
      methodOrProperty.name == "ChangeKeys"
    )
  ) or (
    theClass.name == "Aspect_WindowInputListener" and (
      methodOrProperty.name == "Keys" or
      methodOrProperty.name == "ChangeKeys"
    )
  ):
    return False

  # error: private copy constructor used in this function
  if theClass.name == "BRepClass3d_SolidExplorer" and methodOrProperty.name == "GetTree":
    return False

  # Error comes in the binding code for "gp_TrsfNLerp", which is a template specialization of "NCollection_Lerp"
  # error: type name requires a specifier or qualifier
  # error: cannot cast from type 'void (NCollection_Lerp<gp_Trsf>::*)(double, gp_Trsf &) const' to pointer type 'gp_Trsf (*)(const gp_Trsf &, const gp_Trsf &, double)'
  if theClass.name == "NCollection_Lerp" and methodOrProperty.name == "Interpolate" and methodOrProperty.has_static:
    return False

  # causes extreme memory growth which fails the build (see corresponding typedef filter)
  if theClass.name in ["NCollection_Sequence", "NCollection_List"] and "::Iterator" in methodOrProperty.displayname:
    return False

  # Creates error during instantiation:
  # Uncaught (in promise) RuntimeError: abort(Assertion failed: bad export type for `_ZNK19Geom2dHatch_Hatcher6IsDoneEv`: undefined). Build with -s ASSERTIONS=1 for more info.
  # Seems like ::isDone() is not defined anywhere
  if theClass.name == "Geom2dHatch_Hatcher" and methodOrProperty.name == "IsDone":
    return False

  # Creates error during instantiation:
  # Uncaught (in promise) RuntimeError: abort(Assertion failed: bad export type for `_ZN21Geom2dAPI_Interpolate13ClearTangentsEv`: undefined). Build with -s ASSERTIONS=1 for more info.
  if theClass.name == "Geom2dAPI_Interpolate" and methodOrProperty.name == "ClearTangents":
    return False

  # Creates error during instantiation:
  # Uncaught (in promise) RuntimeError: abort(Assertion failed: bad export type for `_ZNK21Geom2dGcc_Lin2dTanObl11IsParallel2Ev`: undefined). Build with -s ASSERTIONS=1 for more info.
  if theClass.name == "Geom2dGcc_Lin2dTanObl" and methodOrProperty.name == "IsParallel2":
    return False

  # Creates error during instantiation:
  # Uncaught (in promise) RuntimeError: abort(Assertion failed: bad export type for `_ZN25Geom2dInt_Geom2dCurveTool11IsCompositeERK17Adaptor2d_Curve2d`: undefined). Build with -s ASSERTIONS=1 for more info.
  if theClass.name == "Geom2dInt_Geom2dCurveTool" and methodOrProperty.name == "IsComposite":
    return False

  # Creates error during instantiation:
  # Uncaught (in promise) RuntimeError: abort(Assertion failed: bad export type for `_ZN46Geom2dInt_TheCurveLocatorOfTheProjPCurOfGInter6LocateERK17Adaptor2d_Curve2dS2_iiR17Extrema_POnCurv2dS4_`: undefined). Build with -s ASSERTIONS=1 for more info.
  if theClass.name == "Geom2dInt_TheCurveLocatorOfTheProjPCurOfGInter" and methodOrProperty.name == "Locate":
    return False

  # Creates error during instantiation:
  # see above
  if theClass.name == "GeomInt_IntSS" and methodOrProperty.name == "SetTolFixTangents":
    return False

  # Creates error during instantiation:
  # see above
  if theClass.name == "GeomInt_IntSS" and methodOrProperty.name == "TolFixTangents":
    return False

  # Creates error during instantiation:
  # see above
  if theClass.name == "GeomAPI_Interpolate" and methodOrProperty.name == "ClearTangents":
    return False

  # Creates error during instantiation:
  # see above
  if theClass.name == "GeomFill_FunctionGuide" and methodOrProperty.name == "Deriv2T":
    return False

  # Creates error during instantiation:
  # see above
  if theClass.name == "GeomFill_SweepSectionGenerator" and methodOrProperty.name == "Init":
    return False

  # Creates error during instantiation:
  # see above
  if theClass.name == "GeomInt_ResConstraintOfMyGradientOfTheComputeLineBezierOfWLApprox" and methodOrProperty.name == "Error":
    return False

  # Creates error during instantiation:
  # see above
  if theClass.name == "GeomInt_ResConstraintOfMyGradientbisOfTheComputeLineOfWLApprox" and methodOrProperty.name == "Error":
    return False

  # Creates error during instantiation:
  # see above
  if theClass.name == "GeomInt_WLApprox" and methodOrProperty.name == "Perform":
    return False

  # error: no matching constructor for initialization of 'Extrema_ExtCC'
  if theClass.name in [
    "GeomAPI_ExtremaCurveSurface",
    "GeomAPI_ExtremaCurveCurve"
   ] and methodOrProperty.name == "Extrema":
    return False

  # error: call to implicitly-deleted copy constructor of 'Extrema_ExtPS'
  if theClass.name == "GeomAPI_ProjectPointOnSurf" and methodOrProperty.name == "Extrema":
    return False

  # error: no matching function for call to 'select_overload'
  if theClass.name == "Select3D_SensitiveTriangulation" and methodOrProperty.name == "LastDetectedTriangle":
    return False

  # error: call to implicitly-deleted copy constructor of 'IntTools_FClass2d'
  # error: call to implicitly-deleted copy constructor of 'BRepClass3d_SolidClassifier'
  if theClass.name == "IntTools_Context" and methodOrProperty.name in [
    "FClass2d",
    "ProjPS",
    "SolidClassifier"
  ]:
    return False

  # error: call to implicitly-deleted copy constructor of 'std::__2::basic_stringstream<char, std::__2::char_traits<char>, std::__2::allocator<char>>'
  if theClass.name == "Message_AttributeStream" and methodOrProperty.name == "Stream":
    return False

  # error: calling a private constructor of class 'OpenGl_Clipping'
  if theClass.name == "OpenGl_Context" and methodOrProperty.name in [
    "ChangeClipping",
    "Clipping",
  ]:
    return False

  if theClass.name == "OpenGl_GraphicDriver" and methodOrProperty.name in [
    "Options",
    "ChangeOptions",
  ]:
    return False

  # wasm-ld: error: /opencascade.js/build/bindings/OpenGl/OpenGl_ShaderProgram.hxx/OpenGl_ShaderProgram.cpp.o: undefined symbol: OpenGl_ShaderProgram::compileShaderVerbose(opencascade::handle<OpenGl_Context> const&, opencascade::handle<OpenGl_ShaderObject> const&, TCollection_AsciiString const&, bool)
  if theClass.name == "OpenGl_ShaderProgram" and methodOrProperty.name == "compileShaderVerbose":
    return False

  # wasm-ld: error: /opencascade.js/build/bindings/OpenGl/OpenGl_View.hxx/OpenGl_View.cpp.o: undefined symbol: OpenGl_View::SetTextureEnv(opencascade::handle<OpenGl_Context> const&, opencascade::handle<Graphic3d_TextureEnv> const&)
  if theClass.name == "OpenGl_View" and methodOrProperty.name in [
    "SetTextureEnv",
    "SetBackgroundTextureStyle",
    "SetBackgroundGradient",
    "SetBackgroundGradientType",
  ]:
    return False

  # error: call to 'abs' is ambiguous
  if (
    (
      theClass.name == "NCollection_Vec2" or
      theClass.name == "NCollection_Vec3" or
      theClass.name == "NCollection_Vec4"
    ) and
    methodOrProperty.name == "cwiseAbs"
  ):
    return False


  return True
