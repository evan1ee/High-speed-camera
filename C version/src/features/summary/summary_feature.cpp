#include "summary_feature.h"
#include "src/shell/feature_registry.h"
#include "src/foundation/app_paths.h"

#include <QFileDialog>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

namespace hsc {

SummaryFeatureModule::SummaryFeatureModule() = default;
SummaryFeatureModule::~SummaryFeatureModule() = default;

QWidget* SummaryFeatureModule::createWidget(AppServices& services, QWidget* parent)
{
    auto* w = new QWidget(parent);
    auto* l = new QVBoxLayout(w);
    l->setContentsMargins(6, 6, 6, 6);

    auto* title = new QLabel(QObject::tr("📊 Cross-Run Batch Summary"), w);
    title->setStyleSheet("font-size: 15px; font-weight: bold; color: #202530;");
    l->addWidget(title);

    auto* topBtns = new QHBoxLayout();
    auto* btnAll = new QPushButton(QObject::tr("Select All"), w);
    auto* btnClear = new QPushButton(QObject::tr("Clear"), w);
    topBtns->addWidget(btnAll);
    topBtns->addWidget(btnClear);
    l->addLayout(topBtns);

    batchTable_ = new QTableWidget(0, 3, w);
    batchTable_->setHorizontalHeaderLabels({QObject::tr("Run"), QObject::tr("Stroke (mm)"), QObject::tr("Peak Speed")});
    batchTable_->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    l->addWidget(batchTable_, 1);

    auto* actBtns = new QHBoxLayout();
    auto* btnCalc = new QPushButton(QObject::tr("Calculate Summary"), w);
    auto* btnExport = new QPushButton(QObject::tr("Export CSV"), w);
    actBtns->addWidget(btnCalc);
    actBtns->addWidget(btnExport);
    l->addLayout(actBtns);

    statsLabel_ = new QLabel(QObject::tr("Select runs with *_speed.csv to calculate stats."), w);
    statsLabel_->setWordWrap(true);
    statsLabel_->setStyleSheet("color: #606266; font-size: 11px;");
    l->addWidget(statsLabel_);

    QObject::connect(btnAll, &QPushButton::clicked, [this]() {
        for (int i = 0; i < batchTable_->rowCount(); ++i) {
            batchTable_->item(i, 0)->setCheckState(Qt::Checked);
        }
    });

    QObject::connect(btnClear, &QPushButton::clicked, [this]() {
        for (int i = 0; i < batchTable_->rowCount(); ++i) {
            batchTable_->item(i, 0)->setCheckState(Qt::Unchecked);
        }
    });

    QObject::connect(btnCalc, &QPushButton::clicked, [this, &services]() {
        std::vector<std::filesystem::path> folders;
        auto base = dataRoot() / "captures";
        std::error_code ec;
        for (const auto& entry : std::filesystem::directory_iterator(base, ec)) {
            if (entry.is_directory()) folders.push_back(entry.path());
        }

        auto summary = aggregateRuns(folders);
        batchTable_->setRowCount(0);

        for (const auto& r : summary.runs) {
            int row = batchTable_->rowCount();
            batchTable_->insertRow(row);
            auto* item0 = new QTableWidgetItem(r.run_name);
            item0->setCheckState(Qt::Checked);
            batchTable_->setItem(row, 0, item0);
            batchTable_->setItem(row, 1, new QTableWidgetItem(QString::number(r.stroke_mm, 'f', 2)));
            batchTable_->setItem(row, 2, new QTableWidgetItem(QString::number(r.peak_speed_mm_s, 'f', 1)));
        }

        statsLabel_->setText(
            QString("<b>Analyzed %1 runs:</b><br>"
                    "Stroke: Mean %2 mm | Std %3 mm | CV: %4%<br>"
                    "Speed: Mean %5 mm/s | Std %6 mm/s | CV: %7%")
                .arg(summary.runs.size())
                .arg(QString::number(summary.stroke_mm.mean, 'f', 2))
                .arg(QString::number(summary.stroke_mm.std, 'f', 2))
                .arg(QString::number(summary.stroke_mm.cv_percent, 'f', 1))
                .arg(QString::number(summary.peak_speed_mm_s.mean, 'f', 1))
                .arg(QString::number(summary.peak_speed_mm_s.std, 'f', 1))
                .arg(QString::number(summary.peak_speed_mm_s.cv_percent, 'f', 1)));
        services.log(QString("Calculated summary across %1 runs.").arg(summary.runs.size()));
    });

    QObject::connect(btnExport, &QPushButton::clicked, [this, &services, parent]() {
        QString path = QFileDialog::getSaveFileName(parent, QObject::tr("Export Summary CSV"), "batch_summary.csv", QObject::tr("CSV Files (*.csv)"));
        if (path.isEmpty()) return;

        std::vector<std::filesystem::path> folders;
        auto base = dataRoot() / "captures";
        std::error_code ec;
        for (const auto& entry : std::filesystem::directory_iterator(base, ec)) {
            if (entry.is_directory()) folders.push_back(entry.path());
        }

        auto summary = aggregateRuns(folders);
        if (summary.exportCsv(path.toStdString())) {
            QMessageBox::information(parent, QObject::tr("CSV Exported"),
                                    QObject::tr("Summary saved to %1").arg(path));
            services.log(QString("Summary exported to %1").arg(path));
        }
    });

    return w;
}

} // namespace hsc

HSC_REGISTER_FEATURE(::hsc::SummaryFeatureModule)
