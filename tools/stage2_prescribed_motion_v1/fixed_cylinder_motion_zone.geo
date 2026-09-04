// Stage 2 Fluent companion mesh with an explicit rigid-body near field.
// The circle at r=2.5 is an internal face zone; its cells are the motion zone.
DefineConstant[
  lcFar = {0.50, Name "Parameters/lcFar"}
  lcWall = {0.06, Name "Parameters/lcWall"}
  lcMotion = {0.14, Name "Parameters/lcMotion"}
];
Point(1) = {-5,-5,0,lcFar}; Point(2) = {10,-5,0,lcFar};
Point(3) = {10,5,0,lcFar}; Point(4) = {-5,5,0,lcFar};
Point(9) = {0,0,0,lcWall};
Point(10) = {0.5,0,0,lcWall}; Point(11) = {0.3535533906,0.3535533906,0,lcWall};
Point(12) = {0,0.5,0,lcWall}; Point(13) = {-0.3535533906,0.3535533906,0,lcWall};
Point(14) = {-0.5,0,0,lcWall}; Point(15) = {-0.3535533906,-0.3535533906,0,lcWall};
Point(16) = {0,-0.5,0,lcWall}; Point(17) = {0.3535533906,-0.3535533906,0,lcWall};
Point(20) = {2.5,0,0,lcMotion}; Point(21) = {1.767766953,1.767766953,0,lcMotion};
Point(22) = {0,2.5,0,lcMotion}; Point(23) = {-1.767766953,1.767766953,0,lcMotion};
Point(24) = {-2.5,0,0,lcMotion}; Point(25) = {-1.767766953,-1.767766953,0,lcMotion};
Point(26) = {0,-2.5,0,lcMotion}; Point(27) = {1.767766953,-1.767766953,0,lcMotion};
Line(1)={1,2}; Line(2)={2,3}; Line(3)={3,4}; Line(4)={4,1};
Circle(101)={10,9,11}; Circle(102)={11,9,12}; Circle(103)={12,9,13}; Circle(104)={13,9,14};
Circle(105)={14,9,15}; Circle(106)={15,9,16}; Circle(107)={16,9,17}; Circle(108)={17,9,10};
Circle(201)={20,9,21}; Circle(202)={21,9,22}; Circle(203)={22,9,23}; Circle(204)={23,9,24};
Circle(205)={24,9,25}; Circle(206)={25,9,26}; Circle(207)={26,9,27}; Circle(208)={27,9,20};
Line Loop(1)={1,2,3,4};
Line Loop(2)={-108,-107,-106,-105,-104,-103,-102,-101};
Line Loop(3)={201,202,203,204,205,206,207,208};
Plane Surface(1)={1,3};
Plane Surface(2)={3,2};
Field[1]=Distance; Field[1].CurvesList={101,102,103,104,105,106,107,108};
Field[2]=Threshold; Field[2].InField=1; Field[2].LcMin=lcWall; Field[2].LcMax=lcFar;
Field[2].DistMin=0.25; Field[2].DistMax=3.0; Background Field=2;
Mesh.Algorithm=6; Mesh.MeshSizeFromCurvature=1; Mesh.MeshSizeExtendFromBoundary=1; Mesh.Optimize=1;
out[] = Extrude {0,0,1} { Surface{1,2}; Layers{1}; Recombine; };
Physical Volume("outerFluid")={out[1]};
Physical Volume("movingFluid")={out[3]};
Physical Surface("front")={1,2};
Physical Surface("back")={out[0],out[2]};
Physical Surface("lower")={out[4]}; Physical Surface("outlet")={out[5]};
Physical Surface("upper")={out[6]}; Physical Surface("inlet")={out[7]};
Physical Surface("motionInterface")={out[8],out[9],out[10],out[11],out[12],out[13],out[14],out[15]};
Physical Surface("cylinder")={out[16],out[17],out[18],out[19],out[20],out[21],out[22],out[23]};
