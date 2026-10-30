#include "spray_feature.h"
#include "src/shell/feature_registry.h"
#include "src/shell/ui_icons.h"
#include "src/foundation/app_paths.h"
#include "src/foundation/make_video.h"
#include "src/foundation/reference_store.h"

#include <QFileDialog>
#include <QFormLayout>
#include <QGroupBox>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

namespace hsc {

SprayFeatureModule::SprayFeatureModule() = default;
SprayFeatureModule::~SprayFeatureModule() = default;

SprayMeasureOptions SprayFeatureModule::currentOptions() const
{
    SprayMeasureOptions opts;
    if (smartSaveCheck_) opts.use_erf = edgeV2Check_->isChecked();
    if (autoPickCheck_) opts.auto_pick_frames = autoPickCheck_->isChecked();
    if (measureFromSpin_) opts.measure_from = measureFromSpin_->value();
    if (measureToSpin_) opts.measure_to = measureToSpin_->value();
    if (drawRefOnOutputCheck_) opts.draw_ref_lines = drawRefOnOutputCheck_->isChecked();
    return opts;
}

void SprayFeatureModule::initialize(AppServices& services)
{
    services.registerFolderAnalyzer("spray_angle", "Spray Angle Measurement",
        [](const std::filesystem::path& folder, std::function<void(int, int, const QString&)> progress) {
            SprayMeasureOptions opts;
            opts.draw_ref_lines = true;
            auto ref = NozzleReferenceStore::load();

            auto prog_bridge = [&](int cur, int tot) {
                if (progress) progress(cur, tot, "Measuring frames...");
            };

            auto res = measureFolder(folder, opts, ref, prog_bridge);

            InspectionReport r;
            r.featureId = "spray_angle";
            r.runTitle = res.run_name;
            r.outputFolder = QString::fromStdString(folder.string());
            r.csvPath = QString::fromStdString(res.csv_path.string());
            r.valid = res.valid;

            BadgeStatus st = (res.in_rect_verdict == "OK") ? BadgeStatus::PassGreen : BadgeStatus::FailRed;
            r.kpis.push_back({"Spray Angle", QString("%1°").arg(QString::number(res.mean_angle, 'f', 2)),
                              QString("Pooled: %1°").arg(QString::number(res.pooled_angle, 'f', 2)), st});
            r.kpis.push_back({"Confidence", res.overall_confidence_str,
                              QString("Score: %1").arg(static_cast<int>(res.overall_confidence)), BadgeStatus::Neutral});
            r.kpis.push_back({"Target Rect", res.in_rect_verdict.isEmpty() ? "N/A" : res.in_rect_verdict,
                              "Containment Verdict", st});

            r.framePaths = res.annotated_frame_paths;
            return r;
        });
}

QWidget* SprayFeatureModule::createWidget(AppServices& services, QWidget* parent)
{
    auto* w = new QWidget(parent);
    w->setStyleSheet("background: transparent; border: none;");
    auto* l = new QVBoxLayout(w);
    l->setContentsMargins(4, 2, 4, 4);
    l->setSpacing(6);

    // Title row with colorful concentric target icon
    auto* titleRow = new QHBoxLayout();
    titleRow->setContentsMargins(2, 2, 2, 0);
    titleRow->setSpacing(6);
    auto* iconLabel = new QLabel(w);
    iconLabel->setPixmap(getSprayHeaderIcon().scaled(18, 18, Qt::KeepAspectRatio, Qt::SmoothTransformation));
    iconLabel->setStyleSheet("border: none; background: transparent;");
    titleRow->addWidget(iconLabel);

    auto* title = new QLabel(QObject::tr("Spray Angle Measurement"), w);
    title->setStyleSheet("font-size: 13px; font-weight: bold; color: #0f172a; border: none; background: transparent;");
    titleRow->addWidget(title);
    titleRow->addStretch();
    l->addLayout(titleRow);

    const QString groupStyle =
        "QGroupBox { font-size: 11px; font-weight: 600; color: #1e293b; border: 1px solid #cbd5e1; border-radius: 8px; margin-top: 8px; padding-top: 12px; padding-left: 6px; padding-right: 6px; padding-bottom: 6px; background: transparent; }"
        "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 8px; padding: 0 4px; background: transparent; }";

    auto* optGroup = new QGroupBox(QObject::tr("Measurement Options"), w);
    optGroup->setStyleSheet(groupStyle);
    auto* optL = new QVBoxLayout(optGroup);
    optL->setContentsMargins(4, 4, 4, 4);
    optL->setSpacing(5);

    const QString checkStyle =
        "QCheckBox { font-size: 11px; color: #1e293b; spacing: 6px; border: none; background: transparent; }";

    smartSaveCheck_ = new QCheckBox(QObject::tr("Smart Save (RAM detection before disk write)"), optGroup);
    smartSaveCheck_->setChecked(true);
    smartSaveCheck_->setStyleSheet(checkStyle);

    autoPickCheck_ = new QCheckBox(QObject::tr("Auto pick 10 stable jet frames"), optGroup);
    autoPickCheck_->setChecked(true);
    autoPickCheck_->setStyleSheet(checkStyle);

    edgeV2Check_ = new QCheckBox(QObject::tr("Edge detection V2 (erf blurred-step model)"), optGroup);
    edgeV2Check_->setStyleSheet(checkStyle);

    showRefOnPreviewCheck_ = new QCheckBox(QObject::tr("Show reference overlay on preview"), optGroup);
    showRefOnPreviewCheck_->setChecked(true);
    showRefOnPreviewCheck_->setStyleSheet(checkStyle);

    drawRefOnOutputCheck_ = new QCheckBox(QObject::tr("Draw reference lines on measured frames"), optGroup);
    drawRefOnOutputCheck_->setChecked(true);
    drawRefOnOutputCheck_->setStyleSheet(checkStyle);

    optL->addWidget(smartSaveCheck_);
    optL->addWidget(autoPickCheck_);
    optL->addWidget(edgeV2Check_);
    optL->addWidget(showRefOnPreviewCheck_);
    optL->addWidget(drawRefOnOutputCheck_);
    l->addWidget(optGroup);

    auto* frameGroup = new QGroupBox(QObject::tr("Manual Frame Range (if Auto pick is OFF)"), w);
    frameGroup->setStyleSheet(groupStyle);
    auto* fl = new QFormLayout(frameGroup);
    fl->setContentsMargins(6, 6, 6, 6);
    fl->setSpacing(6);

    const QString spinStyle =
        "QSpinBox { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 6px; font-size: 11px; color: #1e293b; min-height: 22px; }"
        "QSpinBox:focus { border: 1px solid #0072ce; }"
        "QSpinBox::up-button, QSpinBox::down-button { width: 0px; height: 0px; border: none; }";

    measureFromSpin_ = new QSpinBox(frameGroup);
    measureFromSpin_->setButtonSymbols(QAbstractSpinBox::NoButtons);
    measureFromSpin_->setRange(1, 500);
    measureFromSpin_->setValue(15);
    measureFromSpin_->setStyleSheet(spinStyle);

    measureToSpin_ = new QSpinBox(frameGroup);
    measureToSpin_->setButtonSymbols(QAbstractSpinBox::NoButtons);
    measureToSpin_->setRange(1, 500);
    measureToSpin_->setValue(22);
    measureToSpin_->setStyleSheet(spinStyle);

    auto* fromLbl = new QLabel(QObject::tr("From frame (Nth):"), frameGroup);
    fromLbl->setStyleSheet("border: none; background: transparent; font-size: 11px; color: #1e293b;");
    auto* toLbl = new QLabel(QObject::tr("To frame (Nth):"), frameGroup);
    toLbl->setStyleSheet("border: none; background: transparent; font-size: 11px; color: #1e293b;");

    fl->addRow(fromLbl, measureFromSpin_);
    fl->addRow(toLbl, measureToSpin_);
    l->addWidget(frameGroup);

    auto* offlineGroup = new QGroupBox(QObject::tr("Offline Re-Processing on Existing Folders"), w);
    offlineGroup->setStyleSheet(groupStyle);
    auto* offL = new QVBoxLayout(offlineGroup);
    offL->setContentsMargins(6, 6, 6, 6);
    offL->setSpacing(6);

    const QString btnStyle =
        "QPushButton { background: #eef2f7; border: 1px solid #c8d3df; border-radius: 6px; padding: 3px 10px; font-size: 11px; font-weight: 500; color: #1e293b; min-height: 24px; text-align: center; }"
        "QPushButton:hover { background: #e2e8f0; }"
        "QPushButton:pressed { background: #cbd5e1; }";

    auto* btnMeasure = new QPushButton(QObject::tr("Measure Angle on Folder..."), offlineGroup);
    btnMeasure->setStyleSheet(btnStyle);
    auto* btnVideo = new QPushButton(QObject::tr("Generate Slow-Motion Video..."), offlineGroup);
    btnVideo->setStyleSheet(btnStyle);

    offL->addWidget(btnMeasure);
    offL->addWidget(btnVideo);
    l->addWidget(offlineGroup);

    QObject::connect(btnMeasure, &QPushButton::clicked, [this, &services, parent]() {
        QString dir = QFileDialog::getExistingDirectory(parent, QObject::tr("Select Injection Folder to Measure"));
        if (dir.isEmpty()) return;
        auto rep = services.runAnalyzer("spray_angle", dir.toStdString(), [](int cur, int tot, const QString& msg) {});
        if (rep && rep->valid) {
            services.publishReport(*rep);
            services.log(QObject::tr("Spray measurement complete for %1").arg(dir));
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

void SprayFeatureModule::onPrimaryActionTriggered(AppServices& services)
{
    // Feature registers workflow chain execution via AppServices pipeline
    services.log("Spray Angle capture requested.");
}

void SprayFeatureModule::paintPreviewOverlay(QPainter& painter, const QSize& frameSize) const
{
    if (!showRefOnPreviewCheck_ || !showRefOnPreviewCheck_->isChecked()) return;
    auto ref = NozzleReferenceStore::load();
    if (ref && ref->isValid() && ref->image_width == frameSize.width() && ref->image_height == frameSize.height()) {
        ref->paint(painter);
    }
}

} // namespace hsc

HSC_REGISTER_FEATURE(::hsc::SprayFeatureModule)
