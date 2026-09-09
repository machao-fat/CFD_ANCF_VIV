/*---------------------------------------------------------------------------*\
  Read-only OF10 initial-flux compatibility probe.

  It reads a legal 0.100 s case, constructs Uf exactly as the dynamic solver
  does when no persisted Uf file exists, compares persisted phi with Sf & Uf,
  and applies CorrectPhi only to local field copies.  With -moveMesh it may
  call mesh.update()/mesh.move() on the local mesh copy, but never advances
  Time, writes a case field, or starts a CFD solver.
\*---------------------------------------------------------------------------*/

#include "fvCFD.H"
#include "CorrectPhi.H"
#include "pimpleControl.H"
#include "pressureReference.H"

#include <cmath>
#include <fstream>
#include <iomanip>

using namespace Foam;

namespace
{

struct Stats
{
    label count{0};
    scalar minValue{GREAT};
    scalar maxValue{-GREAT};
    scalar maxAbs{0};
    scalar l2{0};
    scalar sum{0};
};


Stats stats(const UList<scalar>& values)
{
    Stats result;
    result.count = values.size();
    forAll(values, i)
    {
        const scalar value = values[i];
        result.minValue = min(result.minValue, value);
        result.maxValue = max(result.maxValue, value);
        result.maxAbs = max(result.maxAbs, mag(value));
        result.l2 += sqr(value);
        result.sum += value;
    }
    result.l2 = std::sqrt(result.l2);
    if (!result.count)
    {
        result.minValue = 0;
        result.maxValue = 0;
    }
    return result;
}


Stats fieldStats(const surfaceScalarField& field)
{
    Stats result = stats(field.primitiveField());
    forAll(field.boundaryField(), patchi)
    {
        const Stats patchStats = stats(field.boundaryField()[patchi]);
        result.count += patchStats.count;
        result.minValue = min(result.minValue, patchStats.minValue);
        result.maxValue = max(result.maxValue, patchStats.maxValue);
        result.maxAbs = max(result.maxAbs, patchStats.maxAbs);
        result.l2 = std::sqrt(sqr(result.l2) + sqr(patchStats.l2));
        result.sum += patchStats.sum;
    }
    return result;
}


Stats internalStats(const volScalarField& field)
{
    return stats(field.primitiveField());
}


Stats vectorStats(const UList<vector>& values)
{
    Stats result;
    result.count = values.size();
    forAll(values, i)
    {
        const scalar magnitude = mag(values[i]);
        result.minValue = min(result.minValue, magnitude);
        result.maxValue = max(result.maxValue, magnitude);
        result.maxAbs = max(result.maxAbs, magnitude);
        result.l2 += sqr(magnitude);
        result.sum += magnitude;
    }
    result.l2 = std::sqrt(result.l2);
    if (!result.count)
    {
        result.minValue = 0;
        result.maxValue = 0;
    }
    return result;
}


Stats surfaceVectorStats(const surfaceVectorField& field)
{
    Stats result = vectorStats(field.primitiveField());
    forAll(field.boundaryField(), patchi)
    {
        const Stats patchStats = vectorStats(field.boundaryField()[patchi]);
        result.count += patchStats.count;
        result.minValue = min(result.minValue, patchStats.minValue);
        result.maxValue = max(result.maxValue, patchStats.maxValue);
        result.maxAbs = max(result.maxAbs, patchStats.maxAbs);
        result.l2 = std::sqrt(sqr(result.l2) + sqr(patchStats.l2));
        result.sum += patchStats.sum;
    }
    return result;
}


void writeStats(std::ostream& out, const Stats& value)
{
    out << "{\"count\":" << value.count
        << ",\"min\":" << std::setprecision(17) << value.minValue
        << ",\"max\":" << value.maxValue
        << ",\"max_abs\":" << value.maxAbs
        << ",\"l2\":" << value.l2
        << ",\"sum\":" << value.sum << "}";
}


void writePatchStats
(
    std::ostream& out,
    const surfaceScalarField& field,
    const surfaceScalarField& reference,
    const fvMesh& mesh
)
{
    out << "[";
    forAll(field.boundaryField(), patchi)
    {
        if (patchi) out << ",";
        const Stats values = stats(field.boundaryField()[patchi]);
        const Stats refValues = stats(reference.boundaryField()[patchi]);
        out << "{\"name\":\"" << mesh.boundary()[patchi].name()
            << "\",\"type\":\"" << field.boundaryField()[patchi].type()
            << "\",\"size\":" << field.boundaryField()[patchi].size()
            << ",\"value\":";
        writeStats(out, values);
        out << ",\"reference\":";
        writeStats(out, refValues);
        out << "}";
    }
    out << "]";
}


void writeDifference
(
    std::ostream& out,
    const surfaceScalarField& left,
    const surfaceScalarField& right,
    const fvMesh& mesh
)
{
    surfaceScalarField difference
    (
        IOobject
        (
            "phiDifference",
            mesh.time().timeName(),
            mesh,
            IOobject::NO_READ,
            IOobject::NO_WRITE,
            false
        ),
        left - right
    );
    out << "{\"all\":";
    writeStats(out, fieldStats(difference));
    out << ",\"internal\":";
    writeStats(out, stats(difference.primitiveField()));
    out << ",\"patches\":";
    writePatchStats(out, difference, left, mesh);
    out << "}";
}


scalar boundarySum(const surfaceScalarField& field)
{
    scalar result = 0;
    forAll(field.boundaryField(), patchi)
    {
        forAll(field.boundaryField()[patchi], facei)
        {
            result += field.boundaryField()[patchi][facei];
        }
    }
    return result;
}


void writeDivergence
(
    std::ostream& out,
    const surfaceScalarField& field
)
{
    const tmp<volScalarField> tDiv = fvc::div(field);
    out << "{\"internal\":";
    writeStats(out, internalStats(tDiv()));
    out << "}";
}

}


int main(int argc, char *argv[])
{
    argList::addOption("time", "time", "Initial time directory");
    argList::addOption("output", "file", "External JSON output");
    argList::addBoolOption
    (
        "moveMesh",
        "execute mesh.update() and mesh.move() in the local diagnostic only"
    );
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

    volScalarField p
    (
        IOobject("p", runTime.timeName(), mesh, IOobject::MUST_READ, IOobject::NO_WRITE, false),
        mesh
    );
    volVectorField U
    (
        IOobject("U", runTime.timeName(), mesh, IOobject::MUST_READ, IOobject::NO_WRITE, false),
        mesh
    );

    // This is the exact READ_IF_PRESENT + fvc::flux(U) construction in
    // createPhi.H.  No getter creates an oldTime layer here.
    surfaceScalarField persistedPhi
    (
        IOobject("phi", runTime.timeName(), mesh, IOobject::READ_IF_PRESENT, IOobject::NO_WRITE),
        fvc::flux(U)
    );

    // This is the dynamic createUfIfPresent.H fallback when 0.1/Uf is absent.
    surfaceVectorField Uf
    (
        IOobject("Uf", runTime.timeName(), mesh, IOobject::READ_IF_PRESENT, IOobject::NO_WRITE),
        fvc::interpolate(U)
    );

    const bool movedMesh = args.optionFound("moveMesh");
    if (movedMesh)
    {
        // Match the production ordering without changing the physical time
        // or entering a CFD equation solve.  This is a local mesh copy.
        mesh.update();
        mesh.move();
    }

    surfaceScalarField reconstructedPhi
    (
        IOobject("reconstructedPhi", runTime.timeName(), mesh, IOobject::NO_READ, IOobject::NO_WRITE, false),
        mesh.Sf() & Uf
    );
    surfaceScalarField correctedPhi(reconstructedPhi);
    volVectorField localU(U);

    // Run the actual Foundation CorrectPhi operator only on local copies.
    // No additional mesh.move(), runTime++ or field write is performed.
    pimpleControl pimple(mesh);
    pressureReference pressureReference(p, pimple.dict());
    const label refCell = pressureReference.refCell();
    const scalar refValue = pressureReference.refValue();
    correctUphiBCs(localU, correctedPhi, true);
    CorrectPhi
    (
        correctedPhi,
        localU,
        p,
        dimensionedScalar("rAUf", dimTime, 1),
        geometricZeroField(),
        pressureReference,
        pimple
    );
    fvc::makeRelative(correctedPhi, localU);

    const bool meshPhiPresent =
        mesh.foundObject<surfaceScalarField>("meshPhi");

    std::ofstream output(outputName.c_str());
    output << std::setprecision(17);
    output << "{\"schema_version\":\"of10-initial-phi-uf-compatibility-probe-v1\""
           << ",\"read_only\":true"
           << ",\"time_name\":\"" << timeName << "\""
           << ",\"time_value\":" << runTime.value()
           << ",\"time_index\":" << runTime.timeIndex()
           << ",\"mesh_move_called\":" << (movedMesh ? "true" : "false")
           << ",\"mesh_moving\":" << (mesh.moving() ? "true" : "false")
           << ",\"mesh_changing\":" << (mesh.changing() ? "true" : "false")
           << ",\"persisted_phi_present\":true"
           << ",\"uf_source\":\"fvc::interpolate(U)\""
           << ",\"uf_persisted_file_present\":false"
           << ",\"Uf_magnitude\":";
    writeStats(output, surfaceVectorStats(Uf));
    output << ",\"meshPhi_present\":" << (meshPhiPresent ? "true" : "false");
    if (meshPhiPresent)
    {
        output << ",\"meshPhi\":";
        writeStats
        (
            output,
            fieldStats(mesh.lookupObject<surfaceScalarField>("meshPhi"))
        );
    }
    else
    {
        output << ",\"meshPhi\":null";
    }
    output
           << ",\"U_internal_magnitude\":";
    writeStats(output, vectorStats(U.primitiveField()));
    output << ",\"p_internal\":";
    writeStats(output, stats(p.primitiveField()));
    output << ",\"persisted_phi\":";
    writeStats(output, fieldStats(persistedPhi));
    output << ",\"reconstructed_phi\":";
    writeStats(output, fieldStats(reconstructedPhi));
    output << ",\"corrected_phi\":";
    writeStats(output, fieldStats(correctedPhi));
    output << ",\"persisted_vs_reconstructed\":";
    writeDifference(output, persistedPhi, reconstructedPhi, mesh);
    output << ",\"reconstructed_vs_corrected\":";
    writeDifference(output, reconstructedPhi, correctedPhi, mesh);
    output << ",\"persisted_vs_corrected\":";
    writeDifference(output, persistedPhi, correctedPhi, mesh);
    output << ",\"persisted_boundary_sum\":" << boundarySum(persistedPhi)
           << ",\"reconstructed_boundary_sum\":" << boundarySum(reconstructedPhi)
           << ",\"corrected_boundary_sum\":" << boundarySum(correctedPhi)
           << ",\"persisted_divergence\":";
    writeDivergence(output, persistedPhi);
    output << ",\"reconstructed_divergence\":";
    writeDivergence(output, reconstructedPhi);
    output << ",\"corrected_divergence\":";
    writeDivergence(output, correctedPhi);
    output << ",\"pressure_reference\":{\"ref_cell\":" << refCell
           << ",\"ref_value\":" << refValue << "}"
           << "}\n";

    return output.good() ? 0 : 1;
}
