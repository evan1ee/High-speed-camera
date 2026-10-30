#include "tls_fit.h"

#include <algorithm>
#include <cmath>
#include <random>

namespace hsc {

double computeMedian(std::vector<double> v)
{
    if (v.empty()) return 0.0;
    size_t n = v.size();
    size_t mid = n / 2;
    std::nth_element(v.begin(), v.begin() + mid, v.end());
    if (n % 2 != 0) {
        return v[mid];
    }
    double v_mid = v[mid];
    auto max_it = std::max_element(v.begin(), v.begin() + mid);
    return 0.5 * (*max_it + v_mid);
}

double robustSigma(std::vector<double> residuals)
{
    if (residuals.empty()) return 0.0;
    double med = computeMedian(residuals);
    std::vector<double> dev(residuals.size());
    for (size_t i = 0; i < residuals.size(); ++i) {
        dev[i] = std::abs(residuals[i] - med);
    }
    double mad = computeMedian(dev);
    return 1.4826 * mad;
}

double parabolicVertexOffset(const double* g, int i, int n)
{
    if (i <= 0 || i >= n - 1) return 0.0;
    double a = g[i - 1];
    double b = g[i];
    double c = g[i + 1];
    double denom = a - 2.0 * b + c;
    if (std::abs(denom) < 1e-12) return 0.0;
    double offset = 0.5 * (a - c) / denom;
    if (!std::isfinite(offset) || std::abs(offset) > 0.5) return 0.0;
    return offset;
}

TlsLine tlsFit(const std::vector<std::pair<double, double>>& points)
{
    TlsLine line;
    line.valid = false;
    size_t n = points.size();
    if (n < 2) return line;

    double sum_x = 0.0, sum_y = 0.0;
    for (const auto& p : points) {
        sum_x += p.first;
        sum_y += p.second;
    }
    double mean_x = sum_x / n;
    double mean_y = sum_y / n;

    double cxx = 0.0, cyy = 0.0, cxy = 0.0;
    for (const auto& p : points) {
        double dx = p.first - mean_x;
        double dy = p.second - mean_y;
        cxx += dx * dx;
        cyy += dy * dy;
        cxy += dx * dy;
    }
    cxx /= n;
    cyy /= n;
    cxy /= n;

    // Largest eigenvalue of 2x2 covariance matrix
    double tr = cxx + cyy;
    double disc = std::sqrt((cxx - cyy) * (cxx - cyy) + 4.0 * cxy * cxy);
    double lambda_max = 0.5 * (tr + disc);

    double vx = 1.0, vy = 0.0;
    if (std::abs(cxy) > 1e-12) {
        vx = lambda_max - cyy;
        vy = cxy;
    } else if (cxx >= cyy) {
        vx = 1.0;
        vy = 0.0;
    } else {
        vx = 0.0;
        vy = 1.0;
    }

    double len = std::hypot(vx, vy);
    if (len < 1e-12) len = 1.0;
    vx /= len;
    vy /= len;

    // Canonical orientation: vx >= 0
    if (vx < 0.0 || (std::abs(vx) < 1e-12 && vy < 0.0)) {
        vx = -vx;
        vy = -vy;
    }

    line.vx = vx;
    line.vy = vy;
    if (std::abs(vx) > 1e-9) {
        line.k = vy / vx;
        line.b = mean_y - line.k * mean_x;
    } else {
        line.k = 1e9;
        line.b = mean_y - line.k * mean_x;
    }

    // Residuals (orthogonal distances: |vy*(x - mean_x) - vx*(y - mean_y)|)
    std::vector<double> res(n);
    double sum_sq = 0.0;
    for (size_t i = 0; i < n; ++i) {
        double dx = points[i].first - mean_x;
        double dy = points[i].second - mean_y;
        double d = std::abs(vy * dx - vx * dy);
        res[i] = d;
        sum_sq += d * d;
    }

    line.inliers_count = n;
    line.rms_residual = std::sqrt(sum_sq / n);
    line.valid = true;
    return line;
}

TlsLine ransacTlsFit(const std::vector<std::pair<double, double>>& points,
                     double threshold, int max_iters)
{
    if (points.size() < 2) return tlsFit(points);
    if (points.size() <= 4) return tlsFit(points);

    std::mt19937 rng(42);
    std::uniform_int_distribution<size_t> dist(0, points.size() - 1);

    size_t best_inliers_count = 0;
    std::vector<uint8_t> best_mask(points.size(), 0);

    for (int iter = 0; iter < max_iters; ++iter) {
        size_t idx1 = dist(rng);
        size_t idx2 = dist(rng);
        if (idx1 == idx2) continue;

        double x1 = points[idx1].first, y1 = points[idx1].second;
        double x2 = points[idx2].first, y2 = points[idx2].second;
        double dx = x2 - x1, dy = y2 - y1;
        double len = std::hypot(dx, dy);
        if (len < 1e-6) continue;

        double nx = -dy / len;
        double ny = dx / len;

        size_t inliers = 0;
        std::vector<uint8_t> mask(points.size(), 0);
        for (size_t i = 0; i < points.size(); ++i) {
            double d = std::abs(nx * (points[i].first - x1) + ny * (points[i].second - y1));
            if (d <= threshold) {
                mask[i] = 1;
                ++inliers;
            }
        }

        if (inliers > best_inliers_count) {
            best_inliers_count = inliers;
            best_mask = std::move(mask);
            if (best_inliers_count >= points.size() * 0.95) break;
        }
    }

    std::vector<std::pair<double, double>> inlier_points;
    inlier_points.reserve(best_inliers_count);
    for (size_t i = 0; i < points.size(); ++i) {
        if (best_mask[i]) {
            inlier_points.push_back(points[i]);
        }
    }

    if (inlier_points.size() < 2) {
        return tlsFit(points);
    }

    TlsLine final_line = tlsFit(inlier_points);
    final_line.inliers_count = inlier_points.size();
    return final_line;
}

std::vector<double> savgolDerivative15(const std::vector<double>& y, double dt)
{
    size_t n = y.size();
    std::vector<double> dy(n, 0.0);
    if (n < 2) return dy;
    if (std::abs(dt) < 1e-12) dt = 1.0;

    const int m = 7; // W = 15 = 2*m + 1
    // Filter weight c_j = j / (280 * dt)
    const double factor = 1.0 / (280.0 * dt);

    for (size_t i = 0; i < n; ++i) {
        if (i >= static_cast<size_t>(m) && i + m < n) {
            double sum = 0.0;
            for (int j = -m; j <= m; ++j) {
                sum += j * y[i + j];
            }
            dy[i] = sum * factor;
        } else {
            // Forward/backward difference near endpoints
            if (i > 0 && i + 1 < n) {
                dy[i] = (y[i + 1] - y[i - 1]) / (2.0 * dt);
            } else if (i == 0) {
                dy[i] = (y[1] - y[0]) / dt;
            } else {
                dy[i] = (y[n - 1] - y[n - 2]) / dt;
            }
        }
    }
    return dy;
}

std::vector<double> savgolSmooth21(const std::vector<double>& y)
{
    size_t n = y.size();
    if (n < 5) return y;

    // Base half-window: m=10 (W=21) for full-length vectors, adapted down for short vectors
    int m = 10;
    if (n < 21) {
        if (n >= 15) m = 7;
        else if (n >= 11) m = 5;
        else if (n >= 7) m = 3;
        else m = 2;
    }

    std::vector<double> s(n, 0.0);

    for (size_t i = 0; i < n; ++i) {
        int cur_m = std::min(m, static_cast<int>(std::min(i, n - 1 - i)));
        if (cur_m >= 2) {
            double m_d = static_cast<double>(cur_m);
            double denom = (2.0 * m_d - 1.0) * (2.0 * m_d + 1.0) * (2.0 * m_d + 3.0);
            double num_const = 3.0 * (3.0 * m_d * m_d + 3.0 * m_d - 1.0);
            double sum = 0.0;
            for (int j = -cur_m; j <= cur_m; ++j) {
                double w = (num_const - 15.0 * j * j) / denom;
                sum += w * y[i + j];
            }
            s[i] = sum;
        } else if (cur_m == 1) {
            s[i] = (y[i - 1] + y[i] + y[i + 1]) / 3.0;
        } else {
            s[i] = y[i];
        }
    }

    // Extrapolate endpoints to smoothly dampen boundary noise
    if (n >= 3) {
        s[0] = 2.0 * s[1] - s[2];
        s[n - 1] = 2.0 * s[n - 2] - s[n - 3];
    }

    return s;
}

TimebaseResult resolveTimebase(const std::vector<double>& raw_timestamps,
                               int n, double fallback_fps, double tol)
{
    TimebaseResult res;
    if (n < 2) {
        res.times_s = {0.0};
        res.implied_fps = fallback_fps;
        res.source_name = "fallback";
        res.verified = false;
        return res;
    }

    double ref_fps = (fallback_fps > 0.0) ? fallback_fps : 1048.0;

    if (raw_timestamps.size() == static_cast<size_t>(n) && raw_timestamps.back() > raw_timestamps.front()) {
        struct UnitCand {
            const char* name;
            double factor; // multiply (raw - raw0) by factor to get seconds
        };
        const UnitCand cands[] = {
            {"us", 1e-6},
            {"camera_ticks_100ns", 1e-7},
            {"ms", 1e-3},
            {"ns", 1e-9},
            {"s", 1.0}
        };

        double best_err = 1e9;
        const UnitCand* best_cand = nullptr;
        double best_implied = ref_fps;

        double delta_raw = raw_timestamps.back() - raw_timestamps.front();
        for (const auto& c : cands) {
            double total_s = delta_raw * c.factor;
            if (total_s <= 0.0) continue;
            double implied = static_cast<double>(n - 1) / total_s;
            double err = std::abs(implied - ref_fps) / ref_fps;
            if (err <= tol && err < best_err) {
                best_err = err;
                best_cand = &c;
                best_implied = implied;
            }
        }

        if (best_cand) {
            res.times_s.resize(n);
            double base = raw_timestamps.front();
            for (int i = 0; i < n; ++i) {
                res.times_s[i] = (raw_timestamps[i] - base) * best_cand->factor;
            }
            res.implied_fps = best_implied;
            res.source_name = std::string("timestamps (") + best_cand->name + ")";
            res.verified = true;
            return res;
        }
    }

    // Fallback: uniform sampling based on ref_fps
    res.times_s.resize(n);
    double dt = 1.0 / ref_fps;
    for (int i = 0; i < n; ++i) {
        res.times_s[i] = i * dt;
    }
    res.implied_fps = ref_fps;
    res.source_name = "fps fallback";
    res.verified = false;
    return res;
}

} // namespace hsc

