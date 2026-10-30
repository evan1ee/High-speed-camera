#include "measure_piston.h"
#include "piston_plot.h"
#include "src/foundation/app_paths.h"
#include "src/foundation/bmp_io.h"
#include "src/foundation/tls_fit.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

namespace hsc {

PistonMeasureResult measurePistonFolder(const std::filesystem::path& folder,
                                      const InjectorGeometry& geom,
                                      const std::optional<ScaleCalibration>& cal,
                                      std::function<void(int, int)> progress)
{
    PistonMeasureResult res;
    res.run_name = QString::fromStdString(folder.filename().string());
    res.folder_path = folder;
    res.valid = false;
    res.fps = geom.fallback_fps;

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
    if (n_total < 10) return res;

    // Load first frame for dimensions
    int width = 0, height = 0;
    std::vector<uint8_t> dummy;
    if (!loadGrayBmp(files[0], width, height, dummy)) return res;

    // Sample up to 60 frames for barrel profile
    int sample_count = std::min(60, n_total);
    std::vector<std::vector<uint8_t>> sample_bufs(sample_count);
    std::vector<const uint8_t*> sample_ptrs(sample_count);

    for (int i = 0; i < sample_count; ++i) {
        int idx = static_cast<int>(i * (n_total - 1) / std::max(1, sample_count - 1));
        loadGrayBmp(files[idx], width, height, sample_bufs[i]);
        sample_ptrs[i] = sample_bufs[i].data();
    }

    auto prof = buildBarrelProfile(sample_ptrs, width, height);
    if (!prof.valid) return res;

    // Track each frame
    std::vector<PistonFrameEdge> edges(n_total);
    for (int i = 0; i < n_total; ++i) {
        if (progress) progress(i + 1, n_total * 2);

        std::vector<uint8_t> frame_pixels;
        if (!loadGrayBmp(files[i], width, height, frame_pixels)) continue;

        edges[i] = measurePistonEdge(frame_pixels.data(), width, height, prof);
        edges[i].frame_index = i;
    }

    // Common slope pooling & alignment
    auto raw_positions = applyCommonSlope(edges, height);

    // Detect stroke bounds
    auto bounds = detectPistonBounds(raw_positions);
    if (!bounds.detected) {
        bounds.start_frame = 0;
        bounds.end_frame = n_total - 1;
    }

    int start_i = bounds.start_frame;
    int end_i = bounds.end_frame;
    int stroke_len = end_i - start_i + 1;
    if (stroke_len < 3) return res;

    // Resolve scale mm/px
    double mm_per_px = 0.052;
    if (cal && cal->isValid()) {
        mm_per_px = cal->mm_per_px;
    } else {
        auto loaded_cal = ScaleCalibrationStore::load();
        if (loaded_cal && loaded_cal->isValid()) {
            mm_per_px = loaded_cal->mm_per_px;
        }
    }

    // Timebase resolution
    auto meta_path = folder / "piston_capture.json";
    std::vector<double> raw_timestamps;
    double meta_fps = geom.fallback_fps;

    if (std::filesystem::exists(meta_path)) {
        QFile mf(QString::fromStdString(meta_path.string()));
        if (mf.open(QIODevice::ReadOnly)) {
            QJsonDocument mdoc = QJsonDocument::fromJson(mf.readAll());
            if (mdoc.isObject()) {
                auto obj = mdoc.object();
                if (obj.contains("fps")) meta_fps = obj.value("fps").toDouble(meta_fps);
                QJsonArray ts = obj.contains("frame_times_us") ? obj.value("frame_times_us").toArray()
                                                              : obj.value("timestamps").toArray();
                if (ts.size() == n_total) {
                    for (int i = 0; i < n_total; ++i) raw_timestamps.push_back(ts[i].toDouble());
                }
            }
        }
    }

    auto tb = resolveTimebase(raw_timestamps, n_total, meta_fps);
    res.fps = tb.implied_fps;
    double dt = (res.fps > 0.0) ? (1.0 / res.fps) : (1.0 / geom.fallback_fps);

    res.times_s.resize(stroke_len);
    res.travel_mm.resize(stroke_len);

    double x0 = raw_positions[start_i];
    double t_start = tb.times_s[start_i];
    for (int i = 0; i < stroke_len; ++i) {
        int orig_idx = start_i + i;
        res.times_s[i] = tb.times_s[orig_idx] - t_start;
        res.travel_mm[i] = std::abs(raw_positions[orig_idx] - x0) * mm_per_px;
    }

    // Velocity derivative via Savitzky-Golay
    res.speed_mm_s = savgolDerivative15(res.travel_mm, dt);


    // Fluid mechanics conversion: continuity & stagnation pressure
    double d_barrel = geom.barrel_diameter_mm;
    double d_orifice = geom.orifice_diameter_mm;
    double area_ratio = (d_barrel * d_barrel) / (d_orifice * d_orifice);
    double rho = geom.fluid_density_kg_m3;

    res.jet_speed_m_s.resize(stroke_len);
    res.pressure_MPa.resize(stroke_len);

    for (int i = 0; i < stroke_len; ++i) {
        double v_piston = std::max(0.0, res.speed_mm_s[i]);
        double v_jet = v_piston * area_ratio * 1e-3; // mm/s -> m/s
        double p_stag = 0.5 * rho * v_jet * v_jet * 1e-6; // Pa -> MPa

        res.jet_speed_m_s[i] = v_jet;
        res.pressure_MPa[i] = p_stag;
    }

    res.stroke_mm = res.travel_mm.back();
    res.duration_ms = res.times_s.back() * 1000.0;
    res.peak_speed_mm_s = *std::max_element(res.speed_mm_s.begin(), res.speed_mm_s.end());
    res.peak_jet_speed_m_s = *std::max_element(res.jet_speed_m_s.begin(), res.jet_speed_m_s.end());
    res.peak_jet_pressure_MPa = *std::max_element(res.pressure_MPa.begin(), res.pressure_MPa.end());

    // Write CSV report: <run>_speed.csv
    auto csv_path = folder / (res.run_name.toStdString() + "_speed.csv");
    std::ofstream csv(csv_path);
    if (csv) {
        csv << "Frame,Time (s),Position (px),Travel (mm),Speed (mm/s),Jet Speed (m/s),Stagnation Pressure (MPa)\n";
        for (int i = 0; i < stroke_len; ++i) {
            int orig_idx = start_i + i;
            csv << files[orig_idx].filename().string() << ","
                << std::fixed << std::setprecision(6) << res.times_s[i] << ","
                << std::setprecision(2) << raw_positions[orig_idx] << ","
                << std::setprecision(3) << res.travel_mm[i] << ","
                << std::setprecision(1) << res.speed_mm_s[i] << ","
                << std::setprecision(1) << res.jet_speed_m_s[i] << ","
                << std::setprecision(2) << res.pressure_MPa[i] << "\n";
        }
    }
    res.csv_path = csv_path;

    // Render curves plot: <run>_piston_curves.png
    auto plot_path = folder / (res.run_name.toStdString() + "_piston_curves.png");
    renderPistonPlots(res, plot_path);
    res.plot_path = plot_path;

    res.valid = true;
    return res;
}

} // namespace hsc
