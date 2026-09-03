// 2D Fluent companion mesh: same geometry and sizing as the OpenFOAM source.
DefineConstant[
  lcFar = {0.50, Name "Parameters/lcFar"}
  lcWall = {0.08, Name "Parameters/lcWall"}
];
Point(1) = {-5, -5, 0, lcFar};
Point(2) = {10, -5, 0, lcFar};
Point(3) = {10,  5, 0, lcFar};
Point(4) = {-5,  5, 0, lcFar};
Point(9) = {0, 0, 0, lcWall};
Point(10) = { 0.5, 0, 0, lcWall};
Point(11) = { 0.3535533906,  0.3535533906, 0, lcWall};
Point(12) = { 0, 0.5, 0, lcWall};
Point(13) = {-0.3535533906,  0.3535533906, 0, lcWall};
Point(14) = {-0.5, 0, 0, lcWall};
Point(15) = {-0.3535533906, -0.3535533906, 0, lcWall};
Point(16) = { 0,-0.5, 0, lcWall};
Point(17) = { 0.3535533906, -0.3535533906, 0, lcWall};
Line(1) = {1,2}; Line(2) = {2,3}; Line(3) = {3,4}; Line(4) = {4,1};
Circle(101) = {10,9,11}; Circle(102) = {11,9,12};
Circle(103) = {12,9,13}; Circle(104) = {13,9,14};
Circle(105) = {14,9,15}; Circle(106) = {15,9,16};
Circle(107) = {16,9,17}; Circle(108) = {17,9,10};
Line Loop(1) = {1,2,3,4};
Line Loop(2) = {-108,-107,-106,-105,-104,-103,-102,-101};
Plane Surface(1) = {1,2};
Field[1] = Distance; Field[1].CurvesList = {101,102,103,104,105,106,107,108};
Field[2] = Threshold; Field[2].InField = 1; Field[2].LcMin = lcWall;
Field[2].LcMax = lcFar; Field[2].DistMin = 0.25; Field[2].DistMax = 2.5;
Background Field = 2;
Mesh.Algorithm = 6; Mesh.MeshSizeFromCurvature = 1;
Mesh.MeshSizeExtendFromBoundary = 1; Mesh.Optimize = 1;
Physical Curve("lower") = {1};
Physical Curve("outlet") = {2};
Physical Curve("upper") = {3};
Physical Curve("inlet") = {4};
Physical Curve("cylinder") = {101,102,103,104,105,106,107,108};
Physical Surface("fluid") = {1};
