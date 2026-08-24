/*---------------------------------------------------------------------------*\
  Stage-three file-driven solid-body motion for OpenFOAM 10.
\*---------------------------------------------------------------------------*/

#ifndef ancfFileMotion_H
#define ancfFileMotion_H

#include "solidBodyMotionFunction.H"
#include "fileName.H"
#include "vector.H"

#include <string>

namespace Foam
{
namespace solidBodyMotionFunctions
{

class ancfFileMotion
:
    public solidBodyMotionFunction
{
    // Configuration
    fileName motionFileName_;
    fileName readyFileName_;
    fileName consumedFileName_;
    fileName consumedDirectory_;
    vector CofG_;
    vector initialPosition_;
    label sliceId_;
    bool useZMotion_;
    label stepOffset_;
    scalar startTime_;
    scalar couplingDeltaT_;
    scalar timeTolerance_;
    scalar readyTimeout_;

    // Cache one validated snapshot per OpenFOAM time value.
    mutable scalar cachedTime_;
    mutable label cachedTimeIndex_;
    mutable vector cachedPosition_;
    mutable bool cacheValid_;
    mutable std::string lastError_;

    static std::string readText(const fileName& path);
    static bool jsonNumber(const std::string& text, const std::string& key, scalar& value);
    static bool jsonString(const std::string& text, const std::string& key, std::string& value);
    static std::string trim(const std::string& text);
    static bool parseScalar(const std::string& text, scalar& value);
    static std::string baseName(const fileName& path);
    static bool writeTextAtomic(const fileName& path, const std::string& text);

    bool loadCurrentSnapshot(const scalar currentTime, const label currentTimeIndex) const;

public:

    TypeName("ancfFileMotion");

    ancfFileMotion
    (
        const dictionary& SBMFCoeffs,
        const Time& runTime
    );

    ancfFileMotion(const ancfFileMotion&) = delete;

    virtual autoPtr<solidBodyMotionFunction> clone() const
    {
        return autoPtr<solidBodyMotionFunction>
        (
            new ancfFileMotion(SBMFCoeffs_, time_)
        );
    }

    virtual ~ancfFileMotion() = default;

    virtual septernion transformation() const;

    virtual bool read(const dictionary& SBMFCoeffs);
};

} // End namespace solidBodyMotionFunctions
} // End namespace Foam

#endif
