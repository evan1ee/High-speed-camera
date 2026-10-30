#include "measure_angle.h"
#include "erf_edge.h"
#include "src/foundation/app_paths.h"
#include "src/foundation/bmp_io.h"
#include "src/foundation/summary_calc.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <queue>
#include <sstream>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainter>
#include <QPen>

namespace hsc {

static const double kPi = 3.14159265358979323846;

static double ramp(double v, double v_good, double v_bad)
{
    if (v_good > v_bad) {
        if (v >= v_good) return 100.0;
        if (v <= v_bad) return 0.0;
        return ((v - v_bad) / (v_good - v_bad)) * 100.0;
    } else {
        if (v <= v_good) return 100.0;
        if (v >= v_bad) return 0.0;
        return ((v_bad - v) / (v_bad - v_good)) * 100.0;
    }
}

// 5x5 separable Gaussian blur [1, 4, 6, 4, 1] / 16
static std::vector<uint8_t> gaussianBlur5x5(const uint8_t* src, int w, int h)
{
    std::vector<uint8_t> out(static_cast<size_t>(w) * h, 0);
    std::vector<int> temp(static_cast<size_t>(w) * h, 0);

    // Horizontal pass
    for (int y = 0; y < h; ++y) {
        const uint8_t* row = src + static_cast<size_t>(y) * w;
        int* t_row = temp.data() + static_cast<size_t>(y) * w;
        for (int x = 0; x < w; ++x) {
            int x_m2 = std::max(0, x - 2);
            int x_m1 = std::max(0, x - 1);
            int x_p1 = std::min(w - 1, x + 1);
            int x_p2 = std::min(w - 1, x + 2);

            int val = row[x_m2] + 4 * row[x_m1] + 6 * row[x] + 4 * row[x_p1] + row[x_p2];
            t_row[x] = val;
        }
    }

    // Vertical pass
    for (int y = 0; y < h; ++y) {
        int y_m2 = std::max(0, y - 2);
        int y_m1 = std::max(0, y - 1);
        int y_p1 = std::min(h - 1, y + 1);
        int y_p2 = std::min(h - 1, y + 2);

        const int* r_m2 = temp.data() + static_cast<size_t>(y_m2) * w;
        const int* r_m1 = temp.data() + static_cast<size_t>(y_m1) * w;
        const int* r_c  = temp.data() + static_cast<size_t>(y) * w;
        const int* r_p1 = temp.data() + static_cast<size_t>(y_p1) * w;
        const int* r_p2 = temp.data() + static_cast<size_t>(y_p2) * w;

        uint8_t* out_row = out.data() + static_cast<size_t>(y) * w;
        for (int x = 0; x < w; ++x) {
            int val = r_m2[x] + 4 * r_m1[x] + 6 * r_c[x] + 4 * r_p1[x] + r_p2[x];
            out_row[x] = static_cast<uint8_t>(std::clamp((val + 128) / 256, 0, 255));
        }
    }

    return out;
}

static uint8_t computeOtsuThreshold(const uint8_t* src, int w, int h)
{
    int hist[256] = {0};
    int total_pixels = w * h;
    for (int i = 0; i < total_pixels; ++i) {
        hist[src[i]]++;
    }

    double sum = 0.0;
    for (int i = 0; i < 256; ++i) sum += i * hist[i];

    double sum_b = 0.0;
    int w_b = 0;
    double max_var = 0.0;
    uint8_t threshold = 0;

    for (int t = 0; t < 256; ++t) {
        w_b += hist[t];
        if (w_b == 0) continue;
        int w_f = total_pixels - w_b;
        if (w_f == 0) break;

        sum_b += t * hist[t];
        double m_b = sum_b / w_b;
        double m_f = (sum - sum_b) / w_f;

        double var_between = static_cast<double>(w_b) * static_cast<double>(w_f) * (m_b - m_f) * (m_b - m_f);
        if (var_between > max_var) {
            max_var = var_between;
            threshold = static_cast<uint8_t>(t);
        }
    }

    return threshold;
}

// 8-connected component segmentation, returns mask of largest component and area
static std::vector<uint8_t> findLargestComponent(const uint8_t* bin_mask, int w, int h, int& max_area)
{
    max_area = 0;
    std::vector<int> labels(static_cast<size_t>(w) * h, 0);
    int current_label = 1;
    std::vector<int> areas = {0};

    const int dx[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
    const int dy[8] = {-1, -1, -1, 0, 0, 1, 1, 1};

    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            size_t idx = static_cast<size_t>(y) * w + x;
            if (bin_mask[idx] && labels[idx] == 0) {
                // Flood fill
                int area = 0;
                std::queue<std::pair<int, int>> q;
                q.push({x, y});
                labels[idx] = current_label;

                while (!q.empty()) {
                    auto pt = q.front();
                    q.pop();
                    ++area;

                    for (int dir = 0; dir < 8; ++dir) {
                        int nx = pt.first + dx[dir];
                        int ny = pt.second + dy[dir];
                        if (nx >= 0 && nx < w && ny >= 0 && ny < h) {
                            size_t n_idx = static_cast<size_t>(ny) * w + nx;
                            if (bin_mask[n_idx] && labels[n_idx] == 0) {
                                labels[n_idx] = current_label;
                                q.push({nx, ny});
                            }
                        }
                    }
                }

                areas.push_back(area);
                if (area > max_area) {
                    max_area = area;
                }
                ++current_label;
            }
        }
    }

    std::vector<uint8_t> result(static_cast<size_t>(w) * h, 0);
    if (max_area < 120) return result; // MIN_AREA

    int best_label = 0;
    for (size_t i = 1; i < areas.size(); ++i) {
        if (areas[i] == max_area) {
            best_label = static_cast<int>(i);
            break;
        }
    }

    for (size_t i = 0; i < result.size(); ++i) {
        if (labels[i] == best_label) {
            result[i] = 255;
        }
    }

    return result;
}

FrameMeasureResult measureFrame(const uint8_t* gray, int width, int height,
                               const int16_t* bg,
                               const SprayMeasureOptions& opts,
                               const std::optional<NozzleReference>& ref,
                               double max_run_span)
{
    FrameMeasureResult res;
    res.valid = false;
    if (!gray || width <= 0 || height <= 0) return res;

    size_t npix = static_cast<size_t>(width) * height;
    std::vector<uint8_t> work(npix);

    // Preprocessing & background subtraction
    int hist[256] = {0};
    for (size_t i = 0; i < npix; ++i) {
        int v = gray[i];
        if (bg) {
            v = std::clamp(v - static_cast<int>(bg[i]), 0, 255);
        }
        work[i] = static_cast<uint8_t>(v);
        hist[work[i]]++;
    }

    // Check 99.5-th percentile brightness
    int target_count = static_cast<int>(npix * 0.995);
    int accum = 0;
    int p995 = 0;
    for (int i = 0; i < 256; ++i) {
        accum += hist[i];
        if (accum >= target_count) {
            p995 = i;
            break;
        }
    }

    if (p995 < 80) { // MIN_PEAK
        return res;
    }

    // Gaussian blur 5x5 + Otsu threshold
    auto blurred = gaussianBlur5x5(work.data(), width, height);
    uint8_t otsu_thresh = computeOtsuThreshold(blurred.data(), width, height);

    std::vector<uint8_t> bin_mask(npix, 0);
    for (size_t i = 0; i < npix; ++i) {
        if (blurred[i] >= otsu_thresh) bin_mask[i] = 255;
    }

    int comp_area = 0;
    auto comp = findLargestComponent(bin_mask.data(), width, height, comp_area);
    if (comp_area < 120) {
        return res;
    }

    // Jet span & bounding columns
    int x_min = width, x_max = -1;
    std::vector<int> col_ytop(width, height);
    std::vector<int> col_ybot(width, -1);

    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (comp[static_cast<size_t>(y) * width + x]) {
                x_min = std::min(x_min, x);
                x_max = std::max(x_max, x);
                col_ytop[x] = std::min(col_ytop[x], y);
                col_ybot[x] = std::max(col_ybot[x], y);
            }
        }
    }

    if (x_max <= x_min) return res;

    double jet_span = static_cast<double>(x_max - x_min);
    res.span_px = jet_span;

    // ROI columns (nozzle on right: nozzle_skip px away from right apex)
    int roi_start_x = (opts.nozzle_side > 0) ? (x_max - opts.nozzle_skip) : (x_min + opts.nozzle_skip);
    int roi_len = static_cast<int>(jet_span * opts.roi_frac);
    int roi_end_x = (opts.nozzle_side > 0) ? std::max(x_min, roi_start_x - roi_len)
                                          : std::min(x_max, roi_start_x + roi_len);

    int x_left = std::min(roi_start_x, roi_end_x);
    int x_right = std::max(roi_start_x, roi_end_x);
    x_left = std::clamp(x_left, 0, width - 1);
    x_right = std::clamp(x_right, 0, width - 1);

    int roi_width = x_right - x_left + 1;
    if (roi_width < 12) return res;

    // Extract edge candidate loci per ROI column
    std::vector<std::pair<double, double>> cand_grad_up, cand_grad_lo;
    std::vector<std::pair<double, double>> cand_vis_up, cand_vis_lo;
    std::vector<std::pair<double, double>> cand_erf_up, cand_erf_lo;

    for (int x = x_left; x <= x_right; ++x) {
        int y0 = col_ytop[x];
        int y1 = col_ybot[x];
        if (y0 >= y1 || y0 >= height || y1 < 0) continue;

        // Band outward expansion
        double v_core = 0.0;
        for (int y = y0; y <= y1; ++y) {
            v_core = std::max(v_core, static_cast<double>(blurred[static_cast<size_t>(y) * width + x]));
        }

        // Background estimate (20th percentile along column)
        std::vector<uint8_t> col_vals(height);
        for (int y = 0; y < height; ++y) col_vals[y] = blurred[static_cast<size_t>(y) * width + x];
        std::nth_element(col_vals.begin(), col_vals.begin() + height / 5, col_vals.end());
        double v_bg = static_cast<double>(col_vals[height / 5]);

        double t_band = v_bg + 0.15 * (v_core - v_bg);

        // Expand upward
        int cap = 12;
        while (y0 > 0 && cap-- > 0 && blurred[static_cast<size_t>(y0 - 1) * width + x] > t_band) {
            --y0;
        }
        // Expand downward
        cap = 12;
        while (y1 < height - 1 && cap-- > 0 && blurred[static_cast<size_t>(y1 + 1) * width + x] > t_band) {
            ++y1;
        }

        int seg_lo = std::max(0, y0 - 3);
        int seg_hi = std::min(height - 1, y1 + 3);
        int seg_len = seg_hi - seg_lo + 1;
        if (seg_len < 6) continue;

        std::vector<double> seg(seg_len);
        for (int i = 0; i < seg_len; ++i) {
            seg[i] = static_cast<double>(blurred[static_cast<size_t>(seg_lo + i) * width + x]);
        }

        // Find bright core
        auto max_it = std::max_element(seg.begin(), seg.end());
        int core_idx = static_cast<int>(std::distance(seg.begin(), max_it));

        // 1D vertical central-difference gradient
        std::vector<double> g(seg_len, 0.0);
        for (int i = 1; i < seg_len - 1; ++i) {
            g[i] = 0.5 * (seg[i + 1] - seg[i - 1]);
        }

        // Upper edge: maximum gradient above core
        int peak_up = 1;
        double max_g = g[1];
        for (int i = 1; i < core_idx; ++i) {
            if (g[i] > max_g) {
                max_g = g[i];
                peak_up = i;
            }
        }

        // Lower edge: minimum gradient below core
        int peak_lo = core_idx;
        double min_g = g[std::min(seg_len - 2, core_idx)];
        for (int i = core_idx; i < seg_len - 1; ++i) {
            if (g[i] < min_g) {
                min_g = g[i];
                peak_lo = i;
            }
        }

        // Parabolic vertex offsets
        double off_up = parabolicVertexOffset(g.data(), peak_up, seg_len);
        double off_lo = parabolicVertexOffset(g.data(), peak_lo, seg_len);

        double y_grad_up = seg_lo + peak_up + off_up;
        double y_grad_lo = seg_lo + peak_lo + off_lo;
        cand_grad_up.push_back({static_cast<double>(x), y_grad_up});
        cand_grad_lo.push_back({static_cast<double>(x), y_grad_lo});

        // Visible 25% crossing
        double t_vis = v_bg + 0.25 * (v_core - v_bg);
        // Upper edge walk upward from peak_up
        double y_vis_up = y_grad_up;
        for (int row = peak_up; row >= 0; --row) {
            if (seg[row] < t_vis && row + 1 < seg_len) {
                double den = seg[row + 1] - seg[row];
                double frac_cross = (den > 0) ? ((t_vis - seg[row]) / den) : 0.0;
                y_vis_up = seg_lo + row + frac_cross;
                break;
            }
        }
        cand_vis_up.push_back({static_cast<double>(x), y_vis_up});

        // Lower edge walk downward from peak_lo
        double y_vis_lo = y_grad_lo;
        for (int row = peak_lo; row < seg_len; ++row) {
            if (seg[row] < t_vis && row > 0) {
                double den = seg[row - 1] - seg[row];
                double frac_cross = (den > 0) ? ((seg[row - 1] - t_vis) / den) : 0.0;
                y_vis_lo = seg_lo + (row - 1) + frac_cross;
                break;
            }
        }
        cand_vis_lo.push_back({static_cast<double>(x), y_vis_lo});

        // Erf blurred-step model
        if (opts.use_erf) {
            auto erf_res_up = fitErfEdge(seg, peak_up, core_idx, true);
            if (erf_res_up.valid) {
                cand_erf_up.push_back({static_cast<double>(x), seg_lo + erf_res_up.subpixel_pos});
            } else {
                cand_erf_up.push_back({static_cast<double>(x), y_vis_up});
            }

            auto erf_res_lo = fitErfEdge(seg, peak_lo, core_idx, false);
            if (erf_res_lo.valid) {
                cand_erf_lo.push_back({static_cast<double>(x), seg_lo + erf_res_lo.subpixel_pos});
            } else {
                cand_erf_lo.push_back({static_cast<double>(x), y_vis_lo});
            }
        }
    }

    if (cand_grad_up.size() < 12 || cand_grad_lo.size() < 12) return res;

    // Straightness contest per edge
    auto pickBestLocus = [&](const std::vector<std::pair<double, double>>& c_grad,
                             const std::vector<std::pair<double, double>>& c_vis,
                             const std::vector<std::pair<double, double>>& c_erf) {
        auto calcSpread = [](const std::vector<std::pair<double, double>>& pts) -> double {
            if (pts.size() < 4) return 1e9;
            auto line = tlsFit(pts);
            std::vector<double> r(pts.size());
            for (size_t i = 0; i < pts.size(); ++i) {
                r[i] = pts[i].second - line.eval(pts[i].first);
            }
            return robustSigma(r);
        };

        double s_grad = calcSpread(c_grad);
        const auto* best_pts = &c_grad;
        double s_best = s_grad;

        double s_vis = calcSpread(c_vis);
        if (s_vis <= 1.10 * s_best) {
            best_pts = &c_vis;
            s_best = s_vis;
        }

        if (opts.use_erf && !c_erf.empty()) {
            double s_erf = calcSpread(c_erf);
            if (s_erf <= 1.10 * s_best) {
                best_pts = &c_erf;
            }
        }

        return *best_pts;
    };

    res.upper_pts = pickBestLocus(cand_grad_up, cand_vis_up, cand_erf_up);
    res.lower_pts = pickBestLocus(cand_grad_lo, cand_vis_lo, cand_erf_lo);

    // Savitzky-Golay smoothing on edge loci (W=21, poly=3)
    std::vector<double> y_up(res.upper_pts.size());
    for (size_t i = 0; i < res.upper_pts.size(); ++i) y_up[i] = res.upper_pts[i].second;
    auto y_up_s = savgolSmooth21(y_up);

    std::vector<double> y_lo(res.lower_pts.size());
    for (size_t i = 0; i < res.lower_pts.size(); ++i) y_lo[i] = res.lower_pts[i].second;
    auto y_lo_s = savgolSmooth21(y_lo);

    std::vector<std::pair<double, double>> smooth_pts_up(res.upper_pts.size());
    for (size_t i = 0; i < res.upper_pts.size(); ++i) {
        smooth_pts_up[i] = {res.upper_pts[i].first, y_up_s[i]};
    }
    std::vector<std::pair<double, double>> smooth_pts_lo(res.lower_pts.size());
    for (size_t i = 0; i < res.lower_pts.size(); ++i) {
        smooth_pts_lo[i] = {res.lower_pts[i].first, y_lo_s[i]};
    }

    // RANSAC + TLS fit on smoothed edge inliers
    res.line_upper = ransacTlsFit(smooth_pts_up, 2.5);
    res.line_lower = ransacTlsFit(smooth_pts_lo, 2.5);

    if (!res.line_upper.valid || !res.line_lower.valid) return res;

    // Quality residuals evaluated on RAW subpixel edges so SG filter cannot hide physical noise
    std::vector<double> raw_res_up(res.upper_pts.size());
    for (size_t i = 0; i < res.upper_pts.size(); ++i) {
        raw_res_up[i] = res.upper_pts[i].second - res.line_upper.eval(res.upper_pts[i].first);
    }
    res.line_upper.rms_residual = robustSigma(raw_res_up);

    std::vector<double> raw_res_lo(res.lower_pts.size());
    for (size_t i = 0; i < res.lower_pts.size(); ++i) {
        raw_res_lo[i] = res.lower_pts[i].second - res.line_lower.eval(res.lower_pts[i].first);
    }
    res.line_lower.rms_residual = robustSigma(raw_res_lo);


    // Angle calculations
    if (ref && ref->isValid()) {
        res.angle_upper = ref->angleDeviationDeg(res.line_upper.k);
        res.angle_lower = ref->angleDeviationDeg(res.line_lower.k);

        if (opts.angle_policy == "trusted") {
            // Check confidence of each edge
            double up_rms = res.line_upper.rms_residual;
            double lo_rms = res.line_lower.rms_residual;
            bool up_bad = (up_rms >= 1.0);
            bool lo_bad = (lo_rms >= 1.0);
            if (up_bad && !lo_bad) {
                res.angle = res.angle_lower;
            } else if (lo_bad && !up_bad) {
                res.angle = res.angle_upper;
            } else {
                res.angle = std::max(res.angle_upper, res.angle_lower);
            }
        } else {
            res.angle = std::max(res.angle_upper, res.angle_lower);
        }

        bool in_rect = ref->jetInRect(res.line_upper.k, res.line_upper.b, res.line_lower.k, res.line_lower.b);
        res.in_rect_verdict = in_rect ? "OK" : "NG";
    } else {
        // Free air opening angle: |atan(k_up) - atan(k_lo)|
        double rad = std::abs(std::atan(res.line_upper.k) - std::atan(res.line_lower.k));
        res.angle = rad * (180.0 / kPi);
        res.angle_upper = res.angle * 0.5;
        res.angle_lower = res.angle * 0.5;
        res.in_rect_verdict = "";
    }

    // Quality evaluation
    double max_rms = std::max(res.line_upper.rms_residual, res.line_lower.rms_residual);
    res.score_fit = ramp(max_rms, 0.25, 1.0); // QUALITY_RMS_GOOD=0.25, BAD=1.0

    double cov_frac = static_cast<double>(std::min(res.upper_pts.size(), res.lower_pts.size())) / roi_width;
    res.score_cov = ramp(cov_frac, 0.98, 0.80);

    double run_span_ref = (max_run_span > 0.0) ? max_run_span : res.span_px;
    double span_ratio = (run_span_ref > 0.0) ? (res.span_px / run_span_ref) : 1.0;
    res.score_span = ramp(span_ratio, 0.92, 0.60);

    res.quality_score = std::min({res.score_fit, res.score_cov, res.score_span});

    if (res.quality_score >= 75.0) {
        res.confidence_str = "High";
    } else if (res.quality_score >= 50.0) {
        res.confidence_str = "Medium";
    } else {
        res.confidence_str = "Low";
    }

    res.valid = true;
    return res;
}

FolderMeasureResult measureFolder(const std::filesystem::path& folder,
                                 const SprayMeasureOptions& opts,
                                 const std::optional<NozzleReference>& ref,
                                 std::function<void(int, int)> progress)
{
    FolderMeasureResult res;
    res.run_name = QString::fromStdString(folder.filename().string());
    res.folder_path = folder;
    res.valid = false;

    std::vector<std::filesystem::path> files;
    std::error_code ec;
    for (const auto& entry : std::filesystem::directory_iterator(folder, ec)) {
        if (!entry.is_regular_file()) continue;
        auto ext = entry.path().extension().string();
        std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
        if (ext == ".bmp") files.push_back(entry.path());
    }
    std::sort(files.begin(), files.end());

    int n_total = static_cast<int>(files.size());
    if (n_total == 0) return res;

    // Load first frame for dimensions
    int width = 0, height = 0;
    std::vector<uint8_t> dummy;
    if (!loadGrayBmp(files[0], width, height, dummy)) return res;

    // Compute background (pre-onset head if available via injection_meta.json, or 80-frame median)
    std::vector<int16_t> bg(static_cast<size_t>(width) * height, 0);
    int pre_frames = 0;
    auto meta_path = folder / "injection_meta.json";
    if (std::filesystem::exists(meta_path)) {
        QFile mf(QString::fromStdString(meta_path.string()));
        if (mf.open(QIODevice::ReadOnly)) {
            QJsonDocument mdoc = QJsonDocument::fromJson(mf.readAll());
            if (mdoc.isObject()) {
                pre_frames = mdoc.object().value("pre_frames").toInt(0);
            }
        }
    }

    int bg_sample_count = (pre_frames >= 8 && opts.use_pre_onset_bg)
                              ? std::min(pre_frames, n_total)
                              : std::min(80, n_total);

    std::vector<std::vector<uint8_t>> bg_frames;
    bg_frames.reserve(bg_sample_count);
    for (int i = 0; i < bg_sample_count; ++i) {
        int idx = (pre_frames >= 8 && opts.use_pre_onset_bg)
                      ? i
                      : static_cast<int>(i * (n_total - 1) / std::max(1, bg_sample_count - 1));
        std::vector<uint8_t> p;
        if (loadGrayBmp(files[idx], width, height, p)) {
            bg_frames.push_back(std::move(p));
        }
    }

    if (!bg_frames.empty()) {
        size_t bcount = bg_frames.size();
        std::vector<uint8_t> col_vals(bcount);
        for (size_t p = 0; p < bg.size(); ++p) {
            for (size_t s = 0; s < bcount; ++s) {
                col_vals[s] = bg_frames[s][p];
            }
            std::nth_element(col_vals.begin(), col_vals.begin() + bcount / 2, col_vals.end());
            bg[p] = static_cast<int16_t>(col_vals[bcount / 2]);
        }
    }

    // First pass: measure frames to find spans and candidate jet frames
    std::vector<FrameMeasureResult> all_frame_results(n_total);
    double max_span = 0.0;
    std::vector<int> jet_frame_indices;

    for (int i = 0; i < n_total; ++i) {
        if (progress) progress(i + 1, n_total * 2);

        std::vector<uint8_t> frame_pixels;
        if (!loadGrayBmp(files[i], width, height, frame_pixels)) continue;

        auto f_res = measureFrame(frame_pixels.data(), width, height, bg.data(), opts, ref, 0.0);
        f_res.frame_index = i;
        f_res.frame_name = QString::fromStdString(files[i].filename().string());

        if (f_res.valid) {
            max_span = std::max(max_span, f_res.span_px);
            jet_frame_indices.push_back(i);
        }
        all_frame_results[i] = f_res;
    }

    if (jet_frame_indices.empty()) return res;

    // Pick frames to measure: auto_pick vs fixed measure_from/to
    std::vector<int> selected_frames;

    if (opts.auto_pick_frames && jet_frame_indices.size() >= 10) {
        // Find 10 consecutive frames where span within 5% of median and angle spread <= 0.5 deg
        int best_start = -1;
        double best_score_sum = -1.0;

        for (size_t i = 0; i + 10 <= jet_frame_indices.size(); ++i) {
            // Check consecutive
            bool consec = true;
            for (size_t j = 0; j < 9; ++j) {
                if (jet_frame_indices[i + j + 1] != jet_frame_indices[i + j] + 1) {
                    consec = false;
                    break;
                }
            }
            if (!consec) continue;

            std::vector<double> spans;
            std::vector<double> angles;
            double score_sum = 0.0;

            for (size_t j = 0; j < 10; ++j) {
                int f_idx = jet_frame_indices[i + j];
                spans.push_back(all_frame_results[f_idx].span_px);
                angles.push_back(all_frame_results[f_idx].angle);
                score_sum += all_frame_results[f_idx].quality_score;
            }

            double med_span = computeMedian(spans);
            double min_span = *std::min_element(spans.begin(), spans.end());
            double max_span_win = *std::max_element(spans.begin(), spans.end());

            double min_ang = *std::min_element(angles.begin(), angles.end());
            double max_ang = *std::max_element(angles.begin(), angles.end());

            bool span_ok = (max_span_win - min_span) <= 0.05 * med_span;
            bool angle_ok = (max_ang - min_ang) <= 0.5;

            if (span_ok && angle_ok && score_sum > best_score_sum) {
                best_score_sum = score_sum;
                best_start = static_cast<int>(i);
            }
        }

        if (best_start >= 0) {
            for (int j = 0; j < 10; ++j) {
                selected_frames.push_back(jet_frame_indices[best_start + j]);
            }
        }
    }

    if (selected_frames.empty()) {
        // Fallback to measure_from .. measure_to (1-based from first jet frame)
        int start_k = std::clamp(opts.measure_from - 1, 0, static_cast<int>(jet_frame_indices.size()) - 1);
        int end_k = std::clamp(opts.measure_to - 1, start_k, static_cast<int>(jet_frame_indices.size()) - 1);
        for (int k = start_k; k <= end_k; ++k) {
            selected_frames.push_back(jet_frame_indices[k]);
        }
    }

    // Re-score selected frames with the known max_span
    std::vector<double> measured_angles;
    std::vector<std::pair<double, double>> pooled_up, pooled_lo;
    double quality_sum = 0.0;
    bool all_ok = true;

    // Create destination for annotated frames: <folder>/measure_<stamp>
    QString stamp = QDateTime::currentDateTime().toString("yyyyMMdd_hhmmss");
    auto out_measure_dir = folder / ("measure_" + stamp.toStdString());
    std::filesystem::create_directories(out_measure_dir, ec);

    for (size_t idx = 0; idx < selected_frames.size(); ++idx) {
        int f_idx = selected_frames[idx];
        if (progress) progress(n_total + static_cast<int>(idx) + 1, n_total * 2);

        std::vector<uint8_t> frame_pixels;
        if (!loadGrayBmp(files[f_idx], width, height, frame_pixels)) continue;

        auto f_res = measureFrame(frame_pixels.data(), width, height, bg.data(), opts, ref, max_span);
        f_res.frame_index = f_idx;
        f_res.frame_name = QString::fromStdString(files[f_idx].filename().string());

        if (f_res.valid) {
            res.frame_results.push_back(f_res);
            measured_angles.push_back(f_res.angle);
            quality_sum += f_res.quality_score;

            if (f_res.in_rect_verdict == "NG") all_ok = false;

            for (const auto& pt : f_res.upper_pts) pooled_up.push_back(pt);
            for (const auto& pt : f_res.lower_pts) pooled_lo.push_back(pt);

            // Render annotated frame
            auto annot_path = out_measure_dir / files[f_idx].filename();
            renderAnnotatedFrame(frame_pixels.data(), width, height, f_res, ref, opts.draw_ref_lines, annot_path);
            res.annotated_frame_paths.push_back(QString::fromStdString(annot_path.string()));
        }
    }

    if (measured_angles.empty()) return res;

    res.measured_count = static_cast<int>(measured_angles.size());
    auto angle_stats = computeStats(measured_angles);
    res.mean_angle = angle_stats.mean;
    res.std_angle = angle_stats.std;
    res.overall_confidence = quality_sum / res.measured_count;

    if (res.overall_confidence >= 75.0) {
        res.overall_confidence_str = "High";
    } else if (res.overall_confidence >= 50.0) {
        res.overall_confidence_str = "Medium";
    } else {
        res.overall_confidence_str = "Low";
    }

    if (ref && ref->isValid()) {
        res.in_rect_verdict = all_ok ? "OK" : "NG";
    } else {
        res.in_rect_verdict = "";
    }

    // Pooled fit
    if (!pooled_up.empty() && !pooled_lo.empty()) {
        auto p_up = ransacTlsFit(pooled_up, 2.5);
        auto p_lo = ransacTlsFit(pooled_lo, 2.5);
        if (p_up.valid && p_lo.valid) {
            if (ref && ref->isValid()) {
                double a_up = ref->angleDeviationDeg(p_up.k);
                double a_lo = ref->angleDeviationDeg(p_lo.k);
                res.pooled_angle = std::max(a_up, a_lo);
            } else {
                double rad = std::abs(std::atan(p_up.k) - std::atan(p_lo.k));
                res.pooled_angle = rad * (180.0 / kPi);
            }
        }
    }

    // Write CSV report: <run>_angles.csv
    auto csv_path = out_measure_dir / (res.run_name.toStdString() + "_angles.csv");
    std::ofstream csv(csv_path);
    if (csv) {
        csv << "Frame,Angle (deg),Angle Upper (deg),Angle Lower (deg),Confidence,Fit Score,Coverage Score,Span Score,In-Rect\n";
        for (const auto& fr : res.frame_results) {
            csv << fr.frame_name.toStdString() << ","
                << std::fixed << std::setprecision(2) << fr.angle << ","
                << fr.angle_upper << "," << fr.angle_lower << ","
                << fr.confidence_str.toStdString() << ","
                << std::setprecision(1) << fr.score_fit << ","
                << fr.score_cov << "," << fr.score_span << ","
                << fr.in_rect_verdict.toStdString() << "\n";
        }
        csv << "\nSummary,Mean Angle,Std Angle,Pooled Angle,Overall Confidence,Overall In-Rect\n";
        csv << "Values,"
            << std::fixed << std::setprecision(2) << res.mean_angle << ","
            << res.std_angle << "," << res.pooled_angle << ","
            << res.overall_confidence_str.toStdString() << ","
            << res.in_rect_verdict.toStdString() << "\n";
    }
    res.csv_path = csv_path;
    res.valid = true;

    return res;
}

bool renderAnnotatedFrame(const uint8_t* gray, int width, int height,
                          const FrameMeasureResult& res,
                          const std::optional<NozzleReference>& ref,
                          bool draw_ref_lines,
                          const std::filesystem::path& out_path)
{
    if (!gray || width <= 0 || height <= 0) return false;

    // Convert grayscale to QImage (Format_RGB888)
    QImage img(width, height, QImage::Format_RGB888);
    for (int y = 0; y < height; ++y) {
        const uint8_t* row = gray + static_cast<size_t>(y) * width;
        uint8_t* dest = img.scanLine(y);
        for (int x = 0; x < width; ++x) {
            uint8_t val = row[x];
            dest[x * 3 + 0] = val;
            dest[x * 3 + 1] = val;
            dest[x * 3 + 2] = val;
        }
    }

    QPainter painter(&img);
    painter.setRenderHint(QPainter::Antialiasing, true);

    // Draw reference lines if present & enabled
    if (ref && ref->isValid() && draw_ref_lines) {
        // Red target rectangle
        if (!ref->rect.isEmpty()) {
            painter.setPen(QPen(QColor(255, 0, 0), 1.0));
            painter.drawRect(ref->rect);
        }

        // Blue centerline spray axis
        painter.setPen(QPen(QColor(0, 128, 255), 1.0));
        painter.drawLine(ref->blue_a, ref->blue_b);

        // Yellow nozzle tip line
        painter.setPen(QPen(QColor(255, 255, 0), 1.5));
        painter.drawLine(ref->red_p0, ref->red_p1);
    }

    // Draw green fitted edge lines
    if (res.valid) {
        painter.setPen(QPen(QColor(0, 255, 0), 1.2));

        // Evaluate from x=0 to width-1
        double x0 = 0.0, x1 = static_cast<double>(width - 1);
        QPointF p_up0(x0, res.line_upper.eval(x0));
        QPointF p_up1(x1, res.line_upper.eval(x1));
        painter.drawLine(p_up0, p_up1);

        QPointF p_lo0(x0, res.line_lower.eval(x0));
        QPointF p_lo1(x1, res.line_lower.eval(x1));
        painter.drawLine(p_lo0, p_lo1);

        // Text banner: Angle and confidence
        QFont font = painter.font();
        font.setPointSize(9);
        font.setBold(true);
        painter.setFont(font);

        QString badge = QString("%1° (%2)").arg(QString::number(res.angle, 'f', 2), res.confidence_str);
        painter.setPen(QColor(0, 0, 0));
        painter.drawText(11, 19, badge);
        painter.setPen(QColor(0, 255, 0));
        painter.drawText(10, 18, badge);
    }

    painter.end();

    // Save as 24-bit BMP
    return img.save(QString::fromStdString(out_path.string()), "BMP");
}

} // namespace hsc
