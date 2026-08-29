#include "rbfMotionSolver.H"
#include "addToRunTimeSelectionTable.H"
#include "pointPatchField.H"

namespace Foam
{
    defineTypeNameAndDebug(rbfMotionSolver, 0);
    addToRunTimeSelectionTable(motionSolver, rbfMotionSolver, dictionary);
}

Foam::rbfMotionSolver::rbfMotionSolver
(
    const word& name,
    const polyMesh& mesh,
    const dictionary& dict
)
:
    displacementMotionSolver(name, mesh, dict, typeName),
    fvMotionSolver(mesh),
    cellDisplacement_
    (
        IOobject
        (
            "cellDisplacement",
            mesh.time().timeName(),
            mesh,
            IOobject::READ_IF_PRESENT,
            IOobject::AUTO_WRITE
        ),
        fvMesh_,
        dimensionedVector("cellDisplacement", pointDisplacement_.dimensions(), Zero),
        cellMotionBoundaryTypes<vector>(pointDisplacement_.boundaryField())
    ),
    movingPatchId_
    (
        fvMesh_.boundaryMesh().findPatchID
        (
            coeffDict().lookupOrDefault<word>("movingPatch", "cyl")
        )
    ),
    controlStride_(coeffDict().lookupOrDefault<label>("controlStride", 16)),
    supportRadius_(coeffDict().lookupOrDefault<scalar>("supportRadius", 7.5)),
    controlPointIds_(),
    controlPoints_(),
    controlDisplacements_()
{
    if (movingPatchId_ < 0)
    {
        FatalIOErrorInFunction(coeffDict())
            << "movingPatch was not found" << exit(FatalIOError);
    }
    if (controlStride_ < 1 || supportRadius_ <= SMALL)
    {
        FatalIOErrorInFunction(coeffDict())
            << "controlStride must be positive and supportRadius must be > 0"
            << exit(FatalIOError);
    }
}

Foam::rbfMotionSolver::~rbfMotionSolver() {}

void Foam::rbfMotionSolver::buildControls() const
{
    if (controlPointIds_.size()) return;
    const labelList& patchPoints = fvMesh_.boundaryMesh()[movingPatchId_].meshPoints();
    for (label i = 0; i < patchPoints.size(); i += controlStride_)
    {
        controlPointIds_.append(patchPoints[i]);
    }
    controlPoints_.setSize(controlPointIds_.size());
    controlDisplacements_.setSize(controlPointIds_.size(), Zero);
    forAll(controlPointIds_, i)
    {
        controlPoints_[i] = points0()[controlPointIds_[i]];
    }
}

void Foam::rbfMotionSolver::updateDisplacement() const
{
    buildControls();
    pointDisplacement_.boundaryFieldRef().updateCoeffs();
    const pointPatchField<vector>& pointMoving = pointDisplacement_.boundaryField()[movingPatchId_];
    const vectorField& pointValuesIn = pointMoving.primitiveField();
    const labelList& patchPoints = fvMesh_.boundaryMesh()[movingPatchId_].meshPoints();
    const bool havePointData =
        pointValuesIn.size() == patchPoints.size()
     && gMax(mag(pointValuesIn)) > SMALL;

    // preCICE normally exposes point values through pointDisplacement.  Keep
    // a deterministic face-centre fallback for adapters that expose only the
    // cellDisplacement patch; never index face values with point indices.
    const fvPatchVectorField& moving = cellDisplacement_.boundaryField()[movingPatchId_];
    const vectorField& movingValues = moving.primitiveField();
    const vectorField& faceCentres = moving.patch().Cf();
    forAll(controlPointIds_, i)
    {
        const label localPoint = findIndex(patchPoints, controlPointIds_[i]);
        if (havePointData && localPoint >= 0)
        {
            controlDisplacements_[i] = pointValuesIn[localPoint];
        }
        else
        {
            const point& controlPoint = points0()[controlPointIds_[i]];
            scalar bestDistance = GREAT;
            label nearestFace = -1;
            forAll(faceCentres, facei)
            {
                const scalar distance = magSqr(controlPoint - faceCentres[facei]);
                if (distance < bestDistance)
                {
                    bestDistance = distance;
                    nearestFace = facei;
                }
            }
            controlDisplacements_[i] = nearestFace >= 0 ? movingValues[nearestFace] : Zero;
        }
    }

    vectorField& pointValues = pointDisplacement_.primitiveFieldRef();
    forAll(pointValues, pointi)
    {
        scalar weightSum = 0;
        vector displacement = Zero;
        const scalarField distances(mag(points0()[pointi] - controlPoints_));
        forAll(controlPoints_, i)
        {
            const scalar r = distances[i]/supportRadius_;
            if (r < 1)
            {
                const scalar phi = pow4(1 - r)*(4*r + 1);
                displacement += phi*controlDisplacements_[i];
                weightSum += phi;
            }
        }
        pointValues[pointi] = weightSum > VSMALL ? displacement/weightSum : Zero;
    }

    // Keep all non-moving boundary points fixed and retain the exact
    // displacement supplied on the moving patch.
    forAll(fvMesh_.boundaryMesh(), patchi)
    {
        const labelList& patch = fvMesh_.boundaryMesh()[patchi].meshPoints();
        forAll(patch, j)
        {
            if (patchi != movingPatchId_) pointValues[patch[j]] = Zero;
        }
    }
    forAll(patchPoints, j)
    {
        pointValues[patchPoints[j]] = movingValues[j];
    }

    forAll(cellDisplacement_, celli)
    {
        scalar weightSum = 0;
        vector displacement = Zero;
        const scalarField distances(mag(fvMesh_.C()[celli] - controlPoints_));
        forAll(controlPoints_, i)
        {
            const scalar r = distances[i]/supportRadius_;
            if (r < 1)
            {
                const scalar phi = pow4(1 - r)*(4*r + 1);
                displacement += phi*controlDisplacements_[i];
                weightSum += phi;
            }
        }
        cellDisplacement_[celli] = weightSum > VSMALL ? displacement/weightSum : Zero;
    }
}

Foam::tmp<Foam::pointField> Foam::rbfMotionSolver::curPoints() const
{
    updateDisplacement();
    tmp<pointField> current(points0() + pointDisplacement_.primitiveField());
    pointField& values = current.ref();
    const labelList& moving = fvMesh_.boundaryMesh()[movingPatchId_].meshPoints();
    pointDisplacement_.boundaryFieldRef().updateCoeffs();
    const pointPatchField<vector>& pointMoving = pointDisplacement_.boundaryField()[movingPatchId_];
    const vectorField& pointValuesIn = pointMoving.primitiveField();
    const bool havePointData = pointValuesIn.size() == moving.size() && gMax(mag(pointValuesIn)) > SMALL;
    const fvPatchVectorField& movingField = cellDisplacement_.boundaryField()[movingPatchId_];
    const vectorField& faceCentres = movingField.patch().Cf();
    const vectorField& faceValues = movingField.primitiveField();
    forAll(moving, i)
    {
        scalar bestDistance = GREAT;
        label nearestFace = -1;
        forAll(faceCentres, facei)
        {
            const scalar distance = magSqr(points0()[moving[i]] - faceCentres[facei]);
            if (distance < bestDistance)
            {
                bestDistance = distance;
                nearestFace = facei;
            }
        }
        if (havePointData)
        {
            values[moving[i]] = points0()[moving[i]] + pointValuesIn[i];
        }
        else if (nearestFace >= 0)
        {
            values[moving[i]] = points0()[moving[i]] + faceValues[nearestFace];
        }
    }
    twoDCorrectPoints(values);
    return current;
}

void Foam::rbfMotionSolver::solve()
{
    // The mesh mover calls curPoints() after solve().  Calling movePoints()
    // here would reset the displacement field before curPoints() is queried.
    updateDisplacement();
}

void Foam::rbfMotionSolver::topoChange(const polyTopoChangeMap& map)
{
    displacementMotionSolver::topoChange(map);
    controlPointIds_.clear();
    controlPoints_.clear();
    controlDisplacements_.clear();
}

void Foam::rbfMotionSolver::mapMesh(const polyMeshMap& map)
{
    displacementMotionSolver::mapMesh(map);
    controlPointIds_.clear();
    controlPoints_.clear();
    controlDisplacements_.clear();
}
