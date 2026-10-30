#pragma once

#include <optional>
#include <QPoint>
#include <QPointF>
#include <QRectF>
#include <QString>

class QPainter;

namespace hsc {



struct RectMm {
    double near_mm = 1.0;
    double far_mm = 6.51;
    double height_mm = 0.775;
};

struct NozzleReference {
    QPoint red_p0; // nozzle tip top
    QPoint red_p1; // nozzle tip bottom
    QPointF blue_a; // nozzle tip center
    QPointF blue_b; // spray axis point pointing left (along jet)
    QRectF rect; // target bounding box in px [x0, y0, x1, y1]
    RectMm rect_mm;
    int image_width = 0;
    int image_height = 0;
    QString created_at;

    bool isValid() const {
        return (red_p0 != red_p1) && (image_width > 0 && image_height > 0);
    }

    // Direction vector of spray axis (blue_a -> blue_b, normalized)
    QPointF axisDirection() const;

    // Acute deviation angle (in degrees) of a fitted edge line (k, b) from the blue spray axis
    double angleDeviationDeg(double k) const;

    // Jet-in-rectangle test: returns true (OK) if both upper and lower edge lines stay within rect at x_min and x_max
    bool jetInRect(double k_up, double b_up, double k_lo, double b_lo) const;

    // Renders reference overlays (yellow tip line, blue centerline, red target rect)
    void paint(QPainter& painter) const;
};


class NozzleReferenceStore {
public:
    static std::optional<NozzleReference> load();
    static bool save(const NozzleReference& ref, QString* error = nullptr);

    // Compute blue axis and target rect given tip endpoints (p0, p1) and mm_per_px
    static NozzleReference buildFromTip(const QPoint& p0, const QPoint& p1, double mm_per_px,
                                       int image_width, int image_height,
                                       const RectMm& rect_mm = RectMm{});
};

} // namespace hsc
