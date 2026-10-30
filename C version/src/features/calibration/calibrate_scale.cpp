#include "calibrate_scale.h"
#include "src/foundation/tls_fit.h"

#include <algorithm>
#include <cmath>

namespace hsc {

std::optional<EdgeInfo> detectEdgeInRoi(const uint8_t* gray, int width, int height,
                                       const QRect& roi, const QString& mode)
{
    if (!gray || width <= 0 || height <= 0 || roi.isEmpty()) return std::nullopt;

    int x0 = std::clamp(roi.left(), 0, width - 1);
    int x1 = std::clamp(roi.right(), 0, width - 1);
    int y0 = std::clamp(roi.top(), 0, height - 1);
    int y1 = std::clamp(roi.bottom(), 0, height - 1);

    if (x1 <= x0 || y1 <= y0) return std::nullopt;

    std::vector<std::pair<double, double>> pts;

    // Detect along vertical columns (horizontal edge)
    for (int x = x0; x <= x1; ++x) {
        int seg_len = y1 - y0 + 1;
        if (seg_len < 5) continue;

        std::vector<double> seg(seg_len);
        for (int i = 0; i < seg_len; ++i) {
            seg[i] = gray[static_cast<size_t>(y0 + i) * width + x];
        }

        // Gradient
        std::vector<double> g(seg_len, 0.0);
        for (int i = 1; i < seg_len - 1; ++i) {
            g[i] = 0.5 * (seg[i + 1] - seg[i - 1]);
        }

        int best_i = 1;
        double best_val = g[1];

        if (mode == "step" || mode == "dark") {
            // Find minimum gradient (dark edge) or maximum (bright edge)
            for (int i = 1; i < seg_len - 1; ++i) {
                if (std::abs(g[i]) > std::abs(best_val)) {
                    best_val = g[i];
                    best_i = i;
                }
            }
        } else {
            for (int i = 1; i < seg_len - 1; ++i) {
                if (g[i] > best_val) {
                    best_val = g[i];
                    best_i = i;
                }
            }
        }

        double off = parabolicVertexOffset(g.data(), best_i, seg_len);
        pts.push_back({static_cast<double>(x), y0 + best_i + off});
    }

    if (pts.size() < 6) return std::nullopt;

    auto line = ransacTlsFit(pts, 2.0);
    if (!line.valid) return std::nullopt;

    EdgeInfo edge;
    edge.horizontal = true;
    edge.k = line.k;
    edge.b = line.b;
    edge.roi = roi;

    return edge;
}

std::optional<ScaleCalibration> calibrateFromRois(const uint8_t* gray, int width, int height,
                                                const QRect& roi1, const QRect& roi2,
                                                double ref_mm, const QString& mode)
{
    auto e1 = detectEdgeInRoi(gray, width, height, roi1, mode);
    auto e2 = detectEdgeInRoi(gray, width, height, roi2, mode);

    if (!e1 || !e2) return std::nullopt;

    double k_avg = 0.5 * (e1->k + e2->k);
    double dist_px = std::abs(e2->b - e1->b) / std::sqrt(1.0 + k_avg * k_avg);

    if (dist_px < 5.0) return std::nullopt;

    ScaleCalibration cal;
    cal.mm_per_px = ref_mm / dist_px;
    cal.ref_mm = ref_mm;
    cal.distance_px = dist_px;
    cal.edge1 = *e1;
    cal.edge2 = *e2;
    cal.mode = mode;
    cal.image_width = width;
    cal.image_height = height;

    return cal;
}

AutoCalibResult autoCalibrate(const uint8_t* gray, int width, int height, double ref_mm)
{
    AutoCalibResult res;
    res.valid = false;
    if (!gray || width <= 0 || height <= 0) return res;

    // Scan left third: average vertical column profile
    int scan_w = std::min(width / 3, 100);
    std::vector<double> profile(height, 0.0);

    for (int y = 0; y < height; ++y) {
        double sum = 0.0;
        for (int x = 10; x < 10 + scan_w; ++x) {
            sum += gray[static_cast<size_t>(y) * width + x];
        }
        profile[y] = sum / scan_w;
    }

    // Vertical gradient
    std::vector<double> g(height, 0.0);
    for (int y = 1; y < height - 1; ++y) {
        g[y] = 0.5 * (profile[y + 1] - profile[y - 1]);
    }

    // Find two largest peaks in gradient (one positive, one negative)
    int peak_pos = -1, peak_neg = -1;
    double max_pos = 5.0, min_neg = -5.0;

    for (int y = 10; y < height - 10; ++y) {
        if (g[y] > max_pos) {
            max_pos = g[y];
            peak_pos = y;
        }
        if (g[y] < min_neg) {
            min_neg = g[y];
            peak_neg = y;
        }
    }

    if (peak_pos < 0 || peak_neg < 0) return res;

    int y_top = std::min(peak_pos, peak_neg);
    int y_bot = std::max(peak_pos, peak_neg);

    QRect r1(10, std::max(0, y_top - 15), scan_w, 30);
    QRect r2(10, std::min(height - 31, y_bot - 15), scan_w, 30);

    auto cal = calibrateFromRois(gray, width, height, r1, r2, ref_mm, "step");
    if (!cal) return res;

    res.valid = true;
    res.mm_per_px = cal->mm_per_px;
    res.distance_px = cal->distance_px;
    res.edge1 = cal->edge1;
    res.edge2 = cal->edge2;

    return res;
}

} // namespace hsc
