#pragma once

#include <optional>
#include <vector>
#include <QString>
#include <QRect>

namespace hsc {

struct EdgeInfo {
    bool horizontal = true;
    double k = 0.0;
    double b = 0.0;
    QRect roi;
};

struct ScaleCalibration {
    double mm_per_px = 0.0;
    double ref_mm = 5.0;
    double distance_px = 0.0;
    EdgeInfo edge1;
    EdgeInfo edge2;
    QString mode = "step";
    int image_width = 0;
    int image_height = 0;
    QString created_at;

    bool isValid() const { return mm_per_px > 0.0 && distance_px > 0.0; }
};

class ScaleCalibrationStore {
public:
    static std::optional<ScaleCalibration> load();
    static bool save(const ScaleCalibration& cal, QString* error = nullptr);
};

} // namespace hsc
