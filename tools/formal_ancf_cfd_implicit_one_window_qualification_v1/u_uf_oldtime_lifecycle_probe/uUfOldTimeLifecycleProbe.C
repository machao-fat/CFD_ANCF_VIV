/*---------------------------------------------------------------------------*\
  No-CFD reproduction of the generic U/Uf restore oldTime branch in the
  production adapter.  It reads a real .100 case but only mutates local,
  unregistered field copies.  It writes JSON evidence outside the case.
\*---------------------------------------------------------------------------*/

#include "fvCFD.H"

#include <cmath>
#include <fstream>

using namespace Foam;

namespace
{

struct Difference
{
    scalar maxAbs{0};
    scalar l2{0};
    label count{0};
};


Difference difference(const UList<vector>& expected, const UList<vector>& actual)
{
    if (expected.size() != actual.size())
    {
        FatalErrorInFunction << "field size mismatch" << exit(FatalError);
    }

    Difference result;
    result.count = expected.size();
    forAll(expected, index)
    {
        const vector delta = actual[index] - expected[index];
        result.maxAbs = max(result.maxAbs, max(mag(delta.x()), max(mag(delta.y()), mag(delta.z()))));
        result.l2 += magSqr(delta);
    }
    result.l2 = std::sqrt(result.l2);
    return result;
}


template<class GeoField>
Difference fullDifference(const GeoField& expected, const GeoField& actual)
{
    Difference result = difference(expected.primitiveField(), actual.primitiveField());
    forAll(expected.boundaryField(), patchi)
    {
        const Difference patch = difference(expected.boundaryField()[patchi], actual.boundaryField()[patchi]);
        result.maxAbs = max(result.maxAbs, patch.maxAbs);
        result.l2 = std::sqrt(sqr(result.l2) + sqr(patch.l2));
        result.count += patch.count;
    }
    return result;
}


void writeDifference(Ostream& output, const Difference& value)
{
    output << "{\"count\":" << value.count
           << ",\"max_abs\":" << value.maxAbs
           << ",\"l2\":" << value.l2 << "}";
}


template<class GeoField>
bool exercise
(
    Time& runTime,
    const GeoField& live,
    const scalar checkpointTime,
    const label checkpointTimeIndex,
    const scalar trialTime,
    const label trialTimeIndex,
    Ostream& output
)
{
    GeoField checkpoint(live);
    GeoField trial(live);

    runTime.setTime(instant(trialTime), trialTimeIndex);

    // This creates the real OF10 lazy history from the checkpoint current
    // value. The following local mutation represents a rejected trial.
    trial.oldTime();
    trial.primitiveFieldRef() += vector(1.0, -2.0, 0.5);
    GeoField rejectedTrial(trial);

    runTime.setTime(instant(checkpointTime), checkpointTimeIndex);

    // Exact generic adapter restore ordering for volVector/surfaceVector.
    trial == checkpoint;
    const label levelsBeforeOldRestore = trial.nOldTimes();
    if (levelsBeforeOldRestore >= 1)
    {
        trial.oldTime() == checkpoint.oldTime();
    }

    const label levelsAfterOldRestore = trial.nOldTimes();
    const Difference currentVsCheckpoint = fullDifference(checkpoint, trial);
    const Difference oldVsCheckpointCurrent =
        levelsAfterOldRestore >= 1 ? fullDifference(checkpoint, trial.oldTime()) : Difference{};
    const Difference oldVsCheckpointOld =
        levelsAfterOldRestore >= 1 ? fullDifference(checkpoint.oldTime(), trial.oldTime()) : Difference{};
    const Difference oldVsRejectedTrial =
        levelsAfterOldRestore >= 1 ? fullDifference(rejectedTrial, trial.oldTime()) : Difference{};

    output << "{\"checkpoint_current_time_index\":" << checkpoint.timeIndex()
           << ",\"checkpoint_old_time_index\":" << checkpoint.oldTime().timeIndex()
           << ",\"restored_current_time_index\":" << trial.timeIndex()
           << ",\"restored_old_time_index\":"
           << (levelsAfterOldRestore >= 1 ? trial.oldTime().timeIndex() : -1)
           << ",\"old_time_levels_before_old_restore\":" << levelsBeforeOldRestore
           << ",\"old_time_levels_after_old_restore\":" << levelsAfterOldRestore
           << ",\"current_vs_checkpoint\":";
    writeDifference(output, currentVsCheckpoint);
    output << ",\"old_vs_checkpoint_current\":";
    writeDifference(output, oldVsCheckpointCurrent);
    output << ",\"old_vs_checkpoint_old\":";
    writeDifference(output, oldVsCheckpointOld);
    output << ",\"old_vs_rejected_trial\":";
    writeDifference(output, oldVsRejectedTrial);
    const bool pass = levelsBeforeOldRestore == 1
        && levelsAfterOldRestore == 1
        && currentVsCheckpoint.maxAbs == 0
        && oldVsCheckpointCurrent.maxAbs == 0
        && oldVsCheckpointOld.maxAbs == 0
        && oldVsRejectedTrial.maxAbs > 0
        && trial.timeIndex() == checkpointTimeIndex
        && trial.oldTime().timeIndex() == checkpointTimeIndex;
    output << ",\"pass\":" << (pass ? "true" : "false") << "}";
    return pass;
}

} // End anonymous namespace


int main(int argc, char *argv[])
{
    argList::addOption("time", "time", "Checkpoint time directory");
    argList::addOption("output", "file", "External JSON output");
    #include "setRootCase.H"
    #include "createTime.H"

    const word timeName(args.optionLookupOrDefault<word>("time", "0.1"));
    const fileName outputName(args.optionLookupOrDefault<fileName>("output", ""));
    if (outputName.empty())
    {
        FatalErrorInFunction << "-output is required" << exit(FatalError);
    }
    runTime.setTime(instant(timeName), 0);

    fvMesh mesh
    (
        IOobject
        (
            fvMesh::defaultRegion,
            runTime.timeName(),
            runTime,
            IOobject::MUST_READ
        )
    );
    volVectorField U
    (
        IOobject("U", runTime.timeName(), mesh, IOobject::MUST_READ, IOobject::NO_WRITE, false),
        mesh
    );
    // In the dynamic pimpleFoam path, createUfIfPresent.H constructs Uf from
    // fvc::interpolate(U) when no persisted Uf file exists.  The formal case
    // has no 0.1/Uf file, so reproduce that construction locally instead of
    // attempting to read a non-existent derived field.
    surfaceVectorField Uf
    (
        IOobject("Uf", runTime.timeName(), mesh, IOobject::NO_READ, IOobject::NO_WRITE, false),
        fvc::interpolate(U)
    );

    OFstream output(outputName);
    output.precision(17);
    output << "{\"schema_version\":\"u-uf-oldtime-lifecycle-probe-v1\""
           // Foam's fileName stream formatting supplies its own JSON-safe
           // quotes.  Do not wrap it again.
           << ",\"case\":" << args.rootPath()/args.caseName()
           << ",\"checkpoint_time\":0.1,\"checkpoint_time_index\":0"
           << ",\"trial_time\":0.105,\"trial_time_index\":1"
           << ",\"U\":";
    const bool uPass = exercise(runTime, U, 0.1, 0, 0.105, 1, output);
    output << ",\"Uf\":";
    const bool ufPass = exercise(runTime, Uf, 0.1, 0, 0.105, 1, output);
    output << ",\"pass\":" << (uPass && ufPass ? "true" : "false") << "}\n";

    return uPass && ufPass ? 0 : 1;
}
