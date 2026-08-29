#ifndef rbfMotionSolver_H
#define rbfMotionSolver_H

#include "displacementMotionSolver.H"
#include "fvMotionSolver.H"

namespace Foam
{

class rbfMotionSolver
:
    public displacementMotionSolver,
    public fvMotionSolver
{
    mutable volVectorField cellDisplacement_;
    label movingPatchId_;
    label controlStride_;
    scalar supportRadius_;
    mutable labelList controlPointIds_;
    mutable pointField controlPoints_;
    mutable vectorField controlDisplacements_;

    void buildControls() const;
    void updateDisplacement() const;

public:
    TypeName("rbfDisplacement");

    rbfMotionSolver(const word&, const polyMesh&, const dictionary&);
    rbfMotionSolver(const rbfMotionSolver&) = delete;
    ~rbfMotionSolver();

    volVectorField& cellDisplacement() { return cellDisplacement_; }
    const volVectorField& cellDisplacement() const { return cellDisplacement_; }
    tmp<pointField> curPoints() const override;
    void solve() override;
    void topoChange(const polyTopoChangeMap&) override;
    void mapMesh(const polyMeshMap&) override;
    void operator=(const rbfMotionSolver&) = delete;
};

}

#endif
