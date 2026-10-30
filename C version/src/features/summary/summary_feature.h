#pragma once

#include "src/shell/i_feature_module.h"
#include "src/foundation/summary_calc.h"

#include <QLabel>
#include <QTableWidget>

namespace hsc {

class SummaryFeatureModule : public IFeatureModule {
public:
    SummaryFeatureModule();
    ~SummaryFeatureModule() override;

    QString id() const override { return "summary"; }
    QString title() const override { return "Batch"; }
    QString icon() const override { return "📊"; }
    QString tooltip() const override { return "Cross-Run Batch Summary (F6)"; }
    int displayOrder() const override { return 60; }
    FeatureCategory category() const override { return FeatureCategory::WorkflowTab; }

    QWidget* createWidget(AppServices& services, QWidget* parent) override;

private:
    QTableWidget* batchTable_ = nullptr;
    QLabel* statsLabel_ = nullptr;
};

} // namespace hsc
