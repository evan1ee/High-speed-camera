#pragma once

#include <vector>
#include <utility>
#include <cstddef>
#include <string>

namespace hsc {


struct TlsLine {
    double k = 0.0;          // y = k*x + b
    double b = 0.0;
    double vx = 1.0;        // unit direction vector (vx >= 0)
    double vy = 0.0;
    size_t inliers_count = 0;
    double rms_residual = 0.0; // robust RMS
    bool valid = false;

    double eval(double x) const { return k * x + b; }
    double evalX(double y) const { return (std::abs(k) > 1e-9) ? ((y - b) / k) : 0.0; }
};

// Robust sigma: 1.4826 * MAD(residuals)
double robustSigma(std::vector<double> residuals);

// Median of a double vector (modifies/copies input)
double computeMedian(std::vector<double> v);

// Parabolic vertex subpixel offset in [-0.5, 0.5] from 3 samples g[i-1], g[i], g[i+1]
double parabolicVertexOffset(const double* g, int i, int n);

// Total Least Squares fit (orthogonal regression via PCA) on 2D points (x, y)
TlsLine tlsFit(const std::vector<std::pair<double, double>>& points);

// 2-point RANSAC outlier rejection + Total Least Squares fit
TlsLine ransacTlsFit(const std::vector<std::pair<double, double>>& points,
                     double threshold = 2.5, int max_iters = 100);

// Savitzky-Golay 1st derivative filter (W=15, poly=2, deriv=1)
// Returns derivative vector matching input size
std::vector<double> savgolDerivative15(const std::vector<double>& y, double dt);

// Savitzky-Golay smoothing filter (W=21, poly=3, deriv=0, with adaptive fallback for smaller series)
std::vector<double> savgolSmooth21(const std::vector<double>& y);

// Timebase resolution for hardware camera timestamps
struct TimebaseResult {
    std::vector<double> times_s;
    double implied_fps = 0.0;
    std::string source_name;
    bool verified = false;
};

// Infers timestamp units (us, 100ns ticks, ms, ns) against fallback frame rate
TimebaseResult resolveTimebase(const std::vector<double>& raw_timestamps,
                               int n, double fallback_fps, double tol = 0.05);

} // namespace hsc

