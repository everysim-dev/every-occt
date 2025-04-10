def filterClass(theClass, additionalInfo=None):
  # out of scope of this project
  if (
    theClass.decl_string.startswith("D3DHost") or
    theClass.decl_string.startswith("IVtk")
  ):
    return False

  # undefined symbol: GCPnts_DistFunction2d::GCPnts_DistFunction2d(GCPnts_DistFunction2d const&)
  if theClass.decl_string == "GCPnts_DistFunction2d":
    return False

  # undefined symbol: GeomFill_SweepSectionGenerator::GeomFill_SweepSectionGenerator(opencascade::handle<Geom_Curve> const&, opencascade::handle<Geom_Curve> const&, opencascade::handle<Geom_Curve> const&, double)
  if theClass.decl_string == "GeomFill_SweepSectionGenerator":
    return False

  # undefined symbol: Geom2dGcc_FunctionTanCuCuCu::Geom2dGcc_FunctionTanCuCuCu(gp_Circ2d const&, Geom2dAdaptor_Curve const&, gp_Pnt2d const&)
  if theClass.decl_string == "Geom2dGcc_FunctionTanCuCuCu":
    return False

  # Cocoa is not supported due to missing TargetConditionals.h header
  if theClass.decl_string.startswith("Cocoa"):
    return False

  # method "Add" has no implementation
  if theClass.decl_string == "DsgPrs_RadiusPresentation":
    return False

  # constructor GCPnts_DistFunction(const GCPnts_DistFunction& theOther) is not implemented
  if theClass.decl_string == "GCPnts_DistFunction":
    return False

  if theClass.decl_string.startswith("AdvApp2Var"):
    return False

  # "unsigned long" as function argument type breaks typescript
  if theClass.decl_string == "WNT_HIDSpaceMouse":
    return False

  if theClass.decl_string == "Standard_Dump":
    return False

  # error: undefined symbol: _ZN21CDF_DirectoryIteratorC2Ev
  if theClass.decl_string == "CDF_DirectoryIterator":
    return False

  # error: undefined symbol: _ZN15Geom2dEvaluator16AdjustDerivativeEidR8gp_Vec2dS1_S1_S1_ (referenced by top-level compiled C/C++ code)
  if theClass.decl_string == "Geom2dEvaluator":
    return False

  # error: allocating an object of abstract class type 'PrsDim_Dimension'
  if theClass.decl_string == "PrsDim_Dimension":
    return False

  # error: rvalue reference to type 'Storage_BaseDriver' cannot bind to lvalue of type 'Storage_BaseDriver'
  # error: allocating an object of abstract class type 'Storage_BaseDriver'
  if theClass.decl_string == "FSD_BinaryFile":
    return False

  # error: calling a private constructor of class 'Standard_Mutex'
  # error: 'operator new' is a protected member of 'Standard_Transient'
  # error: 'operator delete' is a protected member of 'Standard_Transient'
  if theClass.decl_string == "Font_BRepFont":
    return False

  # error: 'operator delete' is a protected member of 'Message_ProgressScope'
  if theClass.decl_string == "Message_LazyProgressScope":
    return False

  # error: rvalue reference to type 'Storage_BaseDriver' cannot bind to lvalue of type 'Storage_BaseDriver'
  # error: allocating an object of abstract class type 'Storage_BaseDriver'
  if theClass.decl_string == "FSD_File":
    return False

  # error: no matching function for call to 'operator new'
  if theClass.decl_string.startswith("BRepMeshData_"):
    return False

  # error: address of overloaded function 'XXX' does not match required type 'XXX'
  # Seems to have to do with a template method present
  if (
    theClass.decl_string == "gp_VectorWithNullMagnitude" or
    theClass.decl_string == "BRepTest_Objects"
  ):
    return False

  # error: incomplete type 'BOPAlgo_PaveFiller' used in type trait expression
  if theClass.decl_string == "BOPAlgo_PaveFiller":
    return False

  # []-arrays are not bound properly
  if theClass.decl_string == "BRepGProp_Gauss":
    return False

  # error: call to deleted constructor of 'std::__2::basic_Xstream<char>'
  if (
    theClass.decl_string == "BRepFeat" or
    theClass.decl_string == "GeomTools_UndefinedTypeHandler"
  ):
    return False

  # error: undefined symbol: _ZN24BRepTest_XXX
  if theClass.decl_string.startswith("BRepTest"):
    return False

  # error: undefined symbol: _ZN23BRepFeat_MakeLinearForm16TransformShapeFUEi
  if theClass.decl_string == "BRepFeat_MakeLinearForm":
    return False

  # error: undefined symbol: _ZN17BRepApprox_Approx7PerformEv
  if theClass.decl_string == "BRepApprox_Approx":
    return False

  # error: undefined symbol: _ZNK18BRepGProp_VinertGK15GetAbsolutErrorEv
  if theClass.decl_string == "BRepGProp_VinertGK":
    return False

  # error: undefined symbol: _ZNK21BRepOffset_MakeOffset10GetAnalyseEv
  if theClass.decl_string == "BRepOffset_MakeOffset":
    return False

  # error: undefined symbol: _ZNK32BRepOffsetAPI_FindContigousEdges7NbEdgesEv
  if theClass.decl_string == "BRepOffsetAPI_FindContigousEdges":
    return False

  # error: undefined symbol: _ZNK63BRepApprox_ResConstraintOfMyGradientbisOfTheComputeLineOfApprox5ErrorEv
  if theClass.decl_string == "BRepApprox_ResConstraintOfMyGradientbisOfTheComputeLineOfApprox":
    return False

  # error: undefined symbol: _ZNK66BRepApprox_ResConstraintOfMyGradientOfTheComputeLineBezierOfApprox5ErrorEv
  if theClass.decl_string == "BRepApprox_ResConstraintOfMyGradientOfTheComputeLineBezierOfApprox":
    return False

  # error: array 'new' cannot have initialization arguments
  if theClass.decl_string == "Standard_ErrorHandler":
    return False

  # error: address of overloaded function 'Append' does not match required type 'void (const int &)'
  if theClass.decl_string == "Geom_HSequenceOfBSplineSurface":
    return False

  # error: undefined symbol: _ZN24TopOpeBRepBuild_Builder114GFillSplitsPVSERK12TopoDS_ShapeRK21TopOpeBRepBuild_GTopoR23TopOpeBRepBuild_PaveSet (referenced by top-level compiled C/C++ code)
  if (
    theClass.decl_string == "TopOpeBRepBuild_Builder" or
    theClass.decl_string == "TopOpeBRepBuild_Builder1"
  ):
    return False

  # error: no suitable member 'operator delete' in 'Poly_CoherentTriPtr'
  if theClass.decl_string == "Poly_CoherentTriPtr":
    return False

  # error: undefined symbol: _ZNK22STEPSelections_Counter3POPEv (referenced by top-level compiled C/C++ code)
  if theClass.decl_string == "STEPSelections_Counter":
    return False

  # error: undefined symbol: _ZN23DrawDim_PlanarDimension19get_type_descriptorEv (referenced by top-level compiled C/C++ code)
  if theClass.decl_string == "DrawDim_PlanarDimension":
    return False

  # error: incomplete type 'Interface_GTool' used in type trait expression
  if theClass.decl_string == "Interface_Graph":
    return False
  
  # error: 'operator delete' is a protected member of 'Standard_Transient'
  if theClass.decl_string == "Font_BRepFont":
    return False
  
  if theClass.decl_string == "HLRBRep_CLProps":
    return False

  # error: non-const lvalue reference to type 'void *' cannot bind to a temporary of type 'void *'
  if theClass.decl_string == "HLRBRep_Intersector":
    return False

  # error: undefined symbol: _ZN20HLRBRep_BSurfaceTool4AxisERK19BRepAdaptor_Surface (referenced by top-level compiled C/C++ code)
  if theClass.decl_string == "HLRBRep_BSurfaceTool":
    return False

  # error: no matching function for call to object of type 'std::function<void (IGESData_IGESReaderData &, int, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, emscripten::val, const char *&, const char *&, const char *&, const char *&)>'
  if theClass.decl_string == "IGESData_IGESReaderData":
    return False

  # error: /opencascade.js/build/bindings/IGESToBRep/IGESToBRep_TopoSurface.hxx/IGESToBRep_TopoSurface.cpp.o: undefined symbol: IGESToBRep_TopoSurface::TransferPlaneSurface(opencascade::handle<IGESSolid_PlaneSurface> const&)
  if theClass.decl_string == "IGESToBRep_TopoSurface":
    return False

  # error: /opencascade.js/build/bindings/StepData/StepData_FreeFormEntity.hxx/StepData_FreeFormEntity.cpp.o: undefined symbol: StepData_FreeFormEntity::StepData_FreeFormEntity()
  if theClass.decl_string == "StepData_FreeFormEntity":
    return False

  # error: /opencascade.js/build/bindings/StepData/StepData_UndefinedEntity.hxx/StepData_UndefinedEntity.cpp.o: undefined symbol: StepData_UndefinedEntity::Super() const
  if theClass.decl_string == "StepData_UndefinedEntity":
    return False

  # error: /opencascade.js/build/bindings/HLRBRep/HLRBRep_Surface.hxx/HLRBRep_Surface.cpp.o: undefined symbol: HLRBRep_Surface::UIntervalContinuity() const
  if theClass.decl_string == "HLRBRep_Surface":
    return False

  # error: /opencascade.js/build/bindings/HLRBRep/HLRBRep_ThePolyhedronOfInterCSurf.hxx/HLRBRep_ThePolyhedronOfInterCSurf.cpp.o: undefined symbol: HLRBRep_ThePolyhedronOfInterCSurf::UMinSingularity(bool)
  if theClass.decl_string == "HLRBRep_ThePolyhedronOfInterCSurf":
    return False

  # error: /opencascade.js/build/bindings/HLRBRep/HLRBRep_TheCurveLocatorOfTheProjPCurOfCInter.hxx/HLRBRep_TheCurveLocatorOfTheProjPCurOfCInter.cpp.o: undefined symbol: HLRBRep_TheCurveLocatorOfTheProjPCurOfCInter::Locate(void* const&, void* const&, int, int, Extrema_POnCurv2d&, Extrema_POnCurv2d&)
  if theClass.decl_string == "HLRBRep_TheCurveLocatorOfTheProjPCurOfCInter":
    return False

  # error: /opencascade.js/build/bindings/IntCurveSurface/IntCurveSurface_ThePolyhedronOfHInter.hxx/IntCurveSurface_ThePolyhedronOfHInter.cpp.o: undefined symbol: IntCurveSurface_ThePolyhedronOfHInter::UMinSingularity(bool)
  if theClass.decl_string == "IntCurveSurface_ThePolyhedronOfHInter":
    return False

  # error: /opencascade.js/build/bindings/IntPolyh/IntPolyh_MaillageAffinage.hxx/IntPolyh_MaillageAffinage.cpp.o: undefined symbol: IntPolyh_MaillageAffinage::GetFinTE(int) const
  if theClass.decl_string == "IntPolyh_MaillageAffinage":
    return False

  # error: /opencascade.js/build/bindings/IGESSelect/IGESSelect_SelectBasicGeom.hxx/IGESSelect_SelectBasicGeom.cpp.o: undefined symbol: IGESSelect_SelectBasicGeom::CurvesOnly() const
  if theClass.decl_string == "IGESSelect_SelectBasicGeom":
    return False

  # error: /opencascade.js/build/bindings/ShapeFix/ShapeFix_WireSegment.hxx/ShapeFix_WireSegment.cpp.o: undefined symbol: ShapeFix_WireSegment::ShapeFix_WireSegment(TopoDS_Wire const&, TopAbs_Orientation)
  if theClass.decl_string == "ShapeFix_WireSegment":
    return False

  # error: /opencascade.js/build/bindings/StepFEA/StepFEA_SymmetricTensor43d.hxx/StepFEA_SymmetricTensor43d.cpp.o: undefined symbol: StepFEA_SymmetricTensor43d::SetFeaIsotropicSymmetricTensor43d(opencascade::handle<TColStd_HArray1OfReal> const&)
  if theClass.decl_string == "StepFEA_SymmetricTensor43d":
    return False

  # error: /opencascade.js/build/bindings/IFSelect/IFSelect_EditForm.hxx/IFSelect_EditForm.cpp.o: undefined symbol: IFSelect_EditForm::NbTouched() const
  if theClass.decl_string == "IFSelect_EditForm":
    return False

  # error: /opencascade.js/build/bindings/IFSelect/IFSelect_IntParam.hxx/IFSelect_IntParam.cpp.o: undefined symbol: IFSelect_IntParam::StaticName() const
  if theClass.decl_string == "IFSelect_IntParam":
    return False

  # error: /opencascade.js/build/bindings/IFSelect/IFSelect_ContextModif.hxx/IFSelect_ContextModif.cpp.o: undefined symbol: IFSelect_ContextModif::Search(opencascade::handle<Standard_Transient> const&, opencascade::handle<Standard_Transient>&) const
  if theClass.decl_string == "IFSelect_ContextModif":
    return False

  # error: error: /opencascade.js/build/bindings/IntTools/IntTools_PntOnFace.hxx/IntTools_PntOnFace.cpp.o: undefined symbol: IntTools_PntOnFace::IsValid() const
  if theClass.decl_string == "IntTools_PntOnFace":
    return False

  # error: /opencascade.js/build/bindings/IntImpParGen/IntImpParGen_ImpTool.hxx/IntImpParGen_ImpTool.cpp.o: undefined symbol: IntImpParGen_ImpTool::Value(double) const
  if theClass.decl_string == "IntImpParGen_ImpTool":
    return False

  # error: incomplete type 'Interface_FileParameter' used in type trait expression
  if theClass.decl_string == "Interface_FileReaderData":
    return False

  # error: incomplete type 'Interface_ShareTool' used in type trait expression
  if theClass.decl_string == "Interface_GeneralModule":
    return False

  # error: incomplete type 'Interface_GTool' used in type trait expression
  if theClass.decl_string == "Interface_HGraph":
    return False

  # error: incomplete type 'Interface_ShareTool' used in type trait expression
  if theClass.decl_string == "RWHeaderSection_GeneralModule":
    return False

  # error: constexpr variable 'types' must be initialized by a constant expression
  if theClass.decl_string == "Prs3d_ToolQuadric":
    return False

  # error: constexpr variable 'types' must be initialized by a constant expression
  if theClass.decl_string == "OSD_FileNode":
    return False

  # error: constexpr variable 'types' must be initialized by a constant expression
  if theClass.decl_string == "OSD_File":
    return False

  # error: no matching function for call to 'operator new'
  if theClass.decl_string == "NCollection_ListNode":
    return False

  # error: no matching function for call to 'operator new'
  if theClass.decl_string == "NCollection_SeqNode":
    return False

  # error: incomplete type 'AVStream' used in type trait expression
  if theClass.decl_string.startswith("Media"):
    return False

  # error: incomplete type 'Interface_ShareTool' used in type trait expression
  if theClass.decl_string == "RWStepAP214_GeneralModule":
    return False

  # error: constexpr variable 'types' must be initialized by a constant expression
  if (
    theClass.decl_string == "RWStepShape_RWBrepWithVoids" or
    theClass.decl_string == "RWStepShape_RWEdgeCurve" or
    theClass.decl_string == "RWStepShape_RWEdgeLoop" or
    theClass.decl_string == "RWStepShape_RWFaceBound"
  ):
    return False

  if (
    theClass.decl_string == "LocOpe_Revol" or
    theClass.decl_string == "QANCollection" or
    theClass.decl_string == "MAT2d_CutCurve" or
    theClass.decl_string == "Law_Interpolate" or
    theClass.decl_string == "LocOpe_RevolutionForm" or
    theClass.decl_string == "MeshTest_CheckTopology" or
    theClass.decl_string == "ProjLib_ProjectOnSurface" or
    theClass.decl_string == "QABugs_PresentableObject" or
    theClass.decl_string == "QABugs" or
    theClass.decl_string == "QADraw" or
    theClass.decl_string == "MeshTest" or
    theClass.decl_string == "OSD_Path" or
    theClass.decl_string == "QADNaming" or
    theClass.decl_string == "MeshTest_CheckTopology"
  ):
    return False

  # error: use of undeclared identifier 'TVertex'; did you mean 'ShapePersistent_BRep::TVertex'?
  if theClass.decl_string == "ShapePersistent_BRep":
    return False

  # error: use of undeclared identifier 'Curve'
  if (
    theClass.decl_string == "ShapePersistent_Geom" or
    theClass.decl_string == "ShapePersistent_Geom2d_Curve" or
    theClass.decl_string == "ShapePersistent_Geom2d" or
    theClass.decl_string == "ShapePersistent_Geom_Curve"
  ):
    return False

  # error: use of undeclared identifier 'Surface'
  if theClass.decl_string == "ShapePersistent_Geom_Surface":
    return False

  # error: unknown type name ...
  if (
    theClass.decl_string == "ShapePersistent_Poly" or
    theClass.decl_string == "ShapePersistent_TopoDS" or
    theClass.decl_string == "StdPersistent_TopLoc"
  ):
    return False

  # error: incomplete type 'Interface_ShareTool' used in type trait expression
  if theClass.decl_string == "StepData_DefaultGeneral":
    return False

  # error: no suitable member 'operator delete' in 'TDF_LabelNode'
  if theClass.decl_string == "TDF_LabelNode":
    return False

  # error: incomplete type 'Interface_ShareTool' used in type trait expression
  if theClass.decl_string == "StepData_GeneralModule":
    return False

  # error: constexpr variable 'types' must be initialized by a constant expression
  if theClass.decl_string == "TopClass_SolidExplorer":
    return False

  # error: calling function with incomplete return type 'OSD_FileIterator'
  # error: constexpr variable 'types' must be initialized by a constant expression
  if theClass.decl_string == "UTL":
    return False

  # error: non-const lvalue reference to type 'const int **' cannot bind to a temporary of type 'const int **'
  if (
    theClass.decl_string == "VrmlData_IndexedFaceSet" or
    theClass.decl_string == "VrmlData_IndexedLineSet" or
    theClass.decl_string == "VrmlData_Scene"
  ):
    return False

  # error: duplicate symbol: DISCRETALGO
  if theClass.decl_string == "XBRepMesh":
    return False

  # error: error: undefined symbol: _ZN12TransferBRep9BRepCheckERK12TopoDS_Shapei (referenced by top-level compiled C/C++ code)
  if theClass.decl_string == "TransferBRep":
    return False

  if (
    theClass.decl_string == "math_NewtonMinimum" or
    theClass.decl_string == "math_NewtonFunctionSetRoot"
  ):
    return False

  # error: allocating an object of abstract class type
  if (
    theClass.decl_string == "Graphic3d_CubeMap" or
    theClass.decl_string == "Storage_BaseDriver"
  ):
    return False

  # error: undefined symbol: _ZN18GeomFill_NSectionsC2ERK20NCollection_SequenceIN11opencascade6handleI10Geom_CurveEEERKS0_IdEdd (referenced by top-level compiled C/C++ code)
  if theClass.decl_string == "GeomFill_NSections":
    return False

  # error: expected unqualified-id
  if (
    theClass.decl_string == "math_IntegerVector" or
    theClass.decl_string == "math_Matrix" or
    theClass.decl_string == "math_Vector"
  ):
    return False

  # error: allocating an object of abstract class type 'AIS_Dimension'
  if theClass.decl_string == "AIS_Dimension":
    return False

  # error: undefined symbol
  if (
    theClass.decl_string == "IntPatch_Polyhedron" or
    theClass.decl_string == "IntPatch_RLine" or
    theClass.decl_string == "Xw_Window"
  ):
    return False

  if (
    theClass.decl_string == "BOPTest_Objects" or
    theClass.decl_string == "BOPTest_DrawableShape" or
    theClass.decl_string == "BOPTest" or
    theClass.decl_string == "Draw_Drawable3D" or
    theClass.decl_string == "DBRep_DrawableShape"
  ):
    return False

  # error: no template named 'handle'; did you mean 'opencascade::handle'?
  if theClass.decl_string in [
    "StepKinematics_UnconstrainedPair",
    "StepKinematics_UnconstrainedPairValue"
  ]:
    return False

  return True
