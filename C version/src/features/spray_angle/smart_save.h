#pragma once

#include "src/foundation/temporal_scanner.h"

#include <cstdint>
#include <filesystem>
#include <functional>
#include <optional>
#include <vector>
#include <QString>

namespace hsc {

struct SmartSavePlan {
    bool has_injection = false;
    InjectionBounds bounds;
    std::filesystem::path target_dir;
    int saved_count = 0;
};

// Evaluates in-memory burst frames and writes directly to injection images directory if injection detected
SmartSavePlan planSmartSave(const std::vector<std::vector<uint8_t>>& burst_frames,
                           int width, int height,
                           const std::filesystem::path& base_dir,
                           const QString& run_name,
                           const QString& end_rule = "presence",
                           std::function<void(int, int)> progress = nullptr);

} // namespace hsc
