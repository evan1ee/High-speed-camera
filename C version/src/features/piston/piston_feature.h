#pragma once

#include "src/shell/i_feature_module.h"
#include "measure_piston.h"

#include <QDoubleSpinBox>

namespace hsc {

class PistonFeatureModule : public IFeatureModule {
public:
    PistonFeatureModule();
    ~PistonFeatureModule() override;

    QString id() const override { return "piston"; }
    QString title() const override { return "Piston"; }
    QString icon() const override { return "⚡"; }
    QString tooltip() const override { return "Piston Speed & Hydrodynamics (F2)"; }
    int displayOrder() const override { return 20; }
    FeatureCategory category() const override { return FeatureCategory::WorkflowTab; }

    void initialize(AppServices& services) override;
    QWidget* createWidget(AppServices& services, QWidget* parent) override;

    QString primaryActionLabel() const override { return "CAPTURE PISTON (Space)"; }
    QString activeActionLabel() const override { return "STOP PISTON (Space)"; }
    QString primaryActionColor() const override { return "#2e7d32"; }
    bool usesCamera() const override { return true; }
    void onPrimaryActionTriggered(AppServices& services) override;

    InjectorGeometry currentGeometry() const;

private:
    QDoubleSpinBox* barrelDiaSpin_ = nullptr;
    QDoubleSpinBox* orificeDiaSpin_ = nullptr;
    QDoubleSpinBox* fallbackFpsSpin_ = nullptr;
};

} // namespace hsc
