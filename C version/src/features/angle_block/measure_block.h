#pragma once

#include "src/features/spray_angle/measure_angle.h"

#include <filesystem>
#include <vector>
#include <QString>

namespace hsc {

struct BlockMeasureResult {
    double angle_deg = 0.0;
    TlsLine line1;
    TlsLine line2;
    std::filesystem::path csv_path;
    bool valid = false;
};

// Measures the angle block from a single still frame
BlockMeasureResult measureAngleBlock(const uint8_t* gray, int width, int height,
                                    const std::filesystem::path& out_dir = "");

} // namespace hsc
