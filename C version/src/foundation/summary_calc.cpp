#include "summary_calc.h"
#include "tls_fit.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <iomanip>

namespace hsc {

MetricStats computeStats(std::vector<double> values)
{
    MetricStats stats;
    // Filter non-finite
    std::vector<double> clean;
    for (double v : values) {
        if (std::isfinite(v)) clean.push_back(v);
    }

    stats.n = static_cast<int>(clean.size());
    if (stats.n == 0) return stats;

    double sum = 0.0;
    for (double v : clean) sum += v;
    stats.mean = sum / stats.n;

    stats.min = *std::min_element(clean.begin(), clean.end());
    stats.max = *std::max_element(clean.begin(), clean.end());
    stats.median = computeMedian(clean);

    if (stats.n > 1) {
        double sq_sum = 0.0;
        for (double v : clean) {
            double d = v - stats.mean;
            sq_sum += d * d;
        }
        stats.std = std::sqrt(sq_sum / (stats.n - 1));
        if (std::abs(stats.mean) > 1e-9) {
            stats.cv_percent = (stats.std / std::abs(stats.mean)) * 100.0;
        }
    }

    return stats;
}

static bool parseSpeedCsv(const std::filesystem::path& csvPath, RunSpeedRecord& rec)
{
    std::ifstream f(csvPath);
    if (!f) return false;

    std::string line;
    std::getline(f, line); // header

    std::vector<double> travels;
    std::vector<double> speeds;
    std::vector<double> jet_speeds;
    std::vector<double> pressures;
    std::vector<double> times;

    while (std::getline(f, line)) {
        if (line.empty()) continue;
        std::stringstream ss(line);
        std::string item;
        std::vector<std::string> cols;
        while (std::getline(ss, item, ',')) {
            cols.push_back(item);
        }
        if (cols.size() < 4) continue;

        try {
            // cols: frame, time_s, pos_px, travel_mm, speed_mm_s, [jet_speed, pressure]
            double t = std::stod(cols[1]);
            double tr = std::stod(cols[3]);
            times.push_back(t);
            travels.push_back(tr);

            if (cols.size() >= 5) {
                double sp = std::stod(cols[4]);
                speeds.push_back(sp);
            }
            if (cols.size() >= 6) {
                double jsp = std::stod(cols[5]);
                jet_speeds.push_back(jsp);
            }
            if (cols.size() >= 7) {
                double pr = std::stod(cols[6]);
                pressures.push_back(pr);
            }
        } catch (...) {
            continue;
        }
    }

    if (times.empty() || travels.empty()) return false;

    rec.stroke_mm = travels.back() - travels.front();
    rec.duration_ms = (times.back() - times.front()) * 1000.0;

    if (!speeds.empty()) {
        rec.peak_speed_mm_s = *std::max_element(speeds.begin(), speeds.end());
    }
    if (!jet_speeds.empty()) {
        rec.peak_jet_speed_m_s = *std::max_element(jet_speeds.begin(), jet_speeds.end());
    }
    if (!pressures.empty()) {
        rec.peak_jet_pressure_MPa = *std::max_element(pressures.begin(), pressures.end());
    }

    rec.valid = true;
    return true;
}

BatchSummary aggregateRuns(const std::vector<std::filesystem::path>& folders)
{
    BatchSummary summary;

    std::vector<double> v_stroke;
    std::vector<double> v_speed;
    std::vector<double> v_duration;
    std::vector<double> v_jet_speed;
    std::vector<double> v_pressure;

    for (const auto& folder : folders) {
        // Look for *_speed.csv
        std::error_code ec;
        for (const auto& entry : std::filesystem::directory_iterator(folder, ec)) {
            if (!entry.is_regular_file()) continue;
            std::string name = entry.path().filename().string();
            if (name.find("_speed.csv") != std::string::npos || name == "speed.csv") {
                RunSpeedRecord rec;
                rec.run_name = QString::fromStdString(folder.filename().string());
                rec.folder_path = folder;
                if (parseSpeedCsv(entry.path(), rec)) {
                    summary.runs.push_back(rec);
                    v_stroke.push_back(rec.stroke_mm);
                    v_speed.push_back(rec.peak_speed_mm_s);
                    v_duration.push_back(rec.duration_ms);
                    v_jet_speed.push_back(rec.peak_jet_speed_m_s);
                    v_pressure.push_back(rec.peak_jet_pressure_MPa);
                }
                break;
            }
        }
    }

    summary.stroke_mm = computeStats(v_stroke);
    summary.peak_speed_mm_s = computeStats(v_speed);
    summary.duration_ms = computeStats(v_duration);
    summary.peak_jet_speed_m_s = computeStats(v_jet_speed);
    summary.peak_jet_pressure_MPa = computeStats(v_pressure);

    return summary;
}

bool BatchSummary::exportCsv(const std::filesystem::path& out_path, QString* error) const
{
    std::ofstream f(out_path);
    if (!f) {
        if (error) *error = QString("Cannot open %1 for writing").arg(QString::fromStdString(out_path.string()));
        return false;
    }

    f << "Run,Stroke (mm),Peak Speed (mm/s),Duration (ms),Peak Jet Speed (m/s),Peak Jet Pressure (MPa)\n";
    for (const auto& r : runs) {
        f << r.run_name.toStdString() << ","
          << std::fixed << std::setprecision(3) << r.stroke_mm << ","
          << std::fixed << std::setprecision(1) << r.peak_speed_mm_s << ","
          << std::fixed << std::setprecision(2) << r.duration_ms << ","
          << std::fixed << std::setprecision(1) << r.peak_jet_speed_m_s << ","
          << std::fixed << std::setprecision(2) << r.peak_jet_pressure_MPa << "\n";
    }

    auto writeSummaryRow = [&](const std::string& label, const MetricStats& s1, const MetricStats& s2,
                               const MetricStats& s3, const MetricStats& s4, const MetricStats& s5) {
        f << label << ","
          << s1.mean << "," << s2.mean << "," << s3.mean << "," << s4.mean << "," << s5.mean << "\n";
    };

    f << "\nStatistic,Stroke (mm),Peak Speed (mm/s),Duration (ms),Peak Jet Speed (m/s),Peak Jet Pressure (MPa)\n";
    f << "Mean," << stroke_mm.mean << "," << peak_speed_mm_s.mean << "," << duration_ms.mean << ","
      << peak_jet_speed_m_s.mean << "," << peak_jet_pressure_MPa.mean << "\n";
    f << "Std," << stroke_mm.std << "," << peak_speed_mm_s.std << "," << duration_ms.std << ","
      << peak_jet_speed_m_s.std << "," << peak_jet_pressure_MPa.std << "\n";
    f << "CV (%)," << stroke_mm.cv_percent << "%," << peak_speed_mm_s.cv_percent << "%," << duration_ms.cv_percent << "%,"
      << peak_jet_speed_m_s.cv_percent << "%," << peak_jet_pressure_MPa.cv_percent << "%\n";
    f << "Min," << stroke_mm.min << "," << peak_speed_mm_s.min << "," << duration_ms.min << ","
      << peak_jet_speed_m_s.min << "," << peak_jet_pressure_MPa.min << "\n";
    f << "Median," << stroke_mm.median << "," << peak_speed_mm_s.median << "," << duration_ms.median << ","
      << peak_jet_speed_m_s.median << "," << peak_jet_pressure_MPa.median << "\n";
    f << "Max," << stroke_mm.max << "," << peak_speed_mm_s.max << "," << duration_ms.max << ","
      << peak_jet_speed_m_s.max << "," << peak_jet_pressure_MPa.max << "\n";

    return f.good();
}

} // namespace hsc
