#include "erf_edge.h"

#include <algorithm>
#include <cmath>
#include <vector>

namespace hsc {

static const double kPi = 3.14159265358979323846;
static const double kSqrt2 = 1.41421356237309504880;
static const double kInvSqrtPi = 1.0 / 1.77245385090551602730;

// Solves 4x4 linear system A * x = b via Gaussian elimination with partial pivoting
static bool solve4x4(double A[4][4], double b[4], double x[4])
{
    for (int i = 0; i < 4; ++i) {
        int pivot = i;
        double max_val = std::abs(A[i][i]);
        for (int r = i + 1; r < 4; ++r) {
            double v = std::abs(A[r][i]);
            if (v > max_val) {
                max_val = v;
                pivot = r;
            }
        }
        if (max_val < 1e-12) return false;

        if (pivot != i) {
            for (int c = 0; c < 4; ++c) std::swap(A[i][c], A[pivot][c]);
            std::swap(b[i], b[pivot]);
        }

        double diag = A[i][i];
        for (int c = i; c < 4; ++c) A[i][c] /= diag;
        b[i] /= diag;

        for (int r = 0; r < 4; ++r) {
            if (r != i) {
                double factor = A[r][i];
                for (int c = i; c < 4; ++c) A[r][c] -= factor * A[i][c];
                b[r] -= factor * b[i];
            }
        }
    }

    for (int i = 0; i < 4; ++i) x[i] = b[i];
    return true;
}

ErfEdgeResult fitErfEdge(const std::vector<double>& seg, int peak, int /*core*/, bool is_top)
{
    ErfEdgeResult res;
    res.valid = false;

    int n = static_cast<int>(seg.size());
    int lo = std::max(0, peak - 5);
    int hi = std::min(n - 1, peak + 5);
    int m = hi - lo + 1;

    if (m < 4) return res;

    double vmin = seg[lo], vmax = seg[lo];
    for (int i = lo; i <= hi; ++i) {
        vmin = std::min(vmin, seg[i]);
        vmax = std::max(vmax, seg[i]);
    }

    if (vmax - vmin < 8.0) return res;

    double sign = is_top ? 1.0 : -1.0;

    // Parameters: p = [mu, sigma, base, amp]
    double mu = static_cast<double>(peak);
    double sigma = 1.0;
    double base = vmin;
    double amp = vmax - vmin;

    double lambda = 1e-2;

    auto evalModel = [&](double y, double c_mu, double c_sigma, double c_base, double c_amp) -> double {
        double z = sign * (y - c_mu) / (c_sigma * kSqrt2);
        return c_base + c_amp * 0.5 * (1.0 + std::erf(z));
    };

    auto calcResiduals = [&](double c_mu, double c_sigma, double c_base, double c_amp,
                             std::vector<double>& r, double& sse) {
        sse = 0.0;
        r.resize(m);
        for (int i = 0; i < m; ++i) {
            double y = lo + i;
            double diff = evalModel(y, c_mu, c_sigma, c_base, c_amp) - seg[lo + i];
            r[i] = diff;
            sse += diff * diff;
        }
    };

    std::vector<double> residuals;
    double current_sse = 0.0;
    calcResiduals(mu, sigma, base, amp, residuals, current_sse);

    // Levenberg-Marquardt optimization loop
    for (int iter = 0; iter < 40; ++iter) {
        double JtJ[4][4] = {0};
        double Jtr[4] = {0};

        for (int i = 0; i < m; ++i) {
            double y = lo + i;
            double z = sign * (y - mu) / (sigma * kSqrt2);
            double exp_z2 = std::exp(-z * z);
            double phi = 0.5 * (1.0 + std::erf(z));

            double d_mu = -amp * sign * exp_z2 / (sigma * std::sqrt(2.0 * kPi));
            double d_sigma = -amp * z * exp_z2 / (sigma * std::sqrt(kPi));
            double d_base = 1.0;
            double d_amp = phi;

            double J[4] = {d_mu, d_sigma, d_base, d_amp};
            double r = residuals[i];

            for (int r_idx = 0; r_idx < 4; ++r_idx) {
                Jtr[r_idx] += J[r_idx] * r;
                for (int c_idx = 0; c_idx < 4; ++c_idx) {
                    JtJ[r_idx][c_idx] += J[r_idx] * J[c_idx];
                }
            }
        }

        // Apply damping
        double A[4][4];
        for (int r = 0; r < 4; ++r) {
            for (int c = 0; c < 4; ++c) A[r][c] = JtJ[r][c];
            A[r][r] += lambda * (JtJ[r][r] + 1e-4);
        }

        double rhs[4];
        for (int r = 0; r < 4; ++r) rhs[r] = -Jtr[r];

        double delta[4];
        if (!solve4x4(A, rhs, delta)) {
            lambda *= 4.0;
            continue;
        }

        double new_mu = std::clamp(mu + delta[0], static_cast<double>(lo), static_cast<double>(hi));
        double new_sigma = std::clamp(sigma + delta[1], 0.3, 5.0);
        double new_base = std::clamp(base + delta[2], 0.0, 255.0);
        double new_amp = std::clamp(amp + delta[3], 8.0, 255.0);

        std::vector<double> new_residuals;
        double new_sse = 0.0;
        calcResiduals(new_mu, new_sigma, new_base, new_amp, new_residuals, new_sse);

        if (new_sse < current_sse) {
            mu = new_mu;
            sigma = new_sigma;
            base = new_base;
            amp = new_amp;
            current_sse = new_sse;
            residuals = std::move(new_residuals);
            lambda = std::max(1e-5, lambda * 0.5);

            if (std::abs(delta[0]) < 1e-4 && std::abs(delta[1]) < 1e-4) {
                break;
            }
        } else {
            lambda = std::min(1e5, lambda * 4.0);
        }
    }

    double rmse = std::sqrt(current_sse / m);
    double conf = std::clamp(1.0 - (rmse / std::max(amp, 1e-6)), 0.0, 1.0);

    if (conf <= 0.0) return res;

    res.valid = true;
    res.subpixel_pos = mu;
    res.confidence = conf;
    return res;
}

} // namespace hsc
