#pragma once

#include "src/shell/i_feature_module.h"

namespace hsc {

class ReferenceFeatureModule : public IFeatureModule {
public:
    ReferenceFeatureModule();
    ~ReferenceFeatureModule() override;

    QString id() const override { return "reference"; }
    QString title() const override { return "Nozzle Reference"; }
    int displayOrder() const override { return 52; }
    FeatureCategory category() const override { return FeatureCategory::SetupTool; }

    QWidget* createWidget(AppServices& services, QWidget* parent) override;
    void paintPreviewOverlay(QPainter& painter, const QSize& frameSize) const override;
};

} // namespace hsc
