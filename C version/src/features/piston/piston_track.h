#pragma once

#include <cstdint>
#include <filesystem>
#include <functional>
#include <optional>
#include <vector>
#include <QString>

namespace hsc {

struct BarrelProfile {
    int y_top = 0;
    int y_bot = 0;
    double v_dark = 0.0;
    double v_bright = 0.0;
    double t_body = 0.0;
    bool valid = false;
};

struct PistonFrameEdge {
    int frame_index = 0;
    double x_edge = 0.0; // horizontal position at barrel center
    std::vector<std::pair<double, double>> edge_points; // (y, x)
    bool detected = false;
};

struct PistonStrokeBounds {
    int start_frame = 0;
    int end_frame = 0;
    int total_frames = 0;
    double total_travel_px = 0.0;
    bool detected = false;
};

// Builds temporal max/min profile and selects valid barrel row band
BarrelProfile buildBarrelProfile(const std::vector<const uint8_t*>& sample_frames, int width, int height);

// Detects piston subpixel leading edge on a single frame
PistonFrameEdge measurePistonEdge(const uint8_t* gray, int width, int height, const BarrelProfile& prof);

// Pools slope across stroke frames and re-projects each frame to common slope
std::vector<double> applyCommonSlope(const std::vector<PistonFrameEdge>& edges, int height);

// Detects stroke onset and plateau settle
PistonStrokeBounds detectPistonBounds(const std::vector<double>& positions);

} // namespace hsc
