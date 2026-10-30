#include "piston_feature.h"
#include "src/shell/feature_registry.h"
#include "src/foundation/app_paths.h"
#include "src/foundation/make_video.h"

#include <QFileDialog>
#include <QFormLayout>
#include <QGroupBox>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

namespace hsc {

PistonFeatureModule::PistonFeatureModule() = default;
PistonFeatureModule::~PistonFeatureModule() = default;

InjectorGeometry PistonFeatureModule::currentGeometry() const
{
    InjectorGeometry geom;
    if (barrelDiaSpin_) geom.barrel_diameter_mm = barrelDiaSpin_->value();
    if (orificeDiaSpin_) geom.orifice_diameter_mm = orificeDiaSpin_->value();
    if (fallbackFpsSpin_) geom.fallback_fps = fallbackFpsSpin_->value();
    return geom;
}

void PistonFeatureModule::initialize(AppServices& services)
{
    services.registerFolderAnalyzer("piston", "Piston Speed & Hydrodynamics",
        [this](const std::filesystem::path& folder, std::function<void(int, int, const QString&)> progress) {
            auto cal = ScaleCalibrationStore::load();
            auto prog_bridge = [&](int cur, int tot) {
                if (progress) progress(cur, tot, "Tracking piston edge...");
            };

            auto res = measurePistonFolder(folder, currentGeometry(), cal, prog_bridge);

            InspectionReport r;
            r.featureId = "piston";
            r.runTitle = res.run_name;
            r.outputFolder = QString::fromStdString(folder.string());
            r.csvPath = QString::fromStdString(res.csv_path.string());
            r.valid = res.valid;

            r.kpis.push_back({"Stroke Travel", QString("%1 mm").arg(QString::number(res.stroke_mm, 'f', 2)),
                              QString("Duration: %1 ms").arg(QString::number(res.duration_ms, 'f', 1)), BadgeStatus::Neutral});
            r.kpis.push_back({"Peak Piston Speed", QString("%1 mm/s").arg(QString::number(res.peak_speed_mm_s, 'f', 1)),
                              "Max Velocity", BadgeStatus::PassGreen});
            r.kpis.push_back({"Exit Jet Speed", QString("%1 m/s").arg(QString::number(res.peak_jet_speed_m_s, 'f', 1)),
                              QString("Pressure: %1 MPa").arg(QString::number(res.peak_jet_pressure_MPa, 'f', 2)), BadgeStatus::PassGreen});

            r.plots.push_back({"Displacement, Velocity & Pressure Curves", QString::fromStdString(res.plot_path.string())});
            return r;
        });
}

QWidget* PistonFeatureModule::createWidget(AppServices& services, QWidget* parent)
{
    auto* w = new QWidget(parent);
    auto* l = new QVBoxLayout(w);
    l->setContentsMargins(6, 6, 6, 6);

    auto* title = new QLabel(QObject::tr("⚡ Piston Speed & Hydrodynamics"), w);
    title->setStyleSheet("font-size: 15px; font-weight: bold; color: #202530;");
    l->addWidget(title);

    auto* geomGroup = new QGroupBox(QObject::tr("Injector Geometry & Mechanics"), w);
    auto* gl = new QFormLayout(geomGroup);
    const QString spinStyle =
        "QDoubleSpinBox { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 6px; font-size: 11px; color: #1e293b; min-height: 22px; }"
        "QDoubleSpinBox:focus { border: 1px solid #0072ce; }"
        "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; height: 0px; border: none; }";

    barrelDiaSpin_ = new QDoubleSpinBox(geomGroup);
    barrelDiaSpin_->setButtonSymbols(QAbstractSpinBox::NoButtons);
    barrelDiaSpin_->setStyleSheet(spinStyle);
    barrelDiaSpin_->setRange(1.0, 50.0);
    barrelDiaSpin_->setValue(6.12);
    barrelDiaSpin_->setSuffix(" mm");

    orificeDiaSpin_ = new QDoubleSpinBox(geomGroup);
    orificeDiaSpin_->setButtonSymbols(QAbstractSpinBox::NoButtons);
    orificeDiaSpin_->setStyleSheet(spinStyle);
    orificeDiaSpin_->setRange(0.01, 10.0);
    orificeDiaSpin_->setValue(0.155);
    orificeDiaSpin_->setDecimals(3);
    orificeDiaSpin_->setSuffix(" mm");

    fallbackFpsSpin_ = new QDoubleSpinBox(geomGroup);
    fallbackFpsSpin_->setButtonSymbols(QAbstractSpinBox::NoButtons);
    fallbackFpsSpin_->setStyleSheet(spinStyle);
    fallbackFpsSpin_->setRange(10.0, 50000.0);
    fallbackFpsSpin_->setValue(1048.0);
    fallbackFpsSpin_->setSuffix(" fps");

    gl->addRow(QObject::tr("Barrel diameter:"), barrelDiaSpin_);
    gl->addRow(QObject::tr("Orifice diameter:"), orificeDiaSpin_);
    gl->addRow(QObject::tr("Fallback FPS:"), fallbackFpsSpin_);
    l->addWidget(geomGroup);

    auto* offlineGroup = new QGroupBox(QObject::tr("Offline Re-Processing"), w);
    auto* offL = new QVBoxLayout(offlineGroup);
    auto* btnMeasure = new QPushButton(QObject::tr("Measure Piston Folder..."), offlineGroup);
    auto* btnVideo = new QPushButton(QObject::tr("Generate Piston Slow-Mo Video..."), offlineGroup);
    offL->addWidget(btnMeasure);
    offL->addWidget(btnVideo);
    l->addWidget(offlineGroup);

    QObject::connect(btnMeasure, &QPushButton::clicked, [this, &services, parent]() {
        QString dir = QFileDialog::getExistingDirectory(parent, QObject::tr("Select Piston Folder to Measure"));
        if (dir.isEmpty()) return;
        auto rep = services.runAnalyzer("piston", dir.toStdString(), [](int cur, int tot, const QString& msg) {});
        if (rep && rep->valid) {
            services.publishReport(*rep);
            services.log(QObject::tr("Piston analysis complete for %1").arg(dir));
        }
    });

    QObject::connect(btnVideo, &QPushButton::clicked, [&services, parent]() {
        QString dir = QFileDialog::getExistingDirectory(parent, QObject::tr("Select Folder to Make Video"));
        if (dir.isEmpty()) return;
        auto out_vid = std::filesystem::path(dir.toStdString()) / "slowmo.avi";
        if (makeVideo(dir.toStdString(), out_vid, 15)) {
            QMessageBox::information(parent, QObject::tr("Video Created"),
                                    QObject::tr("Saved: %1").arg(QString::fromStdString(out_vid.string())));
        }
    });

    l->addStretch();
    return w;
}

void PistonFeatureModule::onPrimaryActionTriggered(AppServices& services)
{
    services.log("Piston capture requested.");
}

} // namespace hsc

HSC_REGISTER_FEATURE(::hsc::PistonFeatureModule)
