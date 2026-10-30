#include "reference_feature.h"
#include "reference_dialog.h"
#include "src/shell/feature_registry.h"
#include "src/foundation/calibration_store.h"
#include "src/foundation/reference_store.h"

#include <QGroupBox>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

namespace hsc {

ReferenceFeatureModule::ReferenceFeatureModule() = default;
ReferenceFeatureModule::~ReferenceFeatureModule() = default;

QWidget* ReferenceFeatureModule::createWidget(AppServices& services, QWidget* parent)
{
    auto* group = new QGroupBox(QObject::tr("Step 2: Nozzle Reference & Tolerance Box"), parent);
    auto* l = new QVBoxLayout(group);

    auto* desc = new QLabel(
        QObject::tr("Defines the nozzle tip, perpendicular spray centerline, and tolerance target box."), group);
    desc->setWordWrap(true);
    desc->setStyleSheet("color: #606266; font-size: 11px;");
    l->addWidget(desc);

    auto* btnRef = new QPushButton(QObject::tr("Set Nozzle Reference..."), group);
    l->addWidget(btnRef);

    QObject::connect(btnRef, &QPushButton::clicked, [&services, parent]() {
        QImage dummy(320, 240, QImage::Format_Grayscale8);
        dummy.fill(20);
        auto cal = ScaleCalibrationStore::load();
        double scale = (cal && cal->isValid()) ? cal->mm_per_px : 0.052;
        ReferenceDialog dlg(dummy, scale, parent);
        if (dlg.exec() == QDialog::Accepted) {
            services.log("Nozzle reference saved successfully.");
        }
    });

    return group;
}

void ReferenceFeatureModule::paintPreviewOverlay(QPainter& painter, const QSize& frameSize) const
{
    auto ref = NozzleReferenceStore::load();
    if (ref && ref->isValid() && ref->image_width == frameSize.width() && ref->image_height == frameSize.height()) {
        ref->paint(painter);
    }
}

} // namespace hsc

HSC_REGISTER_FEATURE(::hsc::ReferenceFeatureModule)
