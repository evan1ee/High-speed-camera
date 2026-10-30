#include "calibration_store.h"
#include "app_paths.h"

#include <QDateTime>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

namespace hsc {

static EdgeInfo edgeFromJson(const QJsonObject& obj)
{
    EdgeInfo e;
    e.horizontal = obj.value("horizontal").toBool(true);
    e.k = obj.value("k").toDouble();
    e.b = obj.value("b").toDouble();
    QJsonArray r = obj.value("roi").toArray();
    if (r.size() == 4) {
        e.roi = QRect(r[0].toInt(), r[1].toInt(), r[2].toInt() - r[0].toInt(), r[3].toInt() - r[1].toInt());
    }
    return e;
}

static QJsonObject edgeToJson(const EdgeInfo& e)
{
    QJsonObject obj;
    obj["horizontal"] = e.horizontal;
    obj["k"] = e.k;
    obj["b"] = e.b;
    QJsonArray r;
    r.append(e.roi.left());
    r.append(e.roi.top());
    r.append(e.roi.right());
    r.append(e.roi.bottom());
    obj["roi"] = r;
    return obj;
}

std::optional<ScaleCalibration> ScaleCalibrationStore::load()
{
    auto path = settingsPath("calibration.json");
    QFile f(QString::fromStdString(path.string()));
    if (!f.open(QIODevice::ReadOnly)) return std::nullopt;

    QJsonParseError err;
    QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) return std::nullopt;

    QJsonObject obj = doc.object();
    ScaleCalibration cal;
    cal.mm_per_px = obj.value("mm_per_px").toDouble();
    cal.ref_mm = obj.value("ref_mm").toDouble(5.0);
    cal.distance_px = obj.value("distance_px").toDouble();
    cal.edge1 = edgeFromJson(obj.value("edge1").toObject());
    cal.edge2 = edgeFromJson(obj.value("edge2").toObject());
    cal.mode = obj.value("mode").toString("step");

    QJsonArray sz = obj.value("image_size").toArray();
    if (sz.size() == 2) {
        cal.image_width = sz[0].toInt();
        cal.image_height = sz[1].toInt();
    }
    cal.created_at = obj.value("created_at").toString();

    if (!cal.isValid()) return std::nullopt;
    return cal;
}

bool ScaleCalibrationStore::save(const ScaleCalibration& cal, QString* error)
{
    QJsonObject obj;
    obj["mm_per_px"] = cal.mm_per_px;
    obj["ref_mm"] = cal.ref_mm;
    obj["distance_px"] = cal.distance_px;
    obj["edge1"] = edgeToJson(cal.edge1);
    obj["edge2"] = edgeToJson(cal.edge2);
    obj["mode"] = cal.mode;

    QJsonArray sz;
    sz.append(cal.image_width);
    sz.append(cal.image_height);
    obj["image_size"] = sz;

    QString now = cal.created_at.isEmpty()
                      ? QDateTime::currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
                      : cal.created_at;
    obj["created_at"] = now;

    QJsonDocument doc(obj);
    auto path = settingsPath("calibration.json");
    return atomicWriteJson(path, doc.toJson(QJsonDocument::Indented), error);
}

} // namespace hsc
