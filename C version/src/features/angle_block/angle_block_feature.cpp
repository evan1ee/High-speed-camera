#include "angle_block_feature.h"
#include "measure_block.h"
#include "src/shell/feature_registry.h"
#include "src/foundation/app_paths.h"

#include <QGroupBox>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

namespace hsc {

AngleBlockFeatureModule::AngleBlockFeatureModule() = default;
AngleBlockFeatureModule::~AngleBlockFeatureModule() = default;

QWidget* AngleBlockFeatureModule::createWidget(AppServices& services, QWidget* parent)
{
    auto* group = new QGroupBox(QObject::tr("Step 3: Precision Angle Block Metrology"), parent);
    auto* l = new QVBoxLayout(group);

    auto* desc = new QLabel(
        QObject::tr("Measures the acute angle of a machined wedge block to verify line-fitting accuracy."), group);
    desc->setWordWrap(true);
    desc->setStyleSheet("color: #606266; font-size: 11px;");
    l->addWidget(desc);

    auto* btnBlock = new QPushButton(QObject::tr("Measure Angle Block..."), group);
    l->addWidget(btnBlock);

    QObject::connect(btnBlock, &QPushButton::clicked, [&services, parent]() {
        QMessageBox::information(parent, QObject::tr("Measure Angle Block"),
                                QObject::tr("Please place the angle block under the camera."));
    });

    return group;
}

} // namespace hsc

HSC_REGISTER_FEATURE(::hsc::AngleBlockFeatureModule)
