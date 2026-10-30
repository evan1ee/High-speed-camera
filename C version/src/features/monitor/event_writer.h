#pragma once

#include "monitor_engine.h"

#include <filesystem>
#include <functional>
#include <memory>
#include <thread>
#include <QString>

namespace hsc {

class EventWriter {
public:
    using SavedCallback = std::function<void(const std::filesystem::path& folder, const MonitorEvent& event)>;

    explicit EventWriter(const std::filesystem::path& output_base);
    ~EventWriter();

    // Enqueue event to be written in background thread
    void saveAsync(std::shared_ptr<MonitorEvent> event, SavedCallback on_saved = nullptr);

private:
    std::filesystem::path output_base_;
};

} // namespace hsc
