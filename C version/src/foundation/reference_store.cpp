#include "reference_store.h"
#include "app_paths.h"

#include <cmath>
#include <algorithm>
#include <QDateTime>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainter>
#include <QPen>

namespace hsc {

QPointF NozzleReference::axisDirection() const
{
    double dx = blue_b.x() - blue_a.x();
    double dy = blue_b.y() - blue_a.y();
    double len = std::hypot(dx, dy);
    if (len < 1e-9) return QPointF(-1.0, 0.0);
    return QPointF(dx / len, dy / len);
}

double NozzleReference::angleDeviationDeg(double k) const
{
    // Direction vector of the fitted edge line
    // Canonical: vx >= 0, so direction is (1.0, k) normalized
    double len = std::hypot(1.0, k);
    double vx = 1.0 / len;
    double vy = k / len;

    QPointF ad = axisDirection();
    double ax = ad.x();
    double ay = ad.y();

    // 2D dot product and cross product scalar
    double dot = ax * vx + ay * vy;
    double cross = ax * vy - ay * vx;

    double rad = std::atan2(std::abs(cross), std::abs(dot));
    return rad * (180.0 / 3.14159265358979323846);
}

bool NozzleReference::jetInRect(double k_up, double b_up, double k_lo, double b_lo) const
{
    if (rect.isEmpty()) return true;

    double x_min = rect.left();
    double x_max = rect.right();
    double y_min = rect.top();
    double y_max = rect.bottom();

    double up_y1 = k_up * x_min + b_up;
    double up_y2 = k_up * x_max + b_up;
    double lo_y1 = k_lo * x_min + b_lo;
    double lo_y2 = k_lo * x_max + b_lo;

    if (up_y1 < y_min || up_y1 > y_max) return false;
    if (up_y2 < y_min || up_y2 > y_max) return false;
    if (lo_y1 < y_min || lo_y1 > y_max) return false;
    if (lo_y2 < y_min || lo_y2 > y_max) return false;

    return true;
}

void NozzleReference::paint(QPainter& painter) const
{
    if (!isValid()) return;
    painter.save();
    painter.setRenderHint(QPainter::Antialiasing, true);
    if (!rect.isEmpty()) {
        painter.setPen(QPen(QColor(255, 0, 0), 1.0));
        painter.drawRect(rect);
    }
    painter.setPen(QPen(QColor(0, 128, 255), 1.0));
    painter.drawLine(blue_a, blue_b);
    painter.setPen(QPen(QColor(255, 255, 0), 1.5));
    painter.drawLine(red_p0, red_p1);
    painter.restore();
}

std::optional<NozzleReference> NozzleReferenceStore::load()
{
    auto path = settingsPath("reference_lines.json");
    QFile f(QString::fromStdString(path.string()));
    if (!f.open(QIODevice::ReadOnly)) return std::nullopt;

    QJsonParseError err;
    QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) return std::nullopt;

    QJsonObject obj = doc.object();
    NozzleReference ref;

    QJsonArray p0 = obj.value("red_p0").toArray();
    if (p0.isEmpty()) p0 = obj.value("nozzle_p0").toArray();
    if (p0.size() == 2) ref.red_p0 = QPoint(p0[0].toInt(), p0[1].toInt());

    QJsonArray p1 = obj.value("red_p1").toArray();
    if (p1.isEmpty()) p1 = obj.value("nozzle_p1").toArray();
    if (p1.size() == 2) ref.red_p1 = QPoint(p1[0].toInt(), p1[1].toInt());

    QJsonArray ba = obj.value("blue_a").toArray();
    if (ba.size() == 2) ref.blue_a = QPointF(ba[0].toDouble(), ba[1].toDouble());

    QJsonArray bb = obj.value("blue_b").toArray();
    if (bb.size() == 2) ref.blue_b = QPointF(bb[0].toDouble(), bb[1].toDouble());

    QJsonArray r = obj.value("rect").toArray();
    if (r.size() == 4) {
        double x0 = r[0].toDouble();
        double y0 = r[1].toDouble();
        double x1 = r[2].toDouble();
        double y1 = r[3].toDouble();
        ref.rect = QRectF(std::min(x0, x1), std::min(y0, y1), std::abs(x1 - x0), std::abs(y1 - y0));
    }

    QJsonObject rmm = obj.value("rect_mm").toObject();
    if (!rmm.isEmpty()) {
        ref.rect_mm.near_mm = rmm.value("near_mm").toDouble(1.0);
        ref.rect_mm.far_mm = rmm.value("far_mm").toDouble(6.51);
        ref.rect_mm.height_mm = rmm.value("height_mm").toDouble(0.775);
    }

    QJsonArray sz = obj.value("image_size").toArray();
    if (sz.size() == 2) {
        ref.image_width = sz[0].toInt();
        ref.image_height = sz[1].toInt();
    }
    ref.created_at = obj.value("created_at").toString();

    if (!ref.isValid()) return std::nullopt;
    return ref;
}

bool NozzleReferenceStore::save(const NozzleReference& ref, QString* error)
{
    QJsonObject obj;

    QJsonArray p0; p0.append(ref.red_p0.x()); p0.append(ref.red_p0.y());
    obj["red_p0"] = p0;
    obj["nozzle_p0"] = p0;

    QJsonArray p1; p1.append(ref.red_p1.x()); p1.append(ref.red_p1.y());
    obj["red_p1"] = p1;
    obj["nozzle_p1"] = p1;

    QJsonArray ba; ba.append(ref.blue_a.x()); ba.append(ref.blue_a.y());
    obj["blue_a"] = ba;

    QJsonArray bb; bb.append(ref.blue_b.x()); bb.append(ref.blue_b.y());
    obj["blue_b"] = bb;

    QJsonArray r;
    r.append(ref.rect.left());
    r.append(ref.rect.top());
    r.append(ref.rect.right());
    r.append(ref.rect.bottom());
    obj["rect"] = r;

    QJsonObject rmm;
    rmm["near_mm"] = ref.rect_mm.near_mm;
    rmm["far_mm"] = ref.rect_mm.far_mm;
    rmm["height_mm"] = ref.rect_mm.height_mm;
    obj["rect_mm"] = rmm;

    QJsonArray sz;
    sz.append(ref.image_width);
    sz.append(ref.image_height);
    obj["image_size"] = sz;

    QString now = ref.created_at.isEmpty()
                      ? QDateTime::currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
                      : ref.created_at;
    obj["created_at"] = now;

    QJsonDocument doc(obj);
    auto path = settingsPath("reference_lines.json");
    return atomicWriteJson(path, doc.toJson(QJsonDocument::Indented), error);
}

NozzleReference NozzleReferenceStore::buildFromTip(const QPoint& p0, const QPoint& p1, double mm_per_px,
                                                 int image_width, int image_height,
                                                 const RectMm& rect_mm)
{
    NozzleReference ref;
    ref.red_p0 = p0;
    ref.red_p1 = p1;
    ref.image_width = image_width;
    ref.image_height = image_height;
    ref.rect_mm = rect_mm;

    double dx = p1.x() - p0.x();
    double dy = p1.y() - p0.y();
    double len = std::hypot(dx, dy);
    if (len < 1e-6) len = 1.0;
    dx /= len;
    dy /= len;

    QPointF mid(0.5 * (p0.x() + p1.x()), 0.5 * (p0.y() + p1.y()));
    ref.blue_a = mid;

    // Normal perpendicular to edge (-dy, dx) pointing toward left (negative X)
    double nx = -dy;
    double ny = dx;
    if (nx > 0) {
        nx = -nx;
        ny = -ny;
    }

    // Clip line to image boundaries
    // Find intersection with x = 0
    double t_x0 = (0.0 - mid.x()) / nx;
    ref.blue_b = QPointF(0.0, mid.y() + t_x0 * ny);

    if (mm_per_px > 0.0) {
        // Build tolerance rectangle
        double near_px = rect_mm.near_mm / mm_per_px;
        double far_px = rect_mm.far_mm / mm_per_px;
        double hh_px = 0.5 * rect_mm.height_mm / mm_per_px;

        QPointF c_near = mid + QPointF(nx, ny) * near_px;
        QPointF c_far = mid + QPointF(nx, ny) * far_px;

        // Corners: c ± d * hh
        QPointF d_vec(dx, dy);
        QPointF pA = c_near - d_vec * hh_px;
        QPointF pB = c_near + d_vec * hh_px;
        QPointF pC = c_far + d_vec * hh_px;
        QPointF pD = c_far - d_vec * hh_px;

        double min_x = std::min({pA.x(), pB.x(), pC.x(), pD.x()});
        double max_x = std::max({pA.x(), pB.x(), pC.x(), pD.x()});
        double min_y = std::min({pA.y(), pB.y(), pC.y(), pD.y()});
        double max_y = std::max({pA.y(), pB.y(), pC.y(), pD.y()});

        ref.rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y);
    }

    return ref;
}

} // namespace hsc
