#include "monitor_engine.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <QDateTime>

namespace hsc {

MonitorEngine::MonitorEngine(int width, int height,
                             int before_frames,
                             int after_frames,
                             int trigger_diff,
                             int quiet_hold,
                             int runaway_cap,
                             int min_peak)
    : width_(width), height_(height),
      before_frames_(before_frames), after_frames_(after_frames),
      trigger_diff_(trigger_diff), quiet_hold_(quiet_hold),
      runaway_cap_(runaway_cap), min_peak_(min_peak)
{
}

void MonitorEngine::reset()
{
    state_ = MonitorState::Armed;
    ring_buffer_.clear();
    prev_frame_.clear();
    active_event_.reset();
    quiet_counter_ = 0;
    pad_counter_ = 0;
}

int MonitorEngine::computeDiff(const uint8_t* a, const uint8_t* b)
{
    if (!a || !b) return 0;
    // Check left 2/3 columns
    int detect_w = (width_ * 2) / 3;
    int count = 0;

    for (int y = 0; y < height_; ++y) {
        const uint8_t* row_a = a + static_cast<size_t>(y) * width_;
        const uint8_t* row_b = b + static_cast<size_t>(y) * width_;
        for (int x = 0; x < detect_w; ++x) {
            int d = static_cast<int>(row_a[x]) - static_cast<int>(row_b[x]);
            if (std::abs(d) > 25) ++count;
        }
    }
    return count;
}

std::shared_ptr<MonitorEvent> MonitorEngine::feedFrame(const uint8_t* gray)
{
    if (!gray || width_ <= 0 || height_ <= 0) return nullptr;

    ++total_fed_;
    size_t npix = static_cast<size_t>(width_) * height_;
    std::vector<uint8_t> cur(gray, gray + npix);

    int diff = 0;
    if (!prev_frame_.empty()) {
        diff = computeDiff(cur.data(), prev_frame_.data());
    }

    std::shared_ptr<MonitorEvent> closed_event = nullptr;

    switch (state_) {
    case MonitorState::Armed: {
        ring_buffer_.push_back(cur);
        if (ring_buffer_.size() > static_cast<size_t>(before_frames_)) {
            ring_buffer_.pop_front();
        }

        if (diff >= trigger_diff_) {
            // Triggered! Move to Recording
            state_ = MonitorState::Recording;
            ++event_seq_;

            active_event_ = std::make_shared<MonitorEvent>();
            active_event_->event_id = event_seq_;
            active_event_->width = width_;
            active_event_->height = height_;
            active_event_->peak_diff = diff;
            active_event_->peak_frame = static_cast<int>(ring_buffer_.size());
            active_event_->onset_frame = static_cast<int>(ring_buffer_.size());

            QString stamp = QDateTime::currentDateTime().toString("yyyyMMdd_hhmmss");
            active_event_->folder_name = QString("monitor_%1_%2_%3x%4")
                                             .arg(stamp)
                                             .arg(event_seq_, 3, 10, QChar('0'))
                                             .arg(width_)
                                             .arg(height_);

            // Drain ring buffer into event frames
            for (auto& f : ring_buffer_) {
                active_event_->frames.push_back(std::move(f));
            }
            ring_buffer_.clear();

            active_event_->frames.push_back(cur);
            quiet_counter_ = 0;
        }
        break;
    }

    case MonitorState::Recording: {
        active_event_->frames.push_back(cur);
        int current_frame_idx = static_cast<int>(active_event_->frames.size()) - 1;

        if (diff > active_event_->peak_diff) {
            active_event_->peak_diff = diff;
            active_event_->peak_frame = current_frame_idx;
        }

        if (diff < trigger_diff_) {
            ++quiet_counter_;
            if (quiet_counter_ >= quiet_hold_) {
                state_ = MonitorState::Padding;
                pad_counter_ = 0;
                active_event_->end_frame = current_frame_idx - quiet_hold_;
            }
        } else {
            quiet_counter_ = 0;
        }

        if (active_event_->frames.size() >= static_cast<size_t>(runaway_cap_)) {
            // Cap hit! Close immediately
            state_ = MonitorState::Armed;
            active_event_->end_frame = current_frame_idx;
            closed_event = active_event_;
            active_event_.reset();
        }
        break;
    }

    case MonitorState::Padding: {
        active_event_->frames.push_back(cur);
        ++pad_counter_;

        if (pad_counter_ >= after_frames_) {
            state_ = MonitorState::Armed;
            closed_event = active_event_;
            active_event_.reset();
        }
        break;
    }
    }

    if (closed_event) {
        if (closed_event->peak_diff < min_peak_) {
            closed_event->discarded = true;
            ++drips_discarded_;
        } else {
            closed_event->discarded = false;
            ++events_detected_;
        }
    }

    prev_frame_ = std::move(cur);
    return closed_event;
}

} // namespace hsc
