#pragma once

#include "src/foundation/tls_fit.h"
#include "src/foundation/reference_store.h"

#include <cstdint>
#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>
#include <QString>

namespace hsc {

struct FrameMeasureResult {
    double angle = 0.0;          // deg (either total opening angle or max/trusted deviation from reference)
    double angle_upper = 0.0;
    double angle_lower = 0.0;
    TlsLine line_upper;
    TlsLine line_lower;
    std::vector<std::pair<double, double>> upper_pts;
    std::vector<std::pair<double, double>> lower_pts;
    double quality_score = 0.0;   // 0 .. 100
    QString confidence_str;      // "High", "Medium", "Low"
    double score_fit = 0.0;
    double score_cov = 0.0;
    double score_span = 0.0;
    QString in_rect_verdict;     // "OK", "NG", or ""
    double span_px = 0.0;
    int frame_index = 0;
    QString frame_name;
    bool valid = false;
};

struct SprayMeasureOptions {
    bool use_erf = false;
    bool use_pre_onset_bg = true;
    QString angle_policy = "max"; // "max" or "trusted"
    bool auto_pick_frames = true;
    int measure_from = 10;
    int measure_to = 20;
    bool draw_ref_lines = true;
    int nozzle_side = 1;          // +1: nozzle on right, jet travelling left
    int nozzle_skip = 14;
    double roi_frac = 0.85;
};

struct FolderMeasureResult {
    QString run_name;
    std::filesystem::path folder_path;
    double mean_angle = 0.0;
    double std_angle = 0.0;
    double pooled_angle = 0.0;
    double overall_confidence = 0.0;
    QString overall_confidence_str; // "High", "Medium", "Low"
    QString in_rect_verdict;        // "OK", "NG", or ""
    int measured_count = 0;
    std::vector<FrameMeasureResult> frame_results;
    std::vector<QString> annotated_frame_paths;
    std::filesystem::path csv_path;
    bool valid = false;
};

// Measures a single grayscale frame
FrameMeasureResult measureFrame(const uint8_t* gray, int width, int height,
                               const int16_t* bg,
                               const SprayMeasureOptions& opts,
                               const std::optional<NozzleReference>& ref = std::nullopt,
                               double max_run_span = 0.0);

// Runs the full measurement pipeline on an injection folder
FolderMeasureResult measureFolder(const std::filesystem::path& folder,
                                 const SprayMeasureOptions& opts,
                                 const std::optional<NozzleReference>& ref = std::nullopt,
                                 std::function<void(int, int)> progress = nullptr);

// Renders visual annotations (green edge lines, yellow nozzle tip, blue axis, red target box) onto BMP
bool renderAnnotatedFrame(const uint8_t* gray, int width, int height,
                          const FrameMeasureResult& res,
                          const std::optional<NozzleReference>& ref,
                          bool draw_ref_lines,
                          const std::filesystem::path& out_path);

} // namespace hsc
