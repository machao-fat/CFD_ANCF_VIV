// Stage 2: one-cell-thick, quasi-2-D O-grid for OpenFOAM/Fluent exchange.
// The x-y geometry is identical to fixed_cylinder_ogrid_2d.geo.  z spans
// [0,1] with a single layer; front/back are symmetry planes.
SetFactory("Built-in");

DefineConstant[
  lcFar = {0.30, Name "Parameters/lcFar"},
  lcOuter = {0.18, Name "Parameters/lcOuter"},
  rCylinder = {0.50, Name "Parameters/rCylinder"},
  rInterface = {2.50, Name "Parameters/rInterface"},
  nRadial = {12, Name "Parameters/nRadial"},
  nTheta = {9, Name "Parameters/nTheta"},
  thickness = {1.0, Name "Parameters/thickness"}
];

Point(1) = {-5,-5,0,lcFar};
Point(2) = {10,-5,0,lcFar};
Point(3) = {10,5,0,lcFar};
Point(4) = {-5,5,0,lcFar};
Line(1) = {1,2};
Line(2) = {2,3};
Line(3) = {3,4};
Line(4) = {4,1};

Point(100) = {0,0,0,lcOuter};
For i In {0:7}
  theta = i*Pi/4;
  Point(10+i) = {rCylinder*Cos(theta), rCylinder*Sin(theta), 0, lcOuter};
  Point(20+i) = {rInterface*Cos(theta), rInterface*Sin(theta), 0, lcOuter};
EndFor

For i In {0:7}
  j = (i+1) % 8;
  Circle(100+i) = {10+i,100,10+j};
  Circle(200+i) = {20+i,100,20+j};
  Line(300+i) = {10+i,20+i};
  Transfinite Curve {100+i,200+i} = nTheta;
  Transfinite Curve {300+i} = nRadial;
EndFor

For i In {0:7}
  j = (i+1) % 8;
  Line Loop(500+i) = {300+i,200+i,-(300+j),-(100+i)};
  Plane Surface(600+i) = {500+i};
  Transfinite Surface {600+i};
  Recombine Surface {600+i};
EndFor

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

// Each sector returns [top, volume, radial, interface, radial, cylinder].
// The final outer surface returns [top, volume, lower, outlet, upper, inlet,
// interface x8]. Shared radial faces remain internal and are unnamed.
out[] = Extrude {0,0,thickness} {
  Surface{600,601,602,603,604,605,606,607,700}; Layers{1}; Recombine;
};

Physical Volume("movingFluid") = {out[1],out[7],out[13],out[19],out[25],out[31],out[37],out[43]};
Physical Volume("outerFluid") = {out[49]};
Physical Surface("front") = {600,601,602,603,604,605,606,607,700};
Physical Surface("back") = {out[0],out[6],out[12],out[18],out[24],out[30],out[36],out[42],out[48]};

Physical Surface("motionInterface") = {out[3],out[9],out[15],out[21],out[27],out[33],out[39],out[45],out[54],out[55],out[56],out[57],out[58],out[59],out[60],out[61]};
Physical Surface("cylinder") = {out[5],out[11],out[17],out[23],out[29],out[35],out[41],out[47]};
Physical Surface("lower") = {out[50]};
Physical Surface("outlet") = {out[51]};
Physical Surface("upper") = {out[52]};
Physical Surface("inlet") = {out[53]};
