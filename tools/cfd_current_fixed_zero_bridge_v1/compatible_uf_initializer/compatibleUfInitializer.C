/*---------------------------------------------------------------------------*\
  Diagnostic counterfactual initial-Uf constructor for the current bridge.

  This utility writes Uf only in an explicitly isolated test case.  It keeps
  the tangential component of fvc::interpolate(U) and changes only the face
  normal component so that Sf & Uf equals the persisted phi.  It never changes
  U, p, phi, mesh points, production source, or production runtime.
\*---------------------------------------------------------------------------*/

#include "fvCFD.H"

#include <cmath>
#include <fstream>
#include <iomanip>

using namespace Foam;

namespace
{

struct ErrorStats
{
    label count{0};
    scalar maxAbs{0};
    scalar l2{0};
    scalar sum{0};
};


void add(ErrorStats& result, const scalar value)
{
    ++result.count;
    result.maxAbs = max(result.maxAbs, mag(value));
    result.l2 += sqr(value);
    result.sum += value;
}


ErrorStats fluxError
(
    const surfaceScalarField& phi,
    const surfaceVectorField& Uf,
    const fvMesh& mesh
)
{
    ErrorStats result;
    const vectorField& Sf = mesh.Sf();
    const scalarField& phiInternal = phi.primitiveField();
    const vectorField& UfInternal = Uf.primitiveField();

    forAll(phiInternal, facei)
    {
        add(result, (Sf[facei] & UfInternal[facei]) - phiInternal[facei]);
    }

    forAll(phi.boundaryField(), patchi)
    {
        const vectorField& patchSf = mesh.Sf().boundaryField()[patchi];
        const scalarField& patchPhi = phi.boundaryField()[patchi];
        const vectorField& patchUf = Uf.boundaryField()[patchi];

        forAll(patchPhi, facei)
        {
            add
            (
                result,
                (patchSf[facei] & patchUf[facei]) - patchPhi[facei]
            );
        }
    }

    result.l2 = std::sqrt(result.l2);
    return result;
}


void writeError(std::ostream& output, const ErrorStats& value)
{
    output << "{\"count\":" << value.count
           << ",\"max_abs\":" << std::setprecision(17) << value.maxAbs
           << ",\"l2\":" << value.l2
           << ",\"sum\":" << value.sum << "}";
}

}


int main(int argc, char *argv[])
{
    argList::addOption("time", "time", "Initial time directory");
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

    // Exact persisted-phi construction used by createPhi.H.
    surfaceScalarField phi
    (
        IOobject("phi", runTime.timeName(), mesh, IOobject::READ_IF_PRESENT, IOobject::NO_WRITE),
        fvc::flux(U)
    );

    // Start from the exact OF10 fallback used when no Uf file exists.
    surfaceVectorField Uf
    (
        IOobject("Uf", runTime.timeName(), mesh, IOobject::NO_READ, IOobject::AUTO_WRITE),
        fvc::interpolate(U)
    );

    const ErrorStats before = fluxError(phi, Uf, mesh);
    const vectorField& Sf = mesh.Sf();
    vectorField& UfInternal = Uf.primitiveFieldRef();

    forAll(UfInternal, facei)
    {
        const scalar magSf = mag(Sf[facei]);
        if (magSf > SMALL)
        {
            const scalar correction =
                (phi.primitiveField()[facei] - (Sf[facei] & UfInternal[facei]))
               /sqr(magSf);
            UfInternal[facei] += correction*Sf[facei];
        }
    }

    forAll(Uf.boundaryFieldRef(), patchi)
    {
        vectorField& patchUf = Uf.boundaryFieldRef()[patchi];
        const vectorField& patchSf = mesh.Sf().boundaryField()[patchi];
        const scalarField& patchPhi = phi.boundaryField()[patchi];

        forAll(patchUf, facei)
        {
            const scalar magSf = mag(patchSf[facei]);
            if (magSf > SMALL)
            {
                const scalar correction =
                    (patchPhi[facei] - (patchSf[facei] & patchUf[facei]))
                   /sqr(magSf);
                patchUf[facei] += correction*patchSf[facei];
            }
        }
    }

    const ErrorStats after = fluxError(phi, Uf, mesh);
    if (!Uf.write())
    {
        FatalErrorInFunction << "failed to write diagnostic Uf" << exit(FatalError);
    }

    std::ofstream output(outputName.c_str());
    output << std::setprecision(17)
           << "{\"schema_version\":\"of10-compatible-uf-counterfactual-v1\""
           << ",\"diagnostic_only\":true"
           << ",\"time_name\":\"" << timeName << "\""
           << ",\"preserved_tangential_component\":true"
           << ",\"source_uf\":\"fvc::interpolate(U)\""
           << ",\"before\":";
    writeError(output, before);
    output << ",\"after\":";
    writeError(output, after);
    output << "}\n";

    return output.good() ? 0 : 1;
}
