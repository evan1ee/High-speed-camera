#pragma once

#include "piston_track.h"
#include "src/foundation/calibration_store.h"

#include <filesystem>
#include <functional>
#include <optional>
#include <vector>
#include <QString>

namespace hsc {

struct InjectorGeometry {
    double barrel_diameter_mm = 6.12;
    double orifice_diameter_mm = 0.155;
    double fluid_density_kg_m3 = 1000.0;
    double fallback_fps = 1048.0;
};

struct PistonMeasureResult {
    QString run_name;
    std::filesystem::path folder_path;
    double stroke_mm = 0.0;
    double peak_speed_mm_s = 0.0;
    double duration_ms = 0.0;
    double peak_jet_speed_m_s = 0.0;
    double peak_jet_pressure_MPa = 0.0;
    double fps = 1048.0;

    std::vector<double> times_s;
    std::vector<double> travel_mm;
    std::vector<double> speed_mm_s;
    std::vector<double> jet_speed_m_s;
    std::vector<double> pressure_MPa;

    std::filesystem::path csv_path;
    std::filesystem::path plot_path;
    bool valid = false;
};

// Measures piston stroke, speed, and hydrodynamics for a folder
PistonMeasureResult measurePistonFolder(const std::filesystem::path& folder,
                                      const InjectorGeometry& geom = InjectorGeometry{},
                                      const std::optional<ScaleCalibration>& cal = std::nullopt,
                                      std::function<void(int, int)> progress = nullptr);

} // namespace hsc
