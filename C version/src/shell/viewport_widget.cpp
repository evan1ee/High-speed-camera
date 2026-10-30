#include "viewport_widget.h"
#include "src/shell/ui_icons.h"
#include <QGraphicsPixmapItem>
#include <QGraphicsScene>
#include <QGraphicsView>
#include <QHBoxLayout>
#include <QLabel>
#include <QPainter>
#include <QPixmap>
#include <QPushButton>
#include <QSlider>
#include <QTabWidget>
#include <QVBoxLayout>

namespace hsc {

ViewportWidget::ViewportWidget(QWidget* parent) : QWidget(parent)
{
    setupUi();
}

ViewportWidget::~ViewportWidget() = default;

void ViewportWidget::setupUi()
{
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);

    mainTab_ = new QTabWidget(this);
    mainTab_->setStyleSheet(
        "QTabWidget::pane { border: 1px solid #d8e0ea; border-radius: 8px; background: #ffffff; }"
        "QTabBar::tab { background: #dce5ee; color: #334155; font-size: 11px; font-weight: 600; padding: 5px 16px; border: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }"
        "QTabBar::tab:selected { background: #ffffff; color: #0f172a; border-bottom: 2px solid #0072ce; font-weight: bold; }"
        "QTabBar::tab:hover:!selected { background: #e2e8f0; color: #0f172a; }");

    // 1. Live Camera View
    auto* liveContainer = new QWidget(mainTab_);
    auto* liveLayout = new QVBoxLayout(liveContainer);
    liveLayout->setContentsMargins(6, 6, 6, 6);
    liveLayout->setSpacing(6);

    // Zoom Toolbar
    auto* zoomBar = new QHBoxLayout();
    zoomBar->setContentsMargins(2, 2, 2, 2);
    liveInfoLabel_ = new QLabel(tr("Frame: Ready | Zoom: 100%"), liveContainer);
    liveInfoLabel_->setStyleSheet("color: #475467; font-size: 11px; font-weight: 500;");
    zoomBar->addWidget(liveInfoLabel_);
    zoomBar->addStretch();

    const QString zBtnStyle =
        "QPushButton { background: #eef2f7; border: 1px solid #c8d3df; border-radius: 6px; padding: 2px 10px; font-size: 11px; font-weight: 500; color: #1e293b; min-height: 22px; }"
        "QPushButton:hover { background: #e2e8f0; }"
        "QPushButton:pressed { background: #cbd5e1; }";

    auto* zInBtn = new QPushButton(tr("Zoom +"), liveContainer);
    zInBtn->setStyleSheet(zBtnStyle);
    auto* zOutBtn = new QPushButton(tr("Zoom -"), liveContainer);
    zOutBtn->setStyleSheet(zBtnStyle);
    auto* z100Btn = new QPushButton(tr("100%"), liveContainer);
    z100Btn->setStyleSheet(zBtnStyle);
    auto* zFitBtn = new QPushButton(tr("Fit"), liveContainer);
    zFitBtn->setStyleSheet(zBtnStyle);

    zoomBar->addWidget(zInBtn);
    zoomBar->addWidget(zOutBtn);
    zoomBar->addWidget(z100Btn);
    zoomBar->addWidget(zFitBtn);
    liveLayout->addLayout(zoomBar);

    connect(zInBtn, &QPushButton::clicked, this, &ViewportWidget::zoomIn);
    connect(zOutBtn, &QPushButton::clicked, this, &ViewportWidget::zoomOut);
    connect(z100Btn, &QPushButton::clicked, this, &ViewportWidget::zoom100);
    connect(zFitBtn, &QPushButton::clicked, this, &ViewportWidget::zoomFit);

    liveScene_ = new QGraphicsScene(this);
    // Create idle rounded dark canvas placeholder with 4:3 aspect ratio
    const int initW = 480;
    const int initH = 360;
    QPixmap idlePix(initW, initH);
    idlePix.fill(Qt::transparent);
    {
        QPainter p(&idlePix);
        p.setRenderHint(QPainter::Antialiasing, true);
        p.setPen(Qt::NoPen);
        p.setBrush(QColor(27, 34, 44)); // Dark slate #1b222c
        p.drawRoundedRect(QRectF(0, 0, initW, initH), 10.0, 10.0);
    }
    livePixmap_ = liveScene_->addPixmap(idlePix);
    liveScene_->setSceneRect(idlePix.rect());

    liveView_ = new QGraphicsView(liveScene_, liveContainer);
    liveView_->setRenderHint(QPainter::Antialiasing);
    liveView_->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    liveView_->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    liveView_->setStyleSheet("background: #111418; border: none; border-radius: 12px;");
    liveLayout->addWidget(liveView_, 1);

    mainTab_->addTab(liveContainer, getTabCameraIcon(), tr("Live Camera Stream"));

    // 2. Results Inspector
    inspectorTab_ = new QWidget(mainTab_);
    auto* inspLayout = new QVBoxLayout(inspectorTab_);
    inspLayout->setContentsMargins(4, 4, 4, 4);

    // Dynamic KPI Cards Bar
    auto* kpiContainer = new QWidget(inspectorTab_);
    kpiLayout_ = new QHBoxLayout(kpiContainer);
    kpiLayout_->setContentsMargins(0, 4, 0, 8);
    inspLayout->addWidget(kpiContainer);

    // Sub-tab: Annotated Frames Scrubber vs Plot Attachments
    auto* contentTab = new QTabWidget(inspectorTab_);
    auto* scrubberContainer = new QWidget(contentTab);
    auto* scLayout = new QVBoxLayout(scrubberContainer);
    scLayout->setContentsMargins(0, 0, 0, 0);

    inspectorScene_ = new QGraphicsScene(this);
    inspectorPixmap_ = inspectorScene_->addPixmap(QPixmap());
    inspectorView_ = new QGraphicsView(inspectorScene_, scrubberContainer);
    inspectorView_->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    inspectorView_->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    inspectorView_->setStyleSheet("background: #111418; border: none; border-radius: 12px;");
    scLayout->addWidget(inspectorView_, 1);

    // Scrubber controls
    auto* scrubBar = new QHBoxLayout();
    prevBtn_ = new QPushButton(tr("◀ Prev"), scrubberContainer);
    nextBtn_ = new QPushButton(tr("Next ▶"), scrubberContainer);
    scrubberSlider_ = new QSlider(Qt::Horizontal, scrubberContainer);
    scrubberLabel_ = new QLabel(tr("Frame: - / -"), scrubberContainer);
    scrubberLabel_->setFixedWidth(100);
    scrubberLabel_->setAlignment(Qt::AlignCenter);

    scrubBar->addWidget(prevBtn_);
    scrubBar->addWidget(scrubberSlider_, 1);
    scrubBar->addWidget(nextBtn_);
    scrubBar->addWidget(scrubberLabel_);
    scLayout->addLayout(scrubBar);

    connect(scrubberSlider_, &QSlider::valueChanged, this, &ViewportWidget::onScrubberChanged);
    connect(prevBtn_, &QPushButton::clicked, this, &ViewportWidget::onPrevFrame);
    connect(nextBtn_, &QPushButton::clicked, this, &ViewportWidget::onNextFrame);

    contentTab->addTab(scrubberContainer, tr("🖼 Annotated Frames"));

    plotsTab_ = new QTabWidget(contentTab);
    contentTab->addTab(plotsTab_, tr("📈 Curves & Plots"));

    inspLayout->addWidget(contentTab, 1);

    mainTab_->addTab(inspectorTab_, getTabInspectorIcon(), tr("Results Inspector"));
    root->addWidget(mainTab_);
}

void ViewportWidget::setReference(const std::optional<NozzleReference>& ref)
{
    reference_ = ref;
}

void ViewportWidget::setShowReference(bool show)
{
    showReference_ = show;
}

void ViewportWidget::drawOverlay(QImage& img)
{
    if (!showReference_ || !reference_ || !reference_->isValid()) return;

    QPainter painter(&img);
    painter.setRenderHint(QPainter::Antialiasing, true);

    // Target rectangle (red)
    if (!reference_->rect.isEmpty()) {
        painter.setPen(QPen(QColor(255, 0, 0), 1.0));
        painter.drawRect(reference_->rect);
    }

    // Centerline spray axis (blue)
    painter.setPen(QPen(QColor(0, 128, 255), 1.0));
    painter.drawLine(reference_->blue_a, reference_->blue_b);

    // Nozzle tip line (yellow)
    painter.setPen(QPen(QColor(255, 255, 0), 1.5));
    painter.drawLine(reference_->red_p0, reference_->red_p1);
}

void ViewportWidget::updateLiveFrame(const QImage& frame)
{
    currentLiveFrame_ = frame.copy();
    drawOverlay(currentLiveFrame_);

    livePixmap_->setPixmap(QPixmap::fromImage(currentLiveFrame_));
    liveScene_->setSceneRect(currentLiveFrame_.rect());

    liveInfoLabel_->setText(QString("Frame: %1x%2 | Zoom: %3%")
                                .arg(frame.width())
                                .arg(frame.height())
                                .arg(static_cast<int>(liveZoom_ * 100)));
}

void ViewportWidget::zoomIn()
{
    liveZoom_ = std::min(8.0, liveZoom_ * 1.25);
    liveView_->resetTransform();
    liveView_->scale(liveZoom_, liveZoom_);
}

void ViewportWidget::zoomOut()
{
    liveZoom_ = std::max(0.2, liveZoom_ / 1.25);
    liveView_->resetTransform();
    liveView_->scale(liveZoom_, liveZoom_);
}

void ViewportWidget::zoomFit()
{
    liveView_->fitInView(liveScene_->sceneRect(), Qt::KeepAspectRatio);
}

void ViewportWidget::zoom100()
{
    liveZoom_ = 1.0;
    liveView_->resetTransform();
}

void ViewportWidget::updateKpiBanner(const std::vector<KpiCard>& kpis)
{
    // Clear previous cards
    QLayoutItem* item;
    while ((item = kpiLayout_->takeAt(0)) != nullptr) {
        delete item->widget();
        delete item;
    }

    for (const auto& card : kpis) {
        auto* box = new QWidget(inspectorTab_);
        box->setStyleSheet(
            "background: #f4f6f8; border: 1px solid #dcdfe6; border-radius: 6px; padding: 6px;");
        auto* bl = new QVBoxLayout(box);
        bl->setContentsMargins(6, 4, 6, 4);
        bl->setSpacing(2);

        auto* lbl = new QLabel(card.label, box);
        lbl->setStyleSheet("color: #606266; font-size: 11px; font-weight: bold;");
        bl->addWidget(lbl);

        auto* val = new QLabel(card.value, box);
        QString color = "#202530";
        if (card.status == BadgeStatus::PassGreen) color = "#1a9d38";
        else if (card.status == BadgeStatus::FailRed) color = "#d32f2f";
        else if (card.status == BadgeStatus::WarnAmber) color = "#e65100";

        val->setStyleSheet(QString("color: %1; font-size: 16px; font-weight: bold;").arg(color));
        bl->addWidget(val);

        if (!card.subtext.isEmpty()) {
            auto* sub = new QLabel(card.subtext, box);
            sub->setStyleSheet("color: #909399; font-size: 10px;");
            bl->addWidget(sub);
        }

        kpiLayout_->addWidget(box);
    }
    kpiLayout_->addStretch();
}

void ViewportWidget::displayReport(const InspectionReport& report)
{
    if (!report.valid) return;

    updateKpiBanner(report.kpis);

    // Frame sequence
    currentReportFrames_ = report.framePaths;
    currentFrameIdx_ = 0;

    scrubberSlider_->blockSignals(true);
    if (!currentReportFrames_.empty()) {
        scrubberSlider_->setRange(0, static_cast<int>(currentReportFrames_.size()) - 1);
        scrubberSlider_->setValue(0);
        prevBtn_->setEnabled(true);
        nextBtn_->setEnabled(true);
    } else {
        scrubberSlider_->setRange(0, 0);
        prevBtn_->setEnabled(false);
        nextBtn_->setEnabled(false);
    }
    scrubberSlider_->blockSignals(false);

    updateScrubberUi();

    // Curve plot sub-tabs
    plotsTab_->clear();
    for (const auto& plot : report.plots) {
        auto* pLabel = new QLabel(plotsTab_);
        pLabel->setAlignment(Qt::AlignCenter);
        QPixmap pm(plot.imagePath);
        if (!pm.isNull()) {
            pLabel->setPixmap(pm.scaled(900, 600, Qt::KeepAspectRatio, Qt::SmoothTransformation));
        } else {
            pLabel->setText(tr("Plot file not found: %1").arg(plot.imagePath));
        }
        plotsTab_->addTab(pLabel, plot.title);
    }

    // Switch to Results Inspector tab automatically!
    mainTab_->setCurrentIndex(1);
}

void ViewportWidget::updateScrubberUi()
{
    if (currentReportFrames_.empty() || currentFrameIdx_ < 0 ||
        currentFrameIdx_ >= static_cast<int>(currentReportFrames_.size())) {
        scrubberLabel_->setText(tr("Frame: - / -"));
        inspectorPixmap_->setPixmap(QPixmap());
        return;
    }

    QString path = currentReportFrames_[currentFrameIdx_];
    QPixmap pm(path);
    if (!pm.isNull()) {
        inspectorPixmap_->setPixmap(pm);
        inspectorScene_->setSceneRect(pm.rect());
        inspectorView_->fitInView(inspectorScene_->sceneRect(), Qt::KeepAspectRatio);
    }

    scrubberLabel_->setText(QString("Frame: %1 / %2")
                                .arg(currentFrameIdx_ + 1)
                                .arg(currentReportFrames_.size()));
}

void ViewportWidget::onScrubberChanged(int index)
{
    currentFrameIdx_ = index;
    updateScrubberUi();
}

void ViewportWidget::onPrevFrame()
{
    if (currentFrameIdx_ > 0) {
        --currentFrameIdx_;
        scrubberSlider_->setValue(currentFrameIdx_);
    }
}

void ViewportWidget::onNextFrame()
{
    if (currentFrameIdx_ + 1 < static_cast<int>(currentReportFrames_.size())) {
        ++currentFrameIdx_;
        scrubberSlider_->setValue(currentFrameIdx_);
    }
}

void ViewportWidget::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);
    if (!currentLiveFrame_.isNull()) {
        liveView_->fitInView(liveScene_->sceneRect(), Qt::KeepAspectRatio);
    } else if (liveView_ && liveScene_ && livePixmap_) {
        QSize viewSz = liveView_->size();
        if (viewSz.width() > 40 && viewSz.height() > 40) {
            int availW = viewSz.width() - 32;
            int availH = viewSz.height() - 32;
            const double aspect = 4.0 / 3.0; // 320x240 camera aspect ratio
            int w = availW;
            int h = availH;
            if (availW / static_cast<double>(availH) > aspect) {
                h = availH;
                w = static_cast<int>(h * aspect);
            } else {
                w = availW;
                h = static_cast<int>(w / aspect);
            }
            if (w < 40) w = 40;
            if (h < 30) h = 30;

            QPixmap idlePix(w, h);
            idlePix.fill(Qt::transparent);
            {
                QPainter p(&idlePix);
                p.setRenderHint(QPainter::Antialiasing, true);
                p.setPen(Qt::NoPen);
                p.setBrush(QColor(27, 34, 44)); // Dark slate #1b222c
                p.drawRoundedRect(QRectF(0, 0, w, h), 10.0, 10.0);
            }
            livePixmap_->setPixmap(idlePix);
            liveScene_->setSceneRect(idlePix.rect());
            liveView_->fitInView(liveScene_->sceneRect(), Qt::KeepAspectRatio);
        }
    }
}

} // namespace hsc
