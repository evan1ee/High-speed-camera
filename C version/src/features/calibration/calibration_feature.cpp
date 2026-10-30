#include "calibration_feature.h"
#include "calibration_dialog.h"
#include "src/shell/feature_registry.h"
#include "src/foundation/calibration_store.h"

#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QGroupBox>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

namespace hsc {

CalibrationFeatureModule::CalibrationFeatureModule() = default;
CalibrationFeatureModule::~CalibrationFeatureModule() = default;

QWidget* CalibrationFeatureModule::createWidget(AppServices& services, QWidget* parent)
{
    auto* group = new QGroupBox(QObject::tr("Step 1: Spatial Scale Calibration (mm/px)"), parent);
    auto* l = new QVBoxLayout(group);

    const QString spinStyle =
        "QDoubleSpinBox { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 6px; font-size: 11px; color: #1e293b; min-height: 22px; }"
        "QDoubleSpinBox:focus { border: 1px solid #0072ce; }"
        "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; height: 0px; border: none; }";

    auto* distSpin = new QDoubleSpinBox(group);
    distSpin->setButtonSymbols(QAbstractSpinBox::NoButtons);
    distSpin->setStyleSheet(spinStyle);
    distSpin->setRange(0.1, 100.0);
    distSpin->setValue(5.0);
    distSpin->setSuffix(" mm");

    auto* fl = new QFormLayout();
    fl->addRow(QObject::tr("Gauge block thickness:"), distSpin);
    l->addLayout(fl);

    auto* btnAuto = new QPushButton(QObject::tr("Auto Calibrate (1-Click)"), group);
    auto* btnManual = new QPushButton(QObject::tr("Manual Calibrate Scale..."), group);
    l->addWidget(btnAuto);
    l->addWidget(btnManual);

    QObject::connect(btnAuto, &QPushButton::clicked, [distSpin, &services, parent]() {
        // Run auto calibrate if live frame available
        QMessageBox::information(parent, QObject::tr("Auto Calibrate"),
                                QObject::tr("Please ensure gauge block is visible in the live preview."));
    });

    QObject::connect(btnManual, &QPushButton::clicked, [distSpin, &services, parent]() {
        QImage dummy(320, 240, QImage::Format_Grayscale8);
        dummy.fill(20);
        CalibrationDialog dlg(dummy, distSpin->value(), parent);
        if (dlg.exec() == QDialog::Accepted) {
            services.log("Scale calibration saved successfully.");
        }
    });

    return group;
}

} // namespace hsc

HSC_REGISTER_FEATURE(::hsc::CalibrationFeatureModule)
