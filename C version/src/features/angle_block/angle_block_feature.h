#pragma once

#include "src/shell/i_feature_module.h"

namespace hsc {

class AngleBlockFeatureModule : public IFeatureModule {
public:
    AngleBlockFeatureModule();
    ~AngleBlockFeatureModule() override;

    QString id() const override { return "angle_block"; }
    QString title() const override { return "Angle Block"; }
    int displayOrder() const override { return 53; }
    FeatureCategory category() const override { return FeatureCategory::SetupTool; }

    QWidget* createWidget(AppServices& services, QWidget* parent) override;
};

} // namespace hsc
