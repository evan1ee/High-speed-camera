#include "monitor_feature.h"
#include "src/shell/feature_registry.h"
#include "src/foundation/app_paths.h"

#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QVBoxLayout>

namespace hsc {

MonitorFeatureModule::MonitorFeatureModule() = default;
MonitorFeatureModule::~MonitorFeatureModule() = default;

void MonitorFeatureModule::initialize(AppServices& services)
{
    writer_ = std::make_unique<EventWriter>(dataRoot());
}

QWidget* MonitorFeatureModule::createWidget(AppServices& services, QWidget* parent)
{
    auto* w = new QWidget(parent);
    auto* l = new QVBoxLayout(w);
    l->setContentsMargins(6, 6, 6, 6);

    auto* title = new QLabel(QObject::tr("🔄 Continuous Online Monitoring"), w);
    title->setStyleSheet("font-size: 15px; font-weight: bold; color: #202530;");
    l->addWidget(title);

    auto* card = new QWidget(w);
    card->setStyleSheet("background: #f8f9fa; border: 1px solid #dcdfe6; border-radius: 6px; padding: 6px;");
    auto* cl = new QHBoxLayout(card);
    monFedLabel_ = new QLabel("Fed: 0", card);
    monEvtLabel_ = new QLabel("Events: 0", card);
    monDripLabel_ = new QLabel("Drips: 0", card);
    cl->addWidget(monFedLabel_);
    cl->addWidget(monEvtLabel_);
    cl->addWidget(monDripLabel_);
    l->addWidget(card);

    monTable_ = new QTableWidget(0, 4, w);
    monTable_->setHorizontalHeaderLabels({"Event #", "Peak Pixels", "Angle", "Verdict"});
    monTable_->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    l->addWidget(monTable_, 1);

    return w;
}

void MonitorFeatureModule::onPrimaryActionTriggered(AppServices& services)
{
    if (isMonitoring_) {
        isMonitoring_ = false;
        services.log("Continuous Monitoring stopped.");
    } else {
        isMonitoring_ = true;
        // Standard resolution 320x240
        engine_ = std::make_unique<MonitorEngine>(320, 240);
        services.log("Continuous Monitoring started. Listening for injections...");
    }
}

void MonitorFeatureModule::feedFrame(const QImage& frame, AppServices& services)
{
    if (!isMonitoring_ || !engine_) return;

    QImage gray = frame.convertToFormat(QImage::Format_Grayscale8);
    auto evt = engine_->feedFrame(gray.constBits());

    if (monFedLabel_) monFedLabel_->setText(QString("Fed: %1").arg(engine_->totalFramesFed()));
    if (monEvtLabel_) monEvtLabel_->setText(QString("Events: %1").arg(engine_->eventsDetected()));
    if (monDripLabel_) monDripLabel_->setText(QString("Drips: %1").arg(engine_->dripsDiscarded()));

    if (evt && !evt->discarded && writer_) {
        services.log(QString("Injection event #%1 detected (%2 frames). Saving...").arg(evt->event_id).arg(evt->frames.size()));

        writer_->saveAsync(evt, [&services, this](const std::filesystem::path& folder, const MonitorEvent& e) {
            auto rep = services.runAnalyzer("spray_angle", folder);
            if (rep && monTable_) {
                QMetaObject::invokeMethod(monTable_, [this, e, rep]() {
                    int row = monTable_->rowCount();
                    monTable_->insertRow(row);
                    monTable_->setItem(row, 0, new QTableWidgetItem(QString("#%1").arg(e.event_id)));
                    monTable_->setItem(row, 1, new QTableWidgetItem(QString::number(e.peak_diff)));
                    QString angle_str = rep->kpis.empty() ? "-" : rep->kpis[0].value;
                    QString verdict = (rep->kpis.size() >= 3) ? rep->kpis[2].value : "-";
                    monTable_->setItem(row, 2, new QTableWidgetItem(angle_str));
                    monTable_->setItem(row, 3, new QTableWidgetItem(verdict));
                });
            }
        });
    }
}

} // namespace hsc

HSC_REGISTER_FEATURE(::hsc::MonitorFeatureModule)
