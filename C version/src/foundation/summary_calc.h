#pragma once

#include <filesystem>
#include <map>
#include <string>
#include <vector>
#include <QString>

namespace hsc {

struct MetricStats {
    int n = 0;
    double mean = 0.0;
    double std = 0.0;
    double cv_percent = 0.0;
    double min = 0.0;
    double median = 0.0;
    double max = 0.0;
};

struct RunSpeedRecord {
    QString run_name;
    std::filesystem::path folder_path;
    double stroke_mm = 0.0;
    double peak_speed_mm_s = 0.0;
    double duration_ms = 0.0;
    double peak_jet_speed_m_s = 0.0;
    double peak_jet_pressure_MPa = 0.0;
    bool valid = false;
};

struct BatchSummary {
    std::vector<RunSpeedRecord> runs;
    MetricStats stroke_mm;
    MetricStats peak_speed_mm_s;
    MetricStats duration_ms;
    MetricStats peak_jet_speed_m_s;
    MetricStats peak_jet_pressure_MPa;

    bool exportCsv(const std::filesystem::path& out_path, QString* error = nullptr) const;
};

// Compute statistics for a vector of values
MetricStats computeStats(std::vector<double> values);

// Parse speed records from a list of folders
BatchSummary aggregateRuns(const std::vector<std::filesystem::path>& folders);

} // namespace hsc
