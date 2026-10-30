#pragma once

#include <vector>

namespace hsc {

struct ErfEdgeResult {
    bool valid = false;
    double subpixel_pos = 0.0;
    double confidence = 0.0;
};

// Fit 4-parameter error-function blurred-step edge model around peak:
// I(y) = base + amp * 0.5 * (1 + erf(sign * (y - mu) / (sigma * sqrt(2))))
ErfEdgeResult fitErfEdge(const std::vector<double>& seg, int peak, int core, bool is_top);

} // namespace hsc
