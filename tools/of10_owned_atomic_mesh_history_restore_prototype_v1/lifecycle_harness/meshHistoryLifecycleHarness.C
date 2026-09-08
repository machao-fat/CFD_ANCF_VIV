#include "fvCFD.H"
#include "dynamicFvMesh.H"
#include "meshHistoryCheckpoint.H"

#include <iomanip>

namespace
{

Foam::scalar checksum(const Foam::pointField& points)
{
    Foam::scalar result = 0;
    forAll(points, pointi)
    {
        result += (pointi + 1)
        *(
            points[pointi].x()
          + 3*points[pointi].y()
          + 7*points[pointi].z()
        );
    }
    return result;
}

Foam::scalar checksum(const Foam::surfaceScalarField& field)
{
    Foam::scalar result = 0;
    const Foam::scalarField& values = field.primitiveField();
    forAll(values, facei)
    {
        result += (facei + 1)*values[facei];
    }
    return result;
}

Foam::pointField translated
(
    const Foam::pointField& reference,
    const Foam::scalar displacementY
)
{
    Foam::pointField result(reference);
    forAll(result, pointi)
    {
        result[pointi].y() += displacementY;
    }
    return result;
}

void emit
(
    const Foam::word& event,
    const Foam::fvMesh& mesh,
    const Foam::Time& runTime
)
{
    const bool hasMeshPhi = mesh.foundObject<Foam::surfaceScalarField>("meshPhi");
    const Foam::scalar meshPhiChecksum = hasMeshPhi
        ? checksum(mesh.lookupObject<Foam::surfaceScalarField>("meshPhi"))
        : 0;
    Foam::Info
        << event
        << " time=" << std::setprecision(17) << runTime.value()
        << " timeIndex=" << runTime.timeIndex()
        << " pointsChecksum=" << checksum(mesh.points())
        << " oldPointsChecksum=" << checksum(mesh.oldPoints())
        << " meshPhiPresent=" << hasMeshPhi
        << " meshPhiChecksum=" << meshPhiChecksum
        << Foam::nl;
}

}

int main(int argc, char *argv[])
{
    Foam::argList::addNote
    (
        "OF10-owned mesh-history checkpoint/restore lifecycle harness"
    );

    #include "setRootCase.H"
    #include "createTime.H"

    Foam::autoPtr<Foam::dynamicFvMesh> meshPtr
    (
        Foam::dynamicFvMesh::New(runTime)
    );
    Foam::fvMesh& mesh = meshPtr();

    const Foam::pointField checkpointPoints(mesh.points());
    Foam::autoPtr<Foam::meshHistoryCheckpoint> checkpoint
    (
        mesh.checkpointMeshHistory()
    );
    emit("CHECKPOINT", mesh, runTime);

    const Foam::label checkpointTimeIndex = runTime.timeIndex();
    const Foam::scalar checkpointTime = runTime.value();

    const auto applyTrial =
    [&]
    (
        const Foam::word& name,
        const Foam::scalar displacementY
    )
    {
        const_cast<Foam::Time&>(runTime).setTime
        (
            checkpointTime + runTime.deltaTValue(),
            checkpointTimeIndex + 1
        );
        mesh.movePoints(translated(checkpointPoints, displacementY));
        emit(name, mesh, runTime);
    };

    const auto restore = [&]()
    {
        const_cast<Foam::Time&>(runTime).setTime
        (
            checkpointTime,
            checkpointTimeIndex
        );
        mesh.restoreMeshHistory(checkpoint());
        emit("RESTORE", mesh, runTime);
    };

    applyTrial("TRIAL_A_PLUS_0P002", 0.002);
    restore();
    applyTrial("TRIAL_B_MINUS_0P002", -0.002);
    restore();
    applyTrial("TRIAL_B_REPEAT_MINUS_0P002", -0.002);

    Foam::Info << "MESH_HISTORY_LIFECYCLE_HARNESS=PASS" << Foam::nl;
    return 0;
}
