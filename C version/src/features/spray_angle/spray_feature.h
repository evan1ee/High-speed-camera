#pragma once

#include "src/shell/i_feature_module.h"
#include "measure_angle.h"
#include "smart_save.h"

#include <QCheckBox>
#include <QSpinBox>

namespace hsc {

class SprayFeatureModule : public IFeatureModule {
public:
    SprayFeatureModule();
    ~SprayFeatureModule() override;

    QString id() const override { return "spray_angle"; }
    QString title() const override { return "Spray"; }
    QString icon() const override { return "🎯"; }
    QString tooltip() const override { return "Spray Angle Measurement (F1)"; }
    int displayOrder() const override { return 10; }
    FeatureCategory category() const override { return FeatureCategory::WorkflowTab; }

    void initialize(AppServices& services) override;
    QWidget* createWidget(AppServices& services, QWidget* parent) override;

    QString primaryActionLabel() const override { return "CAPTURE SPRAY (Space)"; }
    QString activeActionLabel() const override { return "STOP SPRAY (Space)"; }
    QString primaryActionColor() const override { return "#0072ce"; }
    bool usesCamera() const override { return true; }
    void onPrimaryActionTriggered(AppServices& services) override;

    void paintPreviewOverlay(QPainter& painter, const QSize& frameSize) const override;

    SprayMeasureOptions currentOptions() const;

private:
    QCheckBox* smartSaveCheck_ = nullptr;
    QCheckBox* autoPickCheck_ = nullptr;
    QCheckBox* edgeV2Check_ = nullptr;
    QCheckBox* showRefOnPreviewCheck_ = nullptr;
    QCheckBox* drawRefOnOutputCheck_ = nullptr;
    QSpinBox* measureFromSpin_ = nullptr;
    QSpinBox* measureToSpin_ = nullptr;
};

} // namespace hsc
