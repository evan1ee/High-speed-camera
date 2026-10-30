#pragma once

#include "inspection_report.h"
#include "src/foundation/reference_store.h"

#include <optional>
#include <vector>
#include <QImage>
#include <QWidget>

class QGraphicsScene;
class QGraphicsView;
class QGraphicsPixmapItem;
class QLabel;
class QSlider;
class QPushButton;
class QTabWidget;
class QHBoxLayout;
class QVBoxLayout;

namespace hsc {

class ViewportWidget : public QWidget {
    Q_OBJECT

public:
    explicit ViewportWidget(QWidget* parent = nullptr);
    ~ViewportWidget() override;

    void updateLiveFrame(const QImage& frame);
    void displayReport(const InspectionReport& report);
    void setReference(const std::optional<NozzleReference>& ref);
    void setShowReference(bool show);

protected:
    void resizeEvent(QResizeEvent* event) override;

public slots:
    void zoomIn();
    void zoomOut();
    void zoomFit();
    void zoom100();

private slots:
    void onScrubberChanged(int index);
    void onPrevFrame();
    void onNextFrame();

private:
    void setupUi();
    void updateKpiBanner(const std::vector<KpiCard>& kpis);
    void updateScrubberUi();
    void drawOverlay(QImage& img);

    // Main tabs: Live Camera View vs Results Inspector
    QTabWidget* mainTab_ = nullptr;

    // Live view widgets
    QGraphicsView* liveView_ = nullptr;
    QGraphicsScene* liveScene_ = nullptr;
    QGraphicsPixmapItem* livePixmap_ = nullptr;
    QLabel* liveInfoLabel_ = nullptr;

    // Results Inspector widgets
    QWidget* inspectorTab_ = nullptr;
    QHBoxLayout* kpiLayout_ = nullptr;
    QGraphicsView* inspectorView_ = nullptr;
    QGraphicsScene* inspectorScene_ = nullptr;
    QGraphicsPixmapItem* inspectorPixmap_ = nullptr;
    QSlider* scrubberSlider_ = nullptr;
    QLabel* scrubberLabel_ = nullptr;
    QPushButton* prevBtn_ = nullptr;
    QPushButton* nextBtn_ = nullptr;
    QTabWidget* plotsTab_ = nullptr;

    QImage currentLiveFrame_;
    std::vector<QString> currentReportFrames_;
    int currentFrameIdx_ = 0;

    std::optional<NozzleReference> reference_;
    bool showReference_ = true;
    double liveZoom_ = 1.0;
    double inspectorZoom_ = 1.0;
};

} // namespace hsc
