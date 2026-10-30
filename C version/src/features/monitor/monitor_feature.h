#pragma once

#include "src/shell/i_feature_module.h"
#include "event_writer.h"
#include "monitor_engine.h"

#include <memory>
#include <QLabel>
#include <QTableWidget>

namespace hsc {

class MonitorFeatureModule : public IFeatureModule {
public:
    MonitorFeatureModule();
    ~MonitorFeatureModule() override;

    QString id() const override { return "monitor"; }
    QString title() const override { return "Monitor"; }
    QString icon() const override { return "🔄"; }
    QString tooltip() const override { return "Continuous Online Monitor (F4)"; }
    int displayOrder() const override { return 40; }
    FeatureCategory category() const override { return FeatureCategory::WorkflowTab; }

    void initialize(AppServices& services) override;
    QWidget* createWidget(AppServices& services, QWidget* parent) override;

    QString primaryActionLabel() const override { return "START MONITORING (Space)"; }
    QString activeActionLabel() const override { return "STOP MONITORING (Space)"; }
    QString primaryActionColor() const override { return "#6a1b9a"; }
    bool usesCamera() const override { return true; }
    void onPrimaryActionTriggered(AppServices& services) override;

    bool isMonitoring() const { return isMonitoring_; }
    void feedFrame(const QImage& frame, AppServices& services);

private:
    bool isMonitoring_ = false;
    std::unique_ptr<MonitorEngine> engine_;
    std::unique_ptr<EventWriter> writer_;

    QLabel* monFedLabel_ = nullptr;
    QLabel* monEvtLabel_ = nullptr;
    QLabel* monDripLabel_ = nullptr;
    QTableWidget* monTable_ = nullptr;
};

} // namespace hsc
