#pragma once

#include <cstdint>
#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>
#include <QString>

namespace hsc {

struct InjectionBounds {
    int onset_frame = 0;
    int end_frame = 0;
    int peak_frame = 0;
    int copy_start = 0;
    int copy_end = 0;
    int pre_frames = 30;
    int post_frames = 30;
    int extracted_count = 0;
    int total_burst_frames = 0;
    double max_signal = 0.0;
    QString end_rule = "presence";
    bool detected = false;
};

// Computes the motion signal across frames in folder
// Returns count of pixels changing > diff_thresh vs previous frame
std::vector<int32_t> scanMotionSignalFolder(const std::filesystem::path& folder,
                                           int diff_thresh = 25);

// Computes the motion signal across in-memory frames
std::vector<int32_t> scanMotionSignalBuffers(const std::vector<const uint8_t*>& frames,
                                            int width, int height,
                                            int diff_thresh = 25);

// Dual-rule injection bounds detection ("presence" vs "temporal")
std::optional<InjectionBounds> detectBoundsWithPresence(
    const std::vector<int32_t>& signal,
    std::function<std::vector<int16_t>(int)> frame_getter, // downsampled frame getter
    int total_frames,
    int downsample_w, int downsample_h,
    const QString& end_rule = "presence",
    int before_pad = 30,
    int after_pad = 30,
    double min_peak = 300.0);

} // namespace hsc
