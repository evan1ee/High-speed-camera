#include "temporal_scanner.h"
#include "bmp_io.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>

#ifdef _OPENMP
#include <omp.h>
#endif

namespace hsc {

std::vector<int32_t> scanMotionSignalFolder(const std::filesystem::path& folder, int diff_thresh)
{
    std::vector<std::filesystem::path> files;
    std::error_code ec;
    for (const auto& entry : std::filesystem::directory_iterator(folder, ec)) {
        if (!entry.is_regular_file()) continue;
        auto ext = entry.path().extension().string();
        std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
        if (ext == ".bmp") {
            files.push_back(entry.path());
        }
    }
    std::sort(files.begin(), files.end());

    int n = static_cast<int>(files.size());
    if (n < 2) return std::vector<int32_t>(n, 0);

    BmpHeader info;
    if (!readBmpHeader(files[0], info) || info.bpp != 8) {
        return std::vector<int32_t>(n, 0);
    }

    const size_t row_stride = (static_cast<size_t>(info.width) + 3) & ~size_t(3);
    const size_t raw_bytes = row_stride * info.height;

    std::vector<int32_t> signal(n, 0);

    auto readRawBytes = [&](const std::filesystem::path& p, std::vector<uint8_t>& buf) -> bool {
        std::ifstream f(p, std::ios::binary);
        if (!f) return false;
        f.seekg(info.offset, std::ios::beg);
        buf.resize(raw_bytes);
        f.read(reinterpret_cast<char*>(buf.data()), static_cast<std::streamsize>(raw_bytes));
        return static_cast<size_t>(f.gcount()) == raw_bytes;
    };

    #pragma omp parallel
    {
        std::vector<uint8_t> prev, cur;
        #pragma omp for schedule(dynamic)
        for (int start = 1; start < n; start += 64) {
            int end = std::min(start + 64, n);
            if (!readRawBytes(files[start - 1], prev)) continue;

            for (int i = start; i < end; ++i) {
                if (!readRawBytes(files[i], cur)) {
                    prev.swap(cur);
                    continue;
                }

                int32_t count = 0;
                const uint8_t* a = cur.data();
                const uint8_t* b = prev.data();

                for (int r = 0; r < info.height; ++r) {
                    const uint8_t* row_a = a + static_cast<size_t>(r) * row_stride;
                    const uint8_t* row_b = b + static_cast<size_t>(r) * row_stride;
                    for (int c = 0; c < info.width; ++c) {
                        int d = static_cast<int>(row_a[c]) - static_cast<int>(row_b[c]);
                        if (std::abs(d) > diff_thresh) ++count;
                    }
                }

                signal[i] = count;
                prev.swap(cur);
            }
        }
    }

    return signal;
}

std::vector<int32_t> scanMotionSignalBuffers(const std::vector<const uint8_t*>& frames,
                                            int width, int height, int diff_thresh)
{
    int n = static_cast<int>(frames.size());
    std::vector<int32_t> signal(n, 0);
    if (n < 2 || width <= 0 || height <= 0) return signal;

    const size_t npix = static_cast<size_t>(width) * height;

    #pragma omp parallel for schedule(dynamic, 64)
    for (int i = 1; i < n; ++i) {
        const uint8_t* a = frames[i];
        const uint8_t* b = frames[i - 1];
        if (!a || !b) continue;

        int32_t count = 0;
        for (size_t k = 0; k < npix; ++k) {
            int d = static_cast<int>(a[k]) - static_cast<int>(b[k]);
            if (std::abs(d) > diff_thresh) ++count;
        }
        signal[i] = count;
    }

    return signal;
}

std::optional<InjectionBounds> detectBoundsWithPresence(
    const std::vector<int32_t>& signal,
    std::function<std::vector<int16_t>(int)> frame_getter,
    int total_frames,
    int downsample_w, int downsample_h,
    const QString& end_rule,
    int before_pad,
    int after_pad,
    double min_peak)
{
    if (total_frames < 3 || signal.empty()) return std::nullopt;

    auto max_it = std::max_element(signal.begin(), signal.end());
    int peak = static_cast<int>(std::distance(signal.begin(), max_it));
    double peak_val = static_cast<double>(*max_it);

    if (peak_val < min_peak) return std::nullopt;

    const double frac = 0.005;
    const double abs_floor = 30.0;
    const int gap = 5;
    double threshold = std::max(abs_floor, frac * peak_val);

    auto walkLeft = [&]() -> int {
        int i = peak;
        int miss = 0;
        int last = peak;
        while (i >= 0) {
            if (signal[i] > threshold) {
                last = i;
                miss = 0;
            } else {
                ++miss;
                if (miss > gap) break;
            }
            --i;
        }
        return last;
    };

    auto walkRightTemporal = [&]() -> int {
        int i = peak;
        int miss = 0;
        int last = peak;
        while (i < total_frames) {
            if (signal[i] > threshold) {
                last = i;
                miss = 0;
            } else {
                ++miss;
                if (miss > gap) break;
            }
            ++i;
        }
        return last;
    };

    int onset = walkLeft();
    int end = peak;

    if (end_rule == "temporal") {
        end = walkRightTemporal();
    } else {
        // Presence rule
        int lo = std::max(0, onset - 120);
        int hi = std::max(lo + 1, onset - 20);
        if (hi <= lo) {
            lo = 0;
            hi = std::min(total_frames, std::max(1, onset));
        }

        size_t ds_pixels = static_cast<size_t>(downsample_w) * downsample_h;
        std::vector<int16_t> bg(ds_pixels, 0);

        int sample_count = hi - lo;
        if (sample_count > 0 && frame_getter) {
            // Temporal median of background
            std::vector<std::vector<int16_t>> bg_frames;
            bg_frames.reserve(sample_count);
            for (int i = lo; i < hi; ++i) {
                bg_frames.push_back(frame_getter(i));
            }

            std::vector<int16_t> col_vals(sample_count);
            for (size_t p = 0; p < ds_pixels; ++p) {
                for (int s = 0; s < sample_count; ++s) {
                    col_vals[s] = (p < bg_frames[s].size()) ? bg_frames[s][p] : 0;
                }
                std::nth_element(col_vals.begin(), col_vals.begin() + sample_count / 2, col_vals.end());
                bg[p] = col_vals[sample_count / 2];
            }
        }

        std::vector<int16_t> peak_frame = frame_getter ? frame_getter(peak) : std::vector<int16_t>();
        std::vector<uint8_t> mask(ds_pixels, 0);
        size_t mask_sum = 0;
        for (size_t p = 0; p < ds_pixels && p < peak_frame.size(); ++p) {
            if (std::abs(peak_frame[p] - bg[p]) > 40) {
                mask[p] = 1;
                ++mask_sum;
            }
        }

        if (mask_sum < 10) {
            end = walkRightTemporal();
        } else {
            int end_scan = std::min(total_frames, peak + 1500);
            int scan_len = end_scan - peak;
            std::vector<double> presence(scan_len, 0.0);

            for (int k = 0; k < scan_len; ++k) {
                auto cur = frame_getter(peak + k);
                int count = 0;
                for (size_t p = 0; p < ds_pixels && p < cur.size(); ++p) {
                    if (mask[p] && std::abs(cur[p] - bg[p]) > 25) {
                        ++count;
                    }
                }
                presence[k] = count;
            }

            // Moving average over window 21
            int win = 21;
            std::vector<double> smoothed(scan_len, 0.0);
            int half_w = win / 2;
            for (int k = 0; k < scan_len; ++k) {
                int w_lo = std::max(0, k - half_w);
                int w_hi = std::min(scan_len, k + half_w + 1);
                double s = 0.0;
                for (int j = w_lo; j < w_hi; ++j) s += presence[j];
                smoothed[k] = s / (w_hi - w_lo);
            }

            double p_min = *std::min_element(smoothed.begin(), smoothed.end());
            double t_low = std::max(2.0, 1.8 * p_min);

            // Find first run of 25 consecutive frames below t_low after peak + 8
            int hold = 25;
            int consecutive = 0;
            int found_end = peak + scan_len - 1;

            for (int k = 8; k < scan_len; ++k) {
                if (smoothed[k] <= t_low) {
                    ++consecutive;
                    if (consecutive >= hold) {
                        found_end = peak + (k - hold + 1);
                        break;
                    }
                } else {
                    consecutive = 0;
                }
            }

            end = std::max(peak, found_end);
        }
    }

    InjectionBounds bounds;
    bounds.onset_frame = onset;
    bounds.end_frame = end;
    bounds.peak_frame = peak;
    bounds.copy_start = std::max(0, onset - before_pad);
    bounds.copy_end = std::min(total_frames - 1, end + after_pad);
    bounds.pre_frames = onset - bounds.copy_start;
    bounds.post_frames = bounds.copy_end - end;
    bounds.extracted_count = bounds.copy_end - bounds.copy_start + 1;
    bounds.total_burst_frames = total_frames;
    bounds.max_signal = peak_val;
    bounds.end_rule = end_rule;
    bounds.detected = true;

    return bounds;
}

} // namespace hsc
