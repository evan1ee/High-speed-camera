#include "smart_save.h"
#include "src/foundation/app_paths.h"
#include "src/foundation/bmp_io.h"

#include <cstdio>
#include <fstream>
#include <iomanip>
#include <QDateTime>
#include <QJsonDocument>
#include <QJsonObject>

namespace hsc {

SmartSavePlan planSmartSave(const std::vector<std::vector<uint8_t>>& burst_frames,
                           int width, int height,
                           const std::filesystem::path& base_dir,
                           const QString& run_name,
                           const QString& end_rule,
                           std::function<void(int, int)> progress)
{
    SmartSavePlan plan;
    int n = static_cast<int>(burst_frames.size());
    if (n < 3 || width <= 0 || height <= 0) return plan;

    std::vector<const uint8_t*> ptrs(n);
    for (int i = 0; i < n; ++i) ptrs[i] = burst_frames[i].data();

    // Step 1: Scan motion signal in RAM
    auto signal = scanMotionSignalBuffers(ptrs, width, height, 25);

    // Frame getter for downsampled 4x4 frames
    int ds_w = (width + 3) / 4;
    int ds_h = (height + 3) / 4;
    auto getter = [&](int i) -> std::vector<int16_t> {
        std::vector<int16_t> ds(static_cast<size_t>(ds_w) * ds_h, 0);
        const uint8_t* src = burst_frames[i].data();
        for (int y = 0; y < ds_h; ++y) {
            for (int x = 0; x < ds_w; ++x) {
                int orig_y = std::min(height - 1, y * 4);
                int orig_x = std::min(width - 1, x * 4);
                ds[y * ds_w + x] = static_cast<int16_t>(src[orig_y * width + orig_x]);
            }
        }
        return ds;
    };

    auto bounds_opt = detectBoundsWithPresence(signal, getter, n, ds_w, ds_h, end_rule);
    if (!bounds_opt || !bounds_opt->detected) {
        // Fallback: save full burst to data/captures/<run>
        auto cap_dir = base_dir / "captures" / run_name.toStdString();
        std::error_code ec;
        std::filesystem::create_directories(cap_dir, ec);

        for (int i = 0; i < n; ++i) {
            if (progress) progress(i + 1, n);
            char buf[64];
            std::snprintf(buf, sizeof(buf), "frame_%06d.bmp", i + 1);
            saveGrayBmp(cap_dir / buf, width, height, burst_frames[i].data(), false);
        }

        plan.has_injection = false;
        plan.target_dir = cap_dir;
        plan.saved_count = n;
        return plan;
    }

    // Injection detected! Save only window directly to data/injection images/<run>
    plan.has_injection = true;
    plan.bounds = *bounds_opt;

    auto inj_dir = base_dir / "injection images" / run_name.toStdString();
    std::error_code ec;
    std::filesystem::create_directories(inj_dir, ec);

    int count = 0;
    for (int i = plan.bounds.copy_start; i <= plan.bounds.copy_end; ++i) {
        if (progress) progress(count + 1, plan.bounds.extracted_count);
        char buf[64];
        std::snprintf(buf, sizeof(buf), "frame_%06d.bmp", i + 1);
        saveGrayBmp(inj_dir / buf, width, height, burst_frames[i].data(), false);
        ++count;
    }

    // Write injection_meta.json
    QJsonObject meta;
    meta["onset_frame"] = plan.bounds.onset_frame;
    meta["end_frame"] = plan.bounds.end_frame;
    meta["peak_frame"] = plan.bounds.peak_frame;
    meta["pre_frames"] = plan.bounds.pre_frames;
    meta["post_frames"] = plan.bounds.post_frames;
    meta["copy_start"] = plan.bounds.copy_start;
    meta["copy_end"] = plan.bounds.copy_end;
    meta["extracted_count"] = plan.bounds.extracted_count;
    meta["total_burst_frames"] = plan.bounds.total_burst_frames;
    meta["end_rule"] = plan.bounds.end_rule;
    meta["max_signal"] = plan.bounds.max_signal;

    QJsonDocument doc(meta);
    atomicWriteJson(inj_dir / "injection_meta.json", doc.toJson(QJsonDocument::Indented));

    plan.target_dir = inj_dir;
    plan.saved_count = count;
    return plan;
}

} // namespace hsc
