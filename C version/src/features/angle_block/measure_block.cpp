#include "measure_block.h"
#include "src/foundation/tls_fit.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <queue>
#include <vector>

namespace hsc {

static const double kPi = 3.14159265358979323846;

BlockMeasureResult measureAngleBlock(const uint8_t* gray, int width, int height,
                                    const std::filesystem::path& out_dir)
{
    BlockMeasureResult res;
    res.valid = false;
    if (!gray || width < 10 || height < 10) return res;

    // 1. 5x5 Gaussian blur
    std::vector<uint8_t> blur(static_cast<size_t>(width) * height, 0);
    std::vector<int> temp(static_cast<size_t>(width) * height, 0);

    for (int y = 0; y < height; ++y) {
        const uint8_t* row = gray + static_cast<size_t>(y) * width;
        int* t_row = temp.data() + static_cast<size_t>(y) * width;
        for (int x = 0; x < width; ++x) {
            int x_m2 = std::max(0, x - 2);
            int x_m1 = std::max(0, x - 1);
            int x_p1 = std::min(width - 1, x + 1);
            int x_p2 = std::min(width - 1, x + 2);
            t_row[x] = row[x_m2] + 4 * row[x_m1] + 6 * row[x] + 4 * row[x_p1] + row[x_p2];
        }
    }
    for (int y = 0; y < height; ++y) {
        int y_m2 = std::max(0, y - 2);
        int y_m1 = std::max(0, y - 1);
        int y_p1 = std::min(height - 1, y + 1);
        int y_p2 = std::min(height - 1, y + 2);

        const int* r_m2 = temp.data() + static_cast<size_t>(y_m2) * width;
        const int* r_m1 = temp.data() + static_cast<size_t>(y_m1) * width;
        const int* r_c  = temp.data() + static_cast<size_t>(y) * width;
        const int* r_p1 = temp.data() + static_cast<size_t>(y_p1) * width;
        const int* r_p2 = temp.data() + static_cast<size_t>(y_p2) * width;

        uint8_t* out_row = blur.data() + static_cast<size_t>(y) * width;
        for (int x = 0; x < width; ++x) {
            int val = r_m2[x] + 4 * r_m1[x] + 6 * r_c[x] + 4 * r_p1[x] + r_p2[x];
            out_row[x] = static_cast<uint8_t>(std::clamp((val + 128) / 256, 0, 255));
        }
    }

    // 2. Otsu threshold
    int hist[256] = {0};
    int total_pix = width * height;
    for (int i = 0; i < total_pix; ++i) hist[blur[i]]++;

    double sum = 0.0;
    for (int i = 0; i < 256; ++i) sum += i * hist[i];

    double sum_b = 0.0;
    int w_b = 0;
    double max_var = 0.0;
    uint8_t otsu_thresh = 128;

    for (int t = 0; t < 256; ++t) {
        w_b += hist[t];
        if (w_b == 0) continue;
        int w_f = total_pix - w_b;
        if (w_f == 0) break;

        sum_b += t * hist[t];
        double m_b = sum_b / w_b;
        double m_f = (sum - sum_b) / w_f;
        double var = static_cast<double>(w_b) * static_cast<double>(w_f) * (m_b - m_f) * (m_b - m_f);
        if (var > max_var) {
            max_var = var;
            otsu_thresh = static_cast<uint8_t>(t);
        }
    }

    // Binary mask
    std::vector<uint8_t> bin(total_pix, 0);
    int fg_count = 0;
    for (int i = 0; i < total_pix; ++i) {
        if (blur[i] >= otsu_thresh) {
            bin[i] = 1;
            ++fg_count;
        }
    }

    // If foreground is majority, flip so object is minority
    if (fg_count > total_pix / 2) {
        for (int i = 0; i < total_pix; ++i) {
            bin[i] = bin[i] ? 0 : 1;
        }
    }

    // 3. Find largest 8-connected component
    std::vector<int> labels(total_pix, 0);
    int cur_label = 1;
    int max_area = 0;
    int best_label = 0;

    const int dx[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
    const int dy[8] = {-1, -1, -1, 0, 0, 1, 1, 1};

    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            size_t idx = static_cast<size_t>(y) * width + x;
            if (bin[idx] && labels[idx] == 0) {
                int area = 0;
                std::queue<std::pair<int, int>> q;
                q.push({x, y});
                labels[idx] = cur_label;

                while (!q.empty()) {
                    auto pt = q.front();
                    q.pop();
                    ++area;

                    for (int dir = 0; dir < 8; ++dir) {
                        int nx = pt.first + dx[dir];
                        int ny = pt.second + dy[dir];
                        if (nx >= 0 && nx < width && ny >= 0 && ny < height) {
                            size_t n_idx = static_cast<size_t>(ny) * width + nx;
                            if (bin[n_idx] && labels[n_idx] == 0) {
                                labels[n_idx] = cur_label;
                                q.push({nx, ny});
                            }
                        }
                    }
                }

                if (area > max_area) {
                    max_area = area;
                    best_label = cur_label;
                }
                ++cur_label;
            }
        }
    }

    if (max_area < 0.003 * total_pix || best_label == 0) return res;

    // Bounding box of best component
    int x_min = width, x_max = -1;
    int y_min = height, y_max = -1;
    std::vector<int> col_ytop(width, height);
    std::vector<int> col_ybot(width, -1);

    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (labels[static_cast<size_t>(y) * width + x] == best_label) {
                x_min = std::min(x_min, x);
                x_max = std::max(x_max, x);
                y_min = std::min(y_min, y);
                y_max = std::max(y_max, y);
                col_ytop[x] = std::min(col_ytop[x], y);
                col_ybot[x] = std::max(col_ybot[x], y);
            }
        }
    }

    if (x_max <= x_min || y_max <= y_min) return res;

    // 4. Boundary extraction across component columns (skip 5% at ends)
    int span_x = x_max - x_min + 1;
    int skip_x = std::max(2, static_cast<int>(span_x * 0.05));
    int scan_start = x_min + skip_x;
    int scan_end = x_max - skip_x;

    std::vector<std::pair<double, double>> pts_up, pts_lo;

    for (int x = scan_start; x <= scan_end; ++x) {
        int yt = col_ytop[x];
        int yb = col_ybot[x];
        if (yt >= yb || yb < 0 || yt >= height) continue;

        // Subpixel gradient peak near top edge
        int seg_top_0 = std::max(0, yt - 4);
        int seg_top_1 = std::min(height - 1, yt + 4);
        int len_t = seg_top_1 - seg_top_0 + 1;
        if (len_t >= 4) {
            std::vector<double> g(len_t, 0.0);
            for (int i = 1; i < len_t - 1; ++i) {
                int y_cur = seg_top_0 + i;
                g[i] = 0.5 * (static_cast<double>(blur[static_cast<size_t>(y_cur + 1) * width + x]) -
                             static_cast<double>(blur[static_cast<size_t>(y_cur - 1) * width + x]));
            }
            int best_it = 1;
            double best_mag = std::abs(g[1]);
            for (int i = 1; i < len_t - 1; ++i) {
                if (std::abs(g[i]) > best_mag) {
                    best_mag = std::abs(g[i]);
                    best_it = i;
                }
            }
            double off = parabolicVertexOffset(g.data(), best_it, len_t);
            pts_up.push_back({static_cast<double>(x), seg_top_0 + best_it + off});
        }

        // Subpixel gradient peak near bottom edge
        int seg_bot_0 = std::max(0, yb - 4);
        int seg_bot_1 = std::min(height - 1, yb + 4);
        int len_b = seg_bot_1 - seg_bot_0 + 1;
        if (len_b >= 4) {
            std::vector<double> g(len_b, 0.0);
            for (int i = 1; i < len_b - 1; ++i) {
                int y_cur = seg_bot_0 + i;
                g[i] = 0.5 * (static_cast<double>(blur[static_cast<size_t>(y_cur + 1) * width + x]) -
                             static_cast<double>(blur[static_cast<size_t>(y_cur - 1) * width + x]));
            }
            int best_ib = 1;
            double best_mag = std::abs(g[1]);
            for (int i = 1; i < len_b - 1; ++i) {
                if (std::abs(g[i]) > best_mag) {
                    best_mag = std::abs(g[i]);
                    best_ib = i;
                }
            }
            double off = parabolicVertexOffset(g.data(), best_ib, len_b);
            pts_lo.push_back({static_cast<double>(x), seg_bot_0 + best_ib + off});
        }
    }

    if (pts_up.size() < 8 || pts_lo.size() < 8) return res;

    // 5. Savitzky-Golay smoothing on edges
    std::vector<double> y_up(pts_up.size());
    for (size_t i = 0; i < pts_up.size(); ++i) y_up[i] = pts_up[i].second;
    auto y_up_s = savgolSmooth21(y_up);

    std::vector<double> y_lo(pts_lo.size());
    for (size_t i = 0; i < pts_lo.size(); ++i) y_lo[i] = pts_lo[i].second;
    auto y_lo_s = savgolSmooth21(y_lo);

    std::vector<std::pair<double, double>> smooth_up(pts_up.size());
    for (size_t i = 0; i < pts_up.size(); ++i) smooth_up[i] = {pts_up[i].first, y_up_s[i]};

    std::vector<std::pair<double, double>> smooth_lo(pts_lo.size());
    for (size_t i = 0; i < pts_lo.size(); ++i) smooth_lo[i] = {pts_lo[i].first, y_lo_s[i]};

    // 6. RANSAC + TLS fit on upper and lower edge
    res.line1 = ransacTlsFit(smooth_up, 2.0);
    res.line2 = ransacTlsFit(smooth_lo, 2.0);

    if (!res.line1.valid || !res.line2.valid) return res;

    // 7. Calculate acute angle
    double rad = std::abs(std::atan(res.line1.k) - std::atan(res.line2.k));
    res.angle_deg = rad * (180.0 / kPi);

    // 8. Output CSV if requested
    if (!out_dir.empty()) {
        auto csv_path = out_dir / "block_angles.csv";
        std::ofstream csv(csv_path);
        if (csv) {
            csv << "Line1 Slope,Line1 Intercept,Line2 Slope,Line2 Intercept,Measured Angle (deg)\n";
            csv << std::fixed << std::setprecision(6) << res.line1.k << ","
                << std::setprecision(2) << res.line1.b << ","
                << std::setprecision(6) << res.line2.k << ","
                << std::setprecision(2) << res.line2.b << ","
                << std::setprecision(3) << res.angle_deg << "\n";
        }
        res.csv_path = csv_path;
    }

    res.valid = true;
    return res;
}

} // namespace hsc
