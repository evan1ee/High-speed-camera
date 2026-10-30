#pragma once

#include "src/shell/i_feature_module.h"
#include "calibrate_scale.h"

namespace hsc {

class CalibrationFeatureModule : public IFeatureModule {
public:
    CalibrationFeatureModule();
    ~CalibrationFeatureModule() override;

    QString id() const override { return "calibration"; }
    QString title() const override { return "Scale Calibration"; }
    int displayOrder() const override { return 51; }
    FeatureCategory category() const override { return FeatureCategory::SetupTool; }

    QWidget* createWidget(AppServices& services, QWidget* parent) override;
};

} // namespace hsc
