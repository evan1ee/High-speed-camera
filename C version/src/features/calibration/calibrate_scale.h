#pragma once

#include "src/foundation/calibration_store.h"

#include <cstdint>
#include <optional>
#include <vector>
#include <QRect>

namespace hsc {

struct AutoCalibResult {
    bool valid = false;
    double mm_per_px = 0.0;
    double distance_px = 0.0;
    EdgeInfo edge1;
    EdgeInfo edge2;
};

// Measures edge line within an ROI of a grayscale image
std::optional<EdgeInfo> detectEdgeInRoi(const uint8_t* gray, int width, int height,
                                       const QRect& roi, const QString& mode = "step");

// Calibrates scale from two user-marked ROIs
std::optional<ScaleCalibration> calibrateFromRois(const uint8_t* gray, int width, int height,
                                                const QRect& roi1, const QRect& roi2,
                                                double ref_mm = 5.0,
                                                const QString& mode = "step");

// Auto-detects gauge block ROIs and calibrates scale in 1 click
AutoCalibResult autoCalibrate(const uint8_t* gray, int width, int height, double ref_mm = 5.0);

} // namespace hsc
