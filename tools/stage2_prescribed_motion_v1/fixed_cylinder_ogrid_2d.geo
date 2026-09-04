// Stage 2: 2-D structured O-grid near field with a separate outer fluid zone.
// The inner annulus is intended to move rigidly with the cylinder; the outer
// rectangle is the stationary/deforming far field in Fluent.
SetFactory("Built-in");

DefineConstant[
  lcFar = {0.30, Name "Parameters/lcFar"},
  lcOuter = {0.18, Name "Parameters/lcOuter"},
  rCylinder = {0.50, Name "Parameters/rCylinder"},
  rInterface = {2.50, Name "Parameters/rInterface"},
  nRadial = {12, Name "Parameters/nRadial"},
  nTheta = {9, Name "Parameters/nTheta"}
];

// Far-field rectangle: x in [-5,10], y in [-5,5].
Point(1) = {-5,-5,0,lcFar};
Point(2) = {10,-5,0,lcFar};
Point(3) = {10,5,0,lcFar};
Point(4) = {-5,5,0,lcFar};
Line(1) = {1,2};
Line(2) = {2,3};
Line(3) = {3,4};
Line(4) = {4,1};

// Eight equally spaced points on the cylinder and interface circles.
Point(100) = {0,0,0,lcOuter};
For i In {0:7}
  theta = i*Pi/4;
  Point(10+i) = {rCylinder*Cos(theta), rCylinder*Sin(theta), 0, lcOuter};
  Point(20+i) = {rInterface*Cos(theta), rInterface*Sin(theta), 0, lcOuter};
EndFor

// Inner and outer circular arcs. Adjacent annular blocks share each radial
// curve; defining a second reversed copy would create duplicate mesh nodes.
// Each block has 9 points per arc and 12 points radially.
For i In {0:7}
  j = (i+1) % 8;
  Circle(100+i) = {10+i,100,10+j};
  Circle(200+i) = {20+i,100,20+j};
  Line(300+i) = {10+i,20+i};
  Transfinite Curve {100+i,200+i} = nTheta;
  Transfinite Curve {300+i} = nRadial;
EndFor

// All radial curves must exist before a sector references the next one.
For i In {0:7}
  j = (i+1) % 8;
  // inner i -> outer i -> outer j -> inner j -> inner i.  The third edge
  // is the next shared radial curve in reverse orientation.
  Line Loop(500+i) = {300+i,200+i,-(300+j),-(100+i)};
  Plane Surface(600+i) = {500+i};
  Transfinite Surface {600+i};
  Recombine Surface {600+i};
EndFor

// Outer fluid region with the circular interface as a hole.
Line Loop(1) = {1,2,3,4};
Line Loop(2) = {-207,-206,-205,-204,-203,-202,-201,-200};
Plane Surface(700) = {1,2};
Field[1] = Distance;
Field[1].CurvesList = {1,2,3,4,200,201,202,203,204,205,206,207};
Field[2] = Threshold;
Field[2].InField = 1;
Field[2].LcMin = lcOuter;
Field[2].LcMax = lcFar;
Field[2].DistMin = 0.5;
Field[2].DistMax = 3.0;
Background Field = 2;
Mesh.Algorithm = 6;
Mesh.MeshSizeFromCurvature = 1;
Mesh.MeshSizeExtendFromBoundary = 1;
Mesh.Optimize = 1;

Physical Curve("inlet") = {4};
Physical Curve("outlet") = {2};
Physical Curve("upper") = {3};
Physical Curve("lower") = {1};
Physical Curve("cylinder") = {100,101,102,103,104,105,106,107};
Physical Curve("motionInterface") = {200,201,202,203,204,205,206,207};
Physical Surface("movingFluid") = {600,601,602,603,604,605,606,607};
Physical Surface("outerFluid") = {700};
