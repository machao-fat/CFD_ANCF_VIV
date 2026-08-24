/*---------------------------------------------------------------------------*\
  Stage-three file-driven solid-body motion for OpenFOAM 10.

  The library consumes the validated stage-three motion CSV and its atomic
  JSON ready marker. It is deliberately a single rigid-slice motion function.
\*---------------------------------------------------------------------------*/

#include "ancfFileMotion.H"
#include "addToRunTimeSelectionTable.H"
#include "quaternion.H"
#include "septernion.H"

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <limits>
#include <chrono>
#include <thread>
#include <vector>

namespace Foam
{
namespace solidBodyMotionFunctions
{

defineTypeNameAndDebug(ancfFileMotion, 0);
addToRunTimeSelectionTable(solidBodyMotionFunction, ancfFileMotion, dictionary);

ancfFileMotion::ancfFileMotion
(
    const dictionary& SBMFCoeffs,
    const Time& runTime
)
:
    solidBodyMotionFunction(SBMFCoeffs, runTime),
    motionFileName_(), readyFileName_(), consumedFileName_(), consumedDirectory_(), CofG_(vector::zero),
      initialPosition_(vector::zero), sliceId_(0), useZMotion_(false),
      stepOffset_(0), startTime_(0), couplingDeltaT_(0), timeTolerance_(1e-10),
      readyTimeout_(30),
    cachedTime_(0), cachedTimeIndex_(-1), cachedPosition_(vector::zero),
    cacheValid_(false), lastError_()
{
    read(SBMFCoeffs);
}

std::string ancfFileMotion::readText(const fileName& path)
{
    std::ifstream stream(path.c_str());
    if (!stream.good()) return std::string();
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

std::string ancfFileMotion::trim(const std::string& text)
{
    const std::string whitespace = " \t\r\n";
    const std::size_t first = text.find_first_not_of(whitespace);
    if (first == std::string::npos) return std::string();
    const std::size_t last = text.find_last_not_of(whitespace);
    return text.substr(first, last-first+1);
}

bool ancfFileMotion::parseScalar(const std::string& text, scalar& value)
{
    const std::string token = trim(text);
    if (token.empty()) return false;
    char* end = nullptr;
    value = std::strtod(token.c_str(), &end);
    return end != token.c_str() && *end == '\0' && std::isfinite(value);
}

bool ancfFileMotion::jsonNumber
(
    const std::string& text,
    const std::string& key,
    scalar& value
)
{
    const std::string needle = "\"" + key + "\"";
    const std::size_t keyPos = text.find(needle);
    if (keyPos == std::string::npos) return false;
    const std::size_t colon = text.find(':', keyPos + needle.size());
    if (colon == std::string::npos) return false;
    const std::string tail = trim(text.substr(colon+1));
    const std::size_t end = tail.find_first_of(",}\n");
    return parseScalar(tail.substr(0, end), value);
}

bool ancfFileMotion::jsonString
(
    const std::string& text,
    const std::string& key,
    std::string& value
)
{
    const std::string needle = "\"" + key + "\"";
    const std::size_t keyPos = text.find(needle);
    if (keyPos == std::string::npos) return false;
    const std::size_t colon = text.find(':', keyPos + needle.size());
    if (colon == std::string::npos) return false;
    const std::size_t firstQuote = text.find('\"', colon+1);
    if (firstQuote == std::string::npos) return false;
    const std::size_t secondQuote = text.find('\"', firstQuote+1);
    if (secondQuote == std::string::npos) return false;
    value = text.substr(firstQuote+1, secondQuote-firstQuote-1);
    return true;
}

std::string ancfFileMotion::baseName(const fileName& path)
{
    const std::string full(path.c_str());
    const std::size_t slash = full.find_last_of("/\\");
    return slash == std::string::npos ? full : full.substr(slash+1);
}

bool ancfFileMotion::writeTextAtomic
(
    const fileName& path,
    const std::string& text
)
{
    if (path.empty()) return true;
    const fileName temporary(path + ".tmp");
    std::ofstream stream(temporary.c_str(), std::ios::out | std::ios::trunc);
    if (!stream.good()) return false;
    stream << text;
    stream.flush();
    stream.close();
    if (!stream) return false;
    return std::rename(temporary.c_str(), path.c_str()) == 0;
}

bool ancfFileMotion::loadCurrentSnapshot
(
    const scalar currentTime,
    const label currentTimeIndex
) const
{
    cacheValid_ = false;
    lastError_.clear();
    if (couplingDeltaT_ <= SMALL)
    {
        lastError_ = "couplingDeltaT must be positive";
        return false;
    }

    const label expectedStep = stepOffset_
        + label(std::floor((currentTime-startTime_)/couplingDeltaT_ + 0.5));
    const auto deadline = std::chrono::steady_clock::now()
        + std::chrono::milliseconds(label(1000*max(0.0, readyTimeout_)));
    scalar markerStep = 0;
    scalar markerTime = 0;
    std::string markerPayload;
    while (true)
    {
        const std::string marker = readText(readyFileName_);
        if (marker.empty())
        {
            lastError_ = "motion_ready is missing or empty";
        }
        else if (!jsonNumber(marker, "step", markerStep)
              || !jsonNumber(marker, "time_s", markerTime)
              || !jsonString(marker, "payload", markerPayload))
        {
            lastError_ = "motion_ready has no valid step/time/payload";
            return false;
        }
        else if (label(std::floor(markerStep + 0.5)) > expectedStep)
        {
            lastError_ = "motion_ready step jumped beyond CFD time";
            return false;
        }
        else if (label(std::floor(markerStep + 0.5)) == expectedStep
              && mag(markerTime-currentTime) <= timeTolerance_*max(1.0, mag(currentTime))
              && markerPayload == baseName(motionFileName_))
        {
            break;
        }
        else
        {
            lastError_ = "motion_ready is stale or time/payload does not match CFD time";
        }
        if (std::chrono::steady_clock::now() >= deadline)
        {
            return false;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }

    std::ifstream stream(motionFileName_.c_str());
    if (!stream.good())
    {
        lastError_ = "motion CSV cannot be opened";
        return false;
    }

    std::string line;
    bool found = false;
    while (std::getline(stream, line))
    {
        line = trim(line);
        if (line.empty() || line[0] == '#'
         || line.find("schema_version") != std::string::npos) continue;

        std::vector<std::string> fields;
        std::stringstream lineStream(line);
        std::string field;
        while (std::getline(lineStream, field, ',')) fields.push_back(trim(field));
        if (fields.size() < 15 || fields[0] != "0.1.0")
        {
            lastError_ = "motion CSV row has an unsupported schema or fewer than 15 fields";
            return false;
        }

        // The first CSV field is the textual schema version.  The remaining
        // fourteen fields are numeric and follow the shared motion contract.
        scalar values[14];
        for (label i=0; i<14; ++i)
        {
            if (!parseScalar(fields[i+1], values[i]))
            {
                lastError_ = "motion CSV contains NaN/Inf or non-numeric data";
                return false;
            }
        }
        const label rowSliceId = label(std::floor(values[3] + 0.5));
        if (rowSliceId != sliceId_) continue;
        if (label(std::floor(values[0] + 0.5)) != expectedStep
         || mag(values[2]-currentTime) > timeTolerance_*max(1.0, mag(currentTime)))
        {
            lastError_ = "motion CSV step/time does not match CFD time";
            return false;
        }
        cachedPosition_ = vector(values[5], values[6], useZMotion_ ? values[7] : 0.0);
        found = true;
        break;
    }
    if (!found)
    {
        lastError_ = "requested slice_id is absent from motion CSV";
        return false;
    }
    // Release the DrvFs file handle before the producer atomically replaces
    // motion.csv for the next coupling step.
    stream.close();

    cachedTime_ = currentTime;
    cachedTimeIndex_ = currentTimeIndex;
    cacheValid_ = true;
    if (!consumedFileName_.empty())
    {
        fileName acknowledgementPath = consumedFileName_;
        if (!consumedDirectory_.empty())
        {
            acknowledgementPath = fileName
            (
                consumedDirectory_
              + "/motion_consumed_"
              + std::to_string(expectedStep)
              + ".json"
            );
        }
        std::ostringstream consumed;
        // Preserve the exact binary64 time identity across the legacy bridge.
        // The default stream precision rounds 1.508125 to 1.50813.
        consumed << std::setprecision(std::numeric_limits<scalar>::max_digits10);
        consumed << "{\"kind\":\"motion_consumed\",\"step\":"
            << expectedStep << ",\"time_s\":" << currentTime << "}\n";
        if (!writeTextAtomic(acknowledgementPath, consumed.str()))
        {
            lastError_ = "cannot publish motion-consumed acknowledgement";
            cacheValid_ = false;
            return false;
        }
    }
    return true;
}

septernion ancfFileMotion::transformation() const
{
    const scalar currentTime = time_.value();
    const label currentTimeIndex = time_.timeIndex();
    if (!cacheValid_
     || currentTimeIndex != cachedTimeIndex_
     || mag(currentTime-cachedTime_) > timeTolerance_*max(1.0, mag(currentTime)))
    {
        if (!loadCurrentSnapshot(currentTime, currentTimeIndex))
        {
            FatalErrorInFunction
                << lastError_ << " at t=" << currentTime
                << ", step=" << currentTimeIndex
                << exit(FatalError);
        }
    }
    const vector displacement = cachedPosition_ - initialPosition_;
    const quaternion rotation(quaternion::XYZ, vector::zero);
    return septernion(-CofG_ - displacement)*rotation*septernion(CofG_);
}

bool ancfFileMotion::read(const dictionary& SBMFCoeffs)
{
    solidBodyMotionFunction::read(SBMFCoeffs);
    motionFileName_ = fileName(SBMFCoeffs_.lookup("motionFile")).expand();
    readyFileName_ = fileName(SBMFCoeffs_.lookup("readyFile")).expand();
    if (SBMFCoeffs_.found("consumedFile"))
    {
        consumedFileName_ = fileName(SBMFCoeffs_.lookup("consumedFile")).expand();
    }
    else
    {
        consumedFileName_.clear();
    }
    if (SBMFCoeffs_.found("consumedDirectory"))
    {
        consumedDirectory_ = fileName(SBMFCoeffs_.lookup("consumedDirectory")).expand();
    }
    else
    {
        consumedDirectory_.clear();
    }
    SBMFCoeffs_.lookup("CofG") >> CofG_;
    initialPosition_ = SBMFCoeffs_.lookupOrDefault<vector>("initialPosition", CofG_);
    sliceId_ = SBMFCoeffs_.lookupOrDefault<label>("sliceId", 0);
    useZMotion_ = SBMFCoeffs_.lookupOrDefault<bool>("useZMotion", false);
    stepOffset_ = SBMFCoeffs_.lookupOrDefault<label>("stepOffset", 0);
    startTime_ = SBMFCoeffs_.lookupOrDefault<scalar>("startTime", 0.0);
    couplingDeltaT_ = SBMFCoeffs_.lookupOrDefault<scalar>("couplingDeltaT", time_.deltaTValue());
    timeTolerance_ = SBMFCoeffs_.lookupOrDefault<scalar>("timeTolerance", 1.0e-10);
    readyTimeout_ = SBMFCoeffs_.lookupOrDefault<scalar>("readyTimeout", 30.0);
    cachedTimeIndex_ = -1;
    cacheValid_ = false;
    // The initial mesh may not call transformation() at startTime.  Validate
    // and acknowledge the seed snapshot here so a producer can safely issue
    // the first next-step motion without racing the solver startup.
    if (!consumedFileName_.empty())
    {
        if (!loadCurrentSnapshot(time_.value(), time_.timeIndex()))
        {
            FatalErrorInFunction
                << lastError_ << " at initial CFD time " << time_.value()
                << exit(FatalError);
        }
    }
    return true;
}

} // End namespace solidBodyMotionFunctions
} // End namespace Foam
