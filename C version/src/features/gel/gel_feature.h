#pragma once

#include "src/shell/i_feature_module.h"

namespace hsc {

class GelFeatureModule : public IFeatureModule {
public:
    GelFeatureModule();
    ~GelFeatureModule() override;

    QString id() const override { return "gel"; }
    QString title() const override { return "Gel"; }
    QString icon() const override { return "🧊"; }
    QString tooltip() const override { return "Capture Gel Injection (F3)"; }
    int displayOrder() const override { return 30; }
    FeatureCategory category() const override { return FeatureCategory::WorkflowTab; }

    void initialize(AppServices& services) override;
    QWidget* createWidget(AppServices& services, QWidget* parent) override;

    QString primaryActionLabel() const override { return "CAPTURE GEL (Space)"; }
    QString activeActionLabel() const override { return "STOP GEL (Space)"; }
    QString primaryActionColor() const override { return "#00838f"; }
    bool usesCamera() const override { return true; }
    void onPrimaryActionTriggered(AppServices& services) override;
};

} // namespace hsc
