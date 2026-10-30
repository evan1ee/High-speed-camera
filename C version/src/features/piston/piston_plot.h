#pragma once

#include "measure_piston.h"

#include <filesystem>
#include <QString>

namespace hsc {

// Renders 3-panel curve plot (Displacement vs Time, Speed vs Time, Stagnation Pressure vs Time) to PNG
bool renderPistonPlots(const PistonMeasureResult& res,
                       const std::filesystem::path& out_path,
                       int width = 960, int height = 640);

} // namespace hsc
