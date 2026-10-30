#pragma once

#include "src/foundation/reference_store.h"

#include <QDialog>
#include <QImage>
#include <QPoint>

class QGraphicsScene;
class QGraphicsView;
class QGraphicsPixmapItem;
class QLabel;

namespace hsc {

class ReferenceDialog : public QDialog {
    Q_OBJECT

public:
    explicit ReferenceDialog(const QImage& frame, double mm_per_px = 0.052, QWidget* parent = nullptr);
    ~ReferenceDialog() override;

    std::optional<NozzleReference> resultReference() const { return result_; }

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;

private slots:
    void onAutoDetect();
    void onSave();

private:
    void setupUi();
    void updateOverlay();

    QImage frame_;
    double mm_per_px_ = 0.052;
    QPoint p0_;
    QPoint p1_;
    bool dragging_ = false;

    QGraphicsView* view_ = nullptr;
    QGraphicsScene* scene_ = nullptr;
    QGraphicsPixmapItem* pixmapItem_ = nullptr;
    QLabel* statusLabel_ = nullptr;

    std::optional<NozzleReference> result_;
};

} // namespace hsc
