#include "piston_plot.h"

#include <algorithm>
#include <cmath>
#include <QColor>
#include <QFont>
#include <QImage>
#include <QPainter>
#include <QPainterPath>
#include <QPen>

namespace hsc {

static void drawPanel(QPainter& p, const QRect& rect, const QString& title,
                      const QString& y_label, const std::vector<double>& t_ms,
                      const std::vector<double>& y_vals, const QColor& color)
{
    p.save();
    p.setClipRect(rect);

    // Background & border
    p.fillRect(rect, QColor(248, 249, 250));
    p.setPen(QColor(220, 224, 230));
    p.drawRect(rect.adjusted(0, 0, -1, -1));

    if (t_ms.empty() || y_vals.empty() || t_ms.size() != y_vals.size()) {
        p.restore();
        return;
    }

    int pad_left = 65, pad_right = 20, pad_top = 35, pad_bot = 35;
    QRect plot_area(rect.left() + pad_left, rect.top() + pad_top,
                    rect.width() - pad_left - pad_right, rect.height() - pad_top - pad_bot);

    // Title
    QFont title_font = p.font();
    title_font.setPointSize(9);
    title_font.setBold(true);
    p.setFont(title_font);
    p.setPen(QColor(50, 60, 75));
    p.drawText(rect.left() + pad_left, rect.top() + 20, QString("%1 (%2)").arg(title, y_label));

    double min_x = t_ms.front();
    double max_x = t_ms.back();
    if (std::abs(max_x - min_x) < 1e-6) max_x = min_x + 1.0;

    double min_y = 0.0;
    double max_y = *std::max_element(y_vals.begin(), y_vals.end());
    if (max_y <= 0.0) max_y = 1.0;
    max_y *= 1.15; // margin

    // Grid lines & Y ticks
    QFont label_font = p.font();
    label_font.setPointSize(8);
    label_font.setBold(false);
    p.setFont(label_font);

    int n_y_ticks = 4;
    for (int i = 0; i <= n_y_ticks; ++i) {
        double val = min_y + (max_y - min_y) * (static_cast<double>(i) / n_y_ticks);
        int py = plot_area.bottom() - static_cast<int>((val - min_y) / (max_y - min_y) * plot_area.height());

        p.setPen(QPen(QColor(230, 235, 240), 1, Qt::DashLine));
        p.drawLine(plot_area.left(), py, plot_area.right(), py);

        p.setPen(QColor(100, 110, 125));
        p.drawText(rect.left(), py - 8, pad_left - 8, 16, Qt::AlignRight | Qt::AlignVCenter,
                   QString::number(val, 'f', (max_y < 10.0) ? 2 : 1));
    }

    // X ticks
    int n_x_ticks = 5;
    for (int i = 0; i <= n_x_ticks; ++i) {
        double val = min_x + (max_x - min_x) * (static_cast<double>(i) / n_x_ticks);
        int px = plot_area.left() + static_cast<int>((val - min_x) / (max_x - min_x) * plot_area.width());

        p.setPen(QPen(QColor(230, 235, 240), 1, Qt::DashLine));
        p.drawLine(px, plot_area.top(), px, plot_area.bottom());

        p.setPen(QColor(100, 110, 125));
        p.drawText(px - 30, plot_area.bottom() + 6, 60, 16, Qt::AlignCenter,
                   QString::number(val, 'f', 1));
    }

    // Axes
    p.setPen(QPen(QColor(150, 160, 175), 1.2));
    p.drawLine(plot_area.bottomLeft(), plot_area.bottomRight());
    p.drawLine(plot_area.bottomLeft(), plot_area.topLeft());

    // X axis unit
    p.drawText(plot_area.right() - 40, plot_area.bottom() + 20, 50, 16, Qt::AlignRight, "Time (ms)");

    // Curve
    QPainterPath path;
    bool first = true;
    for (size_t i = 0; i < t_ms.size(); ++i) {
        double x_val = t_ms[i];
        double y_val = y_vals[i];

        int px = plot_area.left() + static_cast<int>((x_val - min_x) / (max_x - min_x) * plot_area.width());
        int py = plot_area.bottom() - static_cast<int>((y_val - min_y) / (max_y - min_y) * plot_area.height());
        px = std::clamp(px, plot_area.left(), plot_area.right());
        py = std::clamp(py, plot_area.top(), plot_area.bottom());

        if (first) {
            path.moveTo(px, py);
            first = false;
        } else {
            path.lineTo(px, py);
        }
    }

    p.setRenderHint(QPainter::Antialiasing, true);
    p.setPen(QPen(color, 2.0));
    p.drawPath(path);

    p.restore();
}

bool renderPistonPlots(const PistonMeasureResult& res,
                       const std::filesystem::path& out_path,
                       int width, int height)
{
    if (!res.valid || res.times_s.empty()) return false;

    QImage img(width, height, QImage::Format_RGB888);
    img.fill(QColor(255, 255, 255));

    QPainter painter(&img);
    painter.setRenderHint(QPainter::Antialiasing, true);

    // Title banner
    QFont main_font = painter.font();
    main_font.setPointSize(12);
    main_font.setBold(true);
    painter.setFont(main_font);
    painter.setPen(QColor(20, 30, 45));

    QString banner = QString("Piston Hydrodynamics: %1 | Stroke: %2 mm | Peak: %3 mm/s | Jet: %4 m/s (%5 MPa)")
                         .arg(res.run_name)
                         .arg(QString::number(res.stroke_mm, 'f', 2))
                         .arg(QString::number(res.peak_speed_mm_s, 'f', 1))
                         .arg(QString::number(res.peak_jet_speed_m_s, 'f', 1))
                         .arg(QString::number(res.peak_jet_pressure_MPa, 'f', 2));
    painter.drawText(20, 30, banner);

    // Time in milliseconds relative to start
    std::vector<double> t_ms(res.times_s.size());
    double t0 = res.times_s.front();
    for (size_t i = 0; i < res.times_s.size(); ++i) {
        t_ms[i] = (res.times_s[i] - t0) * 1000.0;
    }

    // 3 panels vertically
    int top_margin = 45;
    int bottom_margin = 15;
    int total_h = height - top_margin - bottom_margin;
    int panel_h = (total_h - 20) / 3;

    QRect r1(20, top_margin, width - 40, panel_h);
    QRect r2(20, top_margin + panel_h + 10, width - 40, panel_h);
    QRect r3(20, top_margin + (panel_h + 10) * 2, width - 40, panel_h);

    drawPanel(painter, r1, "Displacement vs Time", "Displacement (mm)", t_ms, res.travel_mm, QColor(0, 114, 206));
    drawPanel(painter, r2, "Piston Velocity vs Time", "Speed (mm/s)", t_ms, res.speed_mm_s, QColor(40, 167, 69));
    drawPanel(painter, r3, "Stagnation Impact Pressure vs Time", "Pressure (MPa)", t_ms, res.pressure_MPa, QColor(220, 53, 69));

    painter.end();
    return img.save(QString::fromStdString(out_path.string()), "PNG");
}

} // namespace hsc
