#pragma once

#include "app_services.h"

#include <memory>
#include <QPainter>
#include <QSize>
#include <QString>
#include <QWidget>

namespace hsc {

enum class FeatureCategory {
    WorkflowTab,
    SetupTool,
    BatchTool,
    SettingsTab
};

class IFeatureModule {
public:
    virtual ~IFeatureModule() = default;

    virtual QString id() const = 0;
    virtual QString title() const = 0;
    virtual QString icon() const { return {}; }
    virtual QString tooltip() const { return {}; }
    virtual int displayOrder() const = 0;
    virtual FeatureCategory category() const { return FeatureCategory::WorkflowTab; }

    virtual void initialize(AppServices& /*services*/) {}
    virtual QWidget* createWidget(AppServices& services, QWidget* parent) = 0;

    virtual QString primaryActionLabel() const { return {}; }
    virtual QString activeActionLabel() const { return {}; }
    virtual QString primaryActionColor() const { return "#0072ce"; }
    virtual bool usesCamera() const { return false; }
    virtual void onPrimaryActionTriggered(AppServices& /*services*/) {}

    virtual void paintPreviewOverlay(QPainter& /*painter*/, const QSize& /*frameSize*/) const {}
};

} // namespace hsc
