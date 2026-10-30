#include "piston_track.h"
#include "src/foundation/tls_fit.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace hsc {

BarrelProfile buildBarrelProfile(const std::vector<const uint8_t*>& sample_frames, int width, int height)
{
    BarrelProfile prof;
    prof.valid = false;
    if (sample_frames.empty() || width <= 0 || height <= 0) return prof;

    size_t npix = static_cast<size_t>(width) * height;
    std::vector<uint8_t> max_img(npix, 0);
    std::vector<uint8_t> min_img(npix, 255);

    for (const uint8_t* frame : sample_frames) {
        if (!frame) continue;
        for (size_t i = 0; i < npix; ++i) {
            max_img[i] = std::max(max_img[i], frame[i]);
            min_img[i] = std::min(min_img[i], frame[i]);
        }
    }

    // 10th percentile of min_img, 90th percentile of max_img
    std::vector<uint8_t> min_copy = min_img;
    std::vector<uint8_t> max_copy = max_img;
    std::nth_element(min_copy.begin(), min_copy.begin() + npix / 10, min_copy.end());
    std::nth_element(max_copy.begin(), max_copy.begin() + (npix * 9) / 10, max_copy.end());

    prof.v_dark = min_copy[npix / 10];
    prof.v_bright = max_copy[(npix * 9) / 10];

    if (prof.v_bright - prof.v_dark < 25.0) { // MIN_CONTRAST
        return prof;
    }

    prof.t_body = prof.v_dark + 0.08 * (prof.v_bright - prof.v_dark);
    double t_mid = 0.5 * (prof.v_bright + prof.v_dark);

    // Bright rows: count pixels in max_img >= t_mid
    std::vector<int> row_bright(height, 0);
    for (int y = 0; y < height; ++y) {
        int count = 0;
        for (int x = 0; x < width; ++x) {
            if (max_img[static_cast<size_t>(y) * width + x] >= t_mid) ++count;
        }
        row_bright[y] = count;
    }

    int y_start = -1, y_end = -1;
    for (int y = 0; y < height; ++y) {
        if (row_bright[y] >= width * 0.35) {
            if (y_start < 0) y_start = y;
            y_end = y;
        }
    }

    if (y_start < 0 || y_end - y_start < 8) return prof;

    // Inset row band by 12%
    int band_height = y_end - y_start + 1;
    int inset = static_cast<int>(band_height * 0.12);
    prof.y_top = y_start + inset;
    prof.y_bot = y_end - inset;

    if (prof.y_bot - prof.y_top < 6) {
        prof.y_top = y_start;
        prof.y_bot = y_end;
    }

    prof.valid = true;
    return prof;
}

PistonFrameEdge measurePistonEdge(const uint8_t* gray, int width, int height, const BarrelProfile& prof)
{
    PistonFrameEdge edge;
    edge.detected = false;
    if (!gray || !prof.valid || width <= 0 || height <= 0) return edge;

    std::vector<std::pair<double, double>> pts;

    for (int y = prof.y_top; y <= prof.y_bot; ++y) {
        const uint8_t* row = gray + static_cast<size_t>(y) * width;

        // 1D Gaussian smooth row (sigma = 1.0, 3-tap [1, 2, 1]/4 approximation)
        std::vector<double> smooth(width);
        smooth[0] = row[0];
        smooth[width - 1] = row[width - 1];
        for (int x = 1; x < width - 1; ++x) {
            smooth[x] = 0.25 * (row[x - 1] + 2.0 * row[x] + row[x + 1]);
        }

        // Find first run of at least 30 px darker than prof.t_body
        int run_start = -1;
        int current_run = 0;
        for (int x = 0; x < width; ++x) {
            if (smooth[x] <= prof.t_body) {
                if (current_run == 0) run_start = x;
                ++current_run;
                if (current_run >= 30 || (x == width - 1 && current_run >= 8)) {
                    break;
                }
            } else {
                current_run = 0;
                run_start = -1;
            }
        }

        if (run_start >= 0 && current_run >= 8) {
            // Find steepest bright -> dark transition (minimum gradient) within +/- 4 px
            int g_lo = std::max(1, run_start - 4);
            int g_hi = std::min(width - 2, run_start + 4);

            int best_x = g_lo;
            double min_grad = smooth[g_lo + 1] - smooth[g_lo - 1];

            for (int x = g_lo; x <= g_hi; ++x) {
                double g = smooth[x + 1] - smooth[x - 1];
                if (g < min_grad) {
                    min_grad = g;
                    best_x = x;
                }
            }

            // Parabolic vertex offset
            double g_m1 = smooth[best_x] - smooth[best_x - 2];
            double g_0  = smooth[best_x + 1] - smooth[best_x - 1];
            double g_p1 = smooth[best_x + 2] - smooth[best_x];

            double denom = g_m1 - 2.0 * g_0 + g_p1;
            double off = 0.0;
            if (std::abs(denom) > 1e-9) {
                off = 0.5 * (g_m1 - g_p1) / denom;
                if (std::abs(off) > 0.5) off = 0.0;
            }

            pts.push_back({static_cast<double>(y), best_x + off});
        }
    }

    if (pts.size() < 6) return edge;

    edge.edge_points = pts;
    // Initial robust median x
    std::vector<double> xs;
    for (const auto& p : pts) xs.push_back(p.second);
    edge.x_edge = computeMedian(xs);
    edge.detected = true;

    return edge;
}

std::vector<double> applyCommonSlope(const std::vector<PistonFrameEdge>& edges, int height)
{
    size_t n = edges.size();
    std::vector<double> aligned(n, 0.0);
    if (n == 0) return aligned;

    // Pool centered (y, x - median) points across all detected frames
    std::vector<std::pair<double, double>> pooled;
    for (const auto& e : edges) {
        if (!e.detected || e.edge_points.size() < 4) continue;
        std::vector<double> xs;
        for (const auto& p : e.edge_points) xs.push_back(p.second);
        double med_x = computeMedian(xs);

        for (const auto& p : e.edge_points) {
            pooled.push_back({p.first, p.second - med_x}); // (y, x_centered)
        }
    }

    double k_common = 0.0;
    if (pooled.size() >= 12) {
        // Fit line x = k * y + b
        auto line = tlsFit(pooled);
        if (line.valid && std::abs(line.vx) > 1e-6) {
            k_common = line.vy / line.vx;
        }
    }

    double y_center = 0.5 * height;

    for (size_t i = 0; i < n; ++i) {
        if (!edges[i].detected || edges[i].edge_points.empty()) {
            aligned[i] = (i > 0) ? aligned[i - 1] : 0.0;
            continue;
        }

        std::vector<double> intercepts;
        for (const auto& p : edges[i].edge_points) {
            // b_j = x_j - k_common * y_j
            intercepts.push_back(p.second - k_common * p.first);
        }

        double b_med = computeMedian(intercepts);
        aligned[i] = k_common * y_center + b_med;
    }

    return aligned;
}

PistonStrokeBounds detectPistonBounds(const std::vector<double>& positions)
{
    PistonStrokeBounds bounds;
    bounds.detected = false;
    int n = static_cast<int>(positions.size());
    bounds.total_frames = n;
    if (n < 25) return bounds;

    // Rest baseline from first 20 frames
    std::vector<double> head(positions.begin(), positions.begin() + 20);
    double x_base = computeMedian(head);

    std::vector<double> head_dev(20);
    for (int i = 0; i < 20; ++i) head_dev[i] = std::abs(head[i] - x_base);
    double sigma_base = robustSigma(head_dev);

    double total_span = std::abs(positions.back() - x_base);
    double t_stroke = std::max({0.6, 5.0 * sigma_base, 0.05 * total_span});

    // Find confirmed motion index
    int motion_idx = -1;
    for (int i = 0; i < n - 3; ++i) {
        if (std::abs(positions[i] - x_base) > t_stroke &&
            std::abs(positions[i + 1] - x_base) > t_stroke &&
            std::abs(positions[i + 2] - x_base) > t_stroke) {
            motion_idx = i;
            break;
        }
    }

    if (motion_idx < 0) return bounds;

    // Walk back with local step
    int mid_stroke_idx = (motion_idx + n) / 2;
    double delta_mid = std::abs(positions[std::min(n - 1, mid_stroke_idx + 1)] -
                                positions[std::max(0, mid_stroke_idx - 1)]) * 0.5;

    double step_floor = 0.25 * std::max(0.5, delta_mid);
    int onset = motion_idx;
    int consec_low = 0;

    for (int i = motion_idx; i > 0; --i) {
        double step = std::abs(positions[i] - positions[i - 1]);
        if (step <= step_floor) {
            ++consec_low;
            if (consec_low >= 5) {
                onset = i;
                break;
            }
        } else {
            consec_low = 0;
        }
    }

    // Plateau detection
    int plateau_idx = n - 1;
    double t_plateau = std::max(0.6, 0.25 * delta_mid * 15.0);

    for (int i = motion_idx + 10; i < n - 15; ++i) {
        double min_val = positions[i];
        double max_val = positions[i];
        for (int j = 0; j < 15; ++j) {
            min_val = std::min(min_val, positions[i + j]);
            max_val = std::max(max_val, positions[i + j]);
        }
        if ((max_val - min_val) <= t_plateau) {
            plateau_idx = i;
            break;
        }
    }

    bounds.start_frame = onset;
    bounds.end_frame = plateau_idx;
    bounds.total_travel_px = std::abs(positions[plateau_idx] - positions[onset]);
    bounds.detected = (bounds.total_travel_px > 5.0 && bounds.end_frame > bounds.start_frame);

    return bounds;
}

} // namespace hsc
