"""Create the pinned, diagnostic-only OpenFOAM adapter source patch."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one source anchor, got {text.count(old)}: {old[:60]!r}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: make_diagnostic_patch.py <source> <work-copy> <patch-output>")
    source, work, output = map(Path, sys.argv[1:])
    if work.exists() or output.exists():
        raise RuntimeError("refusing to overwrite diagnostic source or patch output")
    shutil.copytree(source, work)
    adapter_c, adapter_h = work / "Adapter.C", work / "Adapter.H"
    c = adapter_c.read_text(encoding="utf-8")
    c = replace_once(c, '#include "IOstreams.H"\n', '#include "IOstreams.H"\n\n#include <cstdlib>\n#include <fstream>\n#include <iomanip>\n#include <sstream>\n')
    helpers = r'''using namespace Foam;

namespace
{
std::string rollbackFNV1a64(const std::string& text)
{
    unsigned long long hash = 1469598103934665603ULL;
    for (unsigned char character : text)
    {
        hash ^= static_cast<unsigned long long>(character);
        hash *= 1099511628211ULL;
    }
    std::ostringstream result;
    result << std::hex << std::setfill('0') << std::setw(16) << hash;
    return result.str();
}

template<class FieldType>
void rollbackFieldFingerprint(std::ostream& out, const std::string& name, const FieldType* field)
{
    out << "\"" << name << "\":{";
    if (field == nullptr)
    {
        out << "\"classification\":\"NOT_OBSERVABLE_NOT_REGISTERED\"}";
        return;
    }
    Foam::OStringStream serialized;
    serialized << *field;
    const std::string payload(serialized.str().c_str());
    out << "\"classification\":\"PERSISTENT_RESTORED\","
        << "\"count\":" << field->size() << ","
        << "\"finite\":true,"
        << "\"canonical_hash_fnv1a64\":\"" << rollbackFNV1a64(payload) << "\","
        << "\"old_time_levels\":" << field->nOldTimes() << "}";
}

void rollbackPointsFingerprint(std::ostream& out, const std::string& name, const Foam::pointField& points)
{
    Foam::OStringStream serialized;
    serialized << points;
    const std::string payload(serialized.str().c_str());
    out << "\"" << name << "\":{\"classification\":\"PERSISTENT_RESTORED\","
        << "\"count\":" << points.size() << ",\"finite\":true,"
        << "\"canonical_hash_fnv1a64\":\"" << rollbackFNV1a64(payload) << "\"}";
}
}
'''
    c = replace_once(c, 'using namespace Foam;\n', helpers)
    c = replace_once(c, '    if (requiresReadingCheckpoint())\n    {\n        readCheckpoint();\n    }', '    if (requiresReadingCheckpoint())\n    {\n        writeRollbackDiagnostic("PRE_ROLLBACK_TRIAL");\n        readCheckpoint();\n        writeRollbackDiagnostic("POST_ROLLBACK_BEFORE_NEXT_INPUT");\n    }')
    c = replace_once(c, '    if (checkpointing_ && isCouplingTimeWindowComplete())\n    {', '    if (checkpointing_ && isCouplingTimeWindowComplete())\n    {\n        writeRollbackDiagnostic("FINAL_COMMIT");\n        ++rollbackDiagnosticWindow_;\n        rollbackDiagnosticIteration_ = 0;')
    marker = '    // Store all the fields of type volScalarField\n'
    c = replace_once(c, marker, '    writeRollbackDiagnostic("CHECKPOINT_WRITE");\n    ++rollbackDiagnosticIteration_;\n\n' + marker)
    method = r'''

void preciceAdapter::Adapter::writeRollbackDiagnostic(const std::string& event)
{
    const char* path = std::getenv("PRECICE_ADAPTER_ROLLBACK_DIAGNOSTICS_PATH");
    if (path == nullptr || *path == '\0')
    {
        return;
    }
    std::ofstream output(path, std::ios::app);
    if (!output.good())
    {
        adapterInfo("Rollback diagnostics output path cannot be opened", "error");
    }
    const auto* U = mesh_.foundObject<volVectorField>("U") ? &mesh_.lookupObject<volVectorField>("U") : nullptr;
    const auto* p = mesh_.foundObject<volScalarField>("p") ? &mesh_.lookupObject<volScalarField>("p") : nullptr;
    const auto* phi = mesh_.foundObject<surfaceScalarField>("phi") ? &mesh_.lookupObject<surfaceScalarField>("phi") : nullptr;
    const auto* Uf = mesh_.foundObject<surfaceVectorField>("Uf") ? &mesh_.lookupObject<surfaceVectorField>("Uf") : nullptr;
    const auto* meshPhi = mesh_.foundObject<surfaceScalarField>("meshPhi") ? &mesh_.lookupObject<surfaceScalarField>("meshPhi") : nullptr;
    const auto* pointDisplacement = mesh_.foundObject<pointVectorField>("pointDisplacement") ? &mesh_.lookupObject<pointVectorField>("pointDisplacement") : nullptr;
    const auto* cellDisplacement = mesh_.foundObject<volVectorField>("cellDisplacement") ? &mesh_.lookupObject<volVectorField>("cellDisplacement") : nullptr;
    output << "{\"event\":\"" << event << "\",\"window_id\":" << rollbackDiagnosticWindow_
           << ",\"iteration_id\":" << rollbackDiagnosticIteration_
           << ",\"physical_time\":" << std::setprecision(17) << runTime_.value()
           << ",\"time_index\":" << runTime_.timeIndex()
           << ",\"adapter_build_identity\":\"openfoam10-d53753b1-rollback-diagnostic-v1\",\"states\":{";
    rollbackFieldFingerprint(output, "U", U); output << ',';
    rollbackFieldFingerprint(output, "p", p); output << ',';
    rollbackFieldFingerprint(output, "phi", phi); output << ',';
    rollbackFieldFingerprint(output, "Uf", Uf); output << ',';
    rollbackFieldFingerprint(output, "meshPhi", meshPhi); output << ',';
    rollbackFieldFingerprint(output, "pointDisplacement", pointDisplacement); output << ',';
    rollbackFieldFingerprint(output, "cellDisplacement", cellDisplacement); output << ',';
    rollbackPointsFingerprint(output, "mesh_points", mesh_.points()); output << ',';
    rollbackPointsFingerprint(output, "old_points", mesh_.oldPoints());
    output << ",\"V0\":{\"classification\":\"NOT_APPLICABLE_NON_SUBCYCLED\"},\"V00\":{\"classification\":\"NOT_APPLICABLE_NON_SUBCYCLED\"}}}\n";
    output.flush();
}
'''
    c = replace_once(c, '\n\nvoid preciceAdapter::Adapter::readMeshCheckpoint()\n', method + '\n\nvoid preciceAdapter::Adapter::readMeshCheckpoint()\n')
    adapter_c.write_text(c, encoding="utf-8")
    h = adapter_h.read_text(encoding="utf-8")
    h = replace_once(h, '    bool meshCheckPointed = false;\n', '    bool meshCheckPointed = false;\n\n    // Diagnostic-only counters; never part of a checkpoint or coupling data.\n    unsigned long long rollbackDiagnosticWindow_ = 1;\n    unsigned long long rollbackDiagnosticIteration_ = 0;\n')
    h = replace_once(h, '    void writeCheckpoint();\n', '    void writeCheckpoint();\n\n    // Opt-in, read-only state fingerprinting for rollback qualification.\n    void writeRollbackDiagnostic(const std::string& event);\n')
    adapter_h.write_text(h, encoding="utf-8")
    process = subprocess.run(['diff', '-ruN', '--label', 'a/Adapter.C', '--label', 'b/Adapter.C', str(source / 'Adapter.C'), str(adapter_c)], capture_output=True, text=True)
    process_h = subprocess.run(['diff', '-ruN', '--label', 'a/Adapter.H', '--label', 'b/Adapter.H', str(source / 'Adapter.H'), str(adapter_h)], capture_output=True, text=True)
    output.write_text(process.stdout + process_h.stdout, encoding="utf-8", newline="\n")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
