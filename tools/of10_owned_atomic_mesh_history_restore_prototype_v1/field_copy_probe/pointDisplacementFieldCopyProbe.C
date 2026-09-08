/*---------------------------------------------------------------------------*\
  No-CFD pointVectorField checkpoint-copy probe for Foundation OpenFOAM 10.
  It reads a real case field and never writes the case, mesh, or live field.
\*---------------------------------------------------------------------------*/

#include "fvCFD.H"
#include "pointMesh.H"
#include "pointFields.H"
#include "valuePointPatchField.H"

#include <cmath>
#include <fstream>
#include <iomanip>

using namespace Foam;

namespace
{

struct Difference
{
    scalar maxAbs{0};
    scalar l2{0};
    label index{-1};
    direction component{0};
};


scalar componentAbs(const vector& value, direction& component)
{
    scalar result = mag(value.x());
    component = 0;
    for (direction cmpt = 1; cmpt < vector::nComponents; ++cmpt)
    {
        const scalar candidate = mag(value.component(cmpt));
        if (candidate > result)
        {
            result = candidate;
            component = cmpt;
        }
    }
    return result;
}


Difference difference(const UList<vector>& expected, const UList<vector>& actual)
{
    if (expected.size() != actual.size())
    {
        FatalErrorInFunction
            << "size mismatch: " << expected.size() << " vs " << actual.size()
            << exit(FatalError);
    }

    Difference result;
    forAll(expected, index)
    {
        const vector delta = actual[index] - expected[index];
        direction component = 0;
        const scalar absValue = componentAbs(delta, component);
        result.l2 += magSqr(delta);
        if (absValue > result.maxAbs)
        {
            result.maxAbs = absValue;
            result.index = index;
            result.component = component;
        }
    }
    result.l2 = std::sqrt(result.l2);
    return result;
}


void writeDifference
(
    std::ostream& output,
    const Difference& value,
    const label count
)
{
    output << "{\"count\":" << count
           << ",\"max_abs\":" << std::setprecision(17) << value.maxAbs
           << ",\"l2\":" << value.l2
           << ",\"max_index\":" << value.index
           << ",\"max_component\":" << value.component << "}";
}


void writeFieldComparison
(
    std::ostream& output,
    const pointVectorField& expected,
    const pointVectorField& actual,
    const pointBoundaryMesh& boundary
)
{
    output << "{\"internal\":";
    writeDifference(output, difference(expected.primitiveField(), actual.primitiveField()), expected.size());
    output << ",\"patches\":[";
    forAll(expected.boundaryField(), patchi)
    {
        if (patchi)
        {
            output << ',';
        }
        const pointPatchField<vector>& expectedPatch = expected.boundaryField()[patchi];
        const pointPatchField<vector>& actualPatch = actual.boundaryField()[patchi];
        output << "{\"name\":\"" << boundary[patchi].name()
               << "\",\"expected_type\":\"" << expectedPatch.type()
               << "\",\"actual_type\":\"" << actualPatch.type() << "\",";
        const auto* expectedValue = dynamic_cast<const valuePointPatchField<vector>*>(&expectedPatch);
        const auto* actualValue = dynamic_cast<const valuePointPatchField<vector>*>(&actualPatch);
        if (expectedValue != nullptr && actualValue != nullptr)
        {
            output << "\"value_storage\":\"valuePointPatchField\",\"values\":";
            writeDifference
            (
                output,
                difference
                (
                    static_cast<const Field<vector>&>(*expectedValue),
                    static_cast<const Field<vector>&>(*actualValue)
                ),
                expectedValue->size()
            );
        }
        else
        {
            output << "\"value_storage\":\"NOT_VALUE_BACKED\"";
        }
        output << "}";
    }
    output << "]}";
}


bool fieldEqual(const pointVectorField& expected, const pointVectorField& actual)
{
    if (difference(expected.primitiveField(), actual.primitiveField()).maxAbs != 0)
    {
        return false;
    }
    forAll(expected.boundaryField(), patchi)
    {
        const pointPatchField<vector>& expectedPatch = expected.boundaryField()[patchi];
        const pointPatchField<vector>& actualPatch = actual.boundaryField()[patchi];
        if (expectedPatch.type() != actualPatch.type())
        {
            return false;
        }
        const auto* expectedValue = dynamic_cast<const valuePointPatchField<vector>*>(&expectedPatch);
        const auto* actualValue = dynamic_cast<const valuePointPatchField<vector>*>(&actualPatch);
        if ((expectedValue == nullptr) != (actualValue == nullptr))
        {
            return false;
        }
        if
        (
            expectedValue != nullptr
         && difference
            (
                static_cast<const Field<vector>&>(*expectedValue),
                static_cast<const Field<vector>&>(*actualValue)
            ).maxAbs != 0
        )
        {
            return false;
        }
    }
    return true;
}


void writeMethod
(
    std::ostream& output,
    const word& method,
    const pointVectorField& live,
    const pointVectorField& candidate,
    const pointBoundaryMesh& boundary
)
{
    output << "\"" << method << "\":";
    writeFieldComparison(output, live, candidate, boundary);
}

} // End anonymous namespace


int main(int argc, char *argv[])
{
    argList::addOption("time", "time", "Existing time directory to read");
    argList::addOption("output", "file", "JSON evidence output path");
    #include "setRootCase.H"
    #include "createTime.H"

    const word timeName(args.optionLookupOrDefault<word>("time", runTime.timeName()));
    runTime.setTime(instant(timeName), runTime.timeIndex());
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
    const pointMesh& points = pointMesh::New(mesh);
    pointVectorField live
    (
        IOobject
        (
            "pointDisplacement",
            runTime.timeName(),
            points.thisDb(),
            IOobject::MUST_READ,
            IOobject::NO_WRITE,
            false
        ),
        points
    );

    pointVectorField copyConstructed(live);
    pointVectorField forcedAssignment(live);
    forcedAssignment == live;
    pointVectorField ordinaryAssignment(live);
    ordinaryAssignment = live;
    pointVectorField resetAssignment(live);
    resetAssignment.reset(tmp<pointVectorField>(live));

    // Exercise the restore direction without ever mutating the registered live
    // field.  The manipulated target is a local copy with the same patch types.
    pointVectorField forcedRestore(live);
    forcedRestore.primitiveFieldRef() = vector(1.0, -2.0, 3.0);
    forcedRestore.boundaryFieldRef() == vector(1.0, -2.0, 3.0);
    forcedRestore == copyConstructed;

    pointVectorField resetRestore(live);
    resetRestore.primitiveFieldRef() = vector(1.0, -2.0, 3.0);
    resetRestore.boundaryFieldRef() == vector(1.0, -2.0, 3.0);
    resetRestore.reset(tmp<pointVectorField>(copyConstructed));

    const fileName outputPath
    (
        args.optionLookupOrDefault<fileName>
        (
            "output",
            runTime.path()/"pointDisplacement_field_copy_probe.json"
        )
    );
    std::ofstream output(outputPath.c_str());
    if (!output.good())
    {
        FatalErrorInFunction << "cannot open " << outputPath << exit(FatalError);
    }
    output << "{\"case\":\"" << runTime.path()
           << "\",\"time\":\"" << runTime.timeName()
           << "\",\"live_old_time_levels\":" << live.nOldTimes()
           << ",\"methods\":{";
    writeMethod(output, "copy_constructor", live, copyConstructed, points.boundary()); output << ',';
    writeMethod(output, "forced_operator_eq", live, forcedAssignment, points.boundary()); output << ',';
    writeMethod(output, "ordinary_operator_assign", live, ordinaryAssignment, points.boundary()); output << ',';
    writeMethod(output, "reset", live, resetAssignment, points.boundary()); output << ',';
    writeMethod(output, "forced_restore", live, forcedRestore, points.boundary()); output << ',';
    writeMethod(output, "reset_restore", live, resetRestore, points.boundary());
    output << "}}\n";
    output.close();

    const bool pass =
        fieldEqual(live, copyConstructed)
     && fieldEqual(live, forcedAssignment)
     && fieldEqual(live, ordinaryAssignment)
     && fieldEqual(live, resetAssignment)
     && fieldEqual(live, forcedRestore)
     && fieldEqual(live, resetRestore);

    Info<< "POINT_DISPLACEMENT_FIELD_COPY_PROBE=" << (pass ? "PASS" : "FAIL") << nl;
    return pass ? 0 : 1;
}
