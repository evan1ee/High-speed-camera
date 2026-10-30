#pragma once

#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <vector>
#include <QString>

namespace hsc {

enum class MonitorState {
    Armed,
    Recording,
    Padding
};

struct MonitorEvent {
    int event_id = 0;
    QString folder_name;
    std::vector<std::vector<uint8_t>> frames;
    int width = 0;
    int height = 0;
    int peak_frame = 0;
    int peak_diff = 0;
    int onset_frame = 0;
    int end_frame = 0;
    bool discarded = false; // true if rejected as drip/mist (< 3000 peak)
};

class MonitorEngine {
public:
    MonitorEngine(int width, int height,
                  int before_frames = 30,
                  int after_frames = 30,
                  int trigger_diff = 300,
                  int quiet_hold = 60,
                  int runaway_cap = 600,
                  int min_peak = 3000);

    // Feed next frame from camera stream. Returns non-null when an event closes!
    std::shared_ptr<MonitorEvent> feedFrame(const uint8_t* gray);

    MonitorState state() const { return state_; }
    int totalFramesFed() const { return total_fed_; }
    int eventsDetected() const { return events_detected_; }
    int dripsDiscarded() const { return drips_discarded_; }

    void reset();

private:
    int width_;
    int height_;
    int before_frames_;
    int after_frames_;
    int trigger_diff_;
    int quiet_hold_;
    int runaway_cap_;
    int min_peak_;

    MonitorState state_ = MonitorState::Armed;
    std::deque<std::vector<uint8_t>> ring_buffer_;
    std::vector<uint8_t> prev_frame_;

    std::shared_ptr<MonitorEvent> active_event_;
    int quiet_counter_ = 0;
    int pad_counter_ = 0;
    int total_fed_ = 0;
    int events_detected_ = 0;
    int drips_discarded_ = 0;
    int event_seq_ = 0;

    int computeDiff(const uint8_t* a, const uint8_t* b);
};

} // namespace hsc
