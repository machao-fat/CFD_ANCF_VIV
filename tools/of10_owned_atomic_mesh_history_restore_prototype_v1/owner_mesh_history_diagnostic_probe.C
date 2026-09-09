/*---------------------------------------------------------------------------*\
  Read-only proof harness for the owner mesh-history diagnostic.  It creates
  an fvMesh from an existing case, calls the diagnostic twice and compares the
  value snapshots.  It does not construct a solver, move the mesh or call a
  demand-driven mesh-history getter.
\*---------------------------------------------------------------------------*/

#include "argList.H"
#include "fvMesh.H"
#include "meshHistoryCheckpoint.H"
#include "IOobject.H"
#include "Time.H"

namespace
{

bool equalScalar
(
    const Foam::meshHistoryScalarDiagnostic& left,
    const Foam::meshHistoryScalarDiagnostic& right
)
{
    return
        left.present == right.present
     && left.size == right.size
     && left.finite == right.finite
     && left.minValue == right.minValue
     && left.maxValue == right.maxValue
     && left.nOldTimes == right.nOldTimes
     && left.fingerprint == right.fingerprint;
}

bool equalPoints
(
    const Foam::meshHistoryPointDiagnostic& left,
    const Foam::meshHistoryPointDiagnostic& right
)
{
    return
        left.present == right.present
     && left.size == right.size
     && left.finite == right.finite
     && left.maxComponentAbs == right.maxComponentAbs
     && left.fingerprint == right.fingerprint;
}

bool equalState
(
    const Foam::meshHistoryStateDiagnostic& left,
    const Foam::meshHistoryStateDiagnostic& right
)
{
    return
        left.moving == right.moving
     && left.curMotionTimeIndex == right.curMotionTimeIndex
     && left.curTimeIndex == right.curTimeIndex
     && left.storeOldCellCentres == right.storeOldCellCentres
     && equalPoints(left.oldPoints, right.oldPoints)
     && equalPoints(left.oldCellCentres, right.oldCellCentres)
     && equalScalar(left.V0, right.V0)
     && equalScalar(left.V00, right.V00)
     && equalScalar(left.meshPhi, right.meshPhi);
}

}

int main(int argc, char *argv[])
{
    Foam::argList::addNote
    (
        "Non-lazy owner mesh-history diagnostic side-effect probe"
    );
    Foam::argList args(argc, argv);
    Foam::Time runTime(Foam::Time::controlDictName, args);
    Foam::fvMesh mesh
    (
        Foam::IOobject
        (
            Foam::polyMesh::defaultRegion,
            runTime.timeName(),
            runTime
        ),
        false
    );

    const Foam::meshHistoryStateDiagnostic before
    (
        mesh.meshHistoryDiagnostic()
    );
    const Foam::meshHistoryStateDiagnostic after
    (
        mesh.meshHistoryDiagnostic()
    );

    const bool unchanged = equalState(before, after);
    Foam::Info
        << "OWNER_MESH_HISTORY_DIAGNOSTIC_PROBE="
        << (unchanged ? "PASS" : "FAIL") << Foam::nl
        << "before: curMotion=" << before.curMotionTimeIndex
        << " curTime=" << before.curTimeIndex
        << " V0_present=" << before.V0.present
        << " V00_present=" << before.V00.present
        << " meshPhi_present=" << before.meshPhi.present
        << " oldPoints_present=" << before.oldPoints.present
        << " oldCellCentres_present=" << before.oldCellCentres.present
        << Foam::endl;

    return unchanged ? 0 : 1;
}
