#include "event_writer.h"
#include "src/foundation/app_paths.h"
#include "src/foundation/bmp_io.h"

#include <cstdio>
#include <QJsonDocument>
#include <QJsonObject>

namespace hsc {

EventWriter::EventWriter(const std::filesystem::path& output_base)
    : output_base_(output_base)
{
}

EventWriter::~EventWriter() = default;

void EventWriter::saveAsync(std::shared_ptr<MonitorEvent> event, SavedCallback on_saved)
{
    if (!event || event->discarded || event->frames.empty()) return;

    std::thread([this, event, on_saved]() {
        auto inj_dir = output_base_ / "injection images" / event->folder_name.toStdString();
        std::error_code ec;
        std::filesystem::create_directories(inj_dir, ec);

        int total = static_cast<int>(event->frames.size());
        for (int i = 0; i < total; ++i) {
            char buf[64];
            std::snprintf(buf, sizeof(buf), "frame_%06d.bmp", i + 1);
            saveGrayBmp(inj_dir / buf, event->width, event->height, event->frames[i].data(), false);
        }

        QJsonObject meta;
        meta["onset_frame"] = event->onset_frame;
        meta["end_frame"] = event->end_frame;
        meta["peak_frame"] = event->peak_frame;
        meta["pre_frames"] = event->onset_frame;
        meta["post_frames"] = total - event->end_frame;
        meta["copy_start"] = 0;
        meta["copy_end"] = total - 1;
        meta["extracted_count"] = total;
        meta["total_burst_frames"] = total;
        meta["end_rule"] = "presence";
        meta["max_signal"] = event->peak_diff;

        QJsonDocument doc(meta);
        atomicWriteJson(inj_dir / "injection_meta.json", doc.toJson(QJsonDocument::Indented));

        if (on_saved) {
            on_saved(inj_dir, *event);
        }
    }).detach();
}

} // namespace hsc
