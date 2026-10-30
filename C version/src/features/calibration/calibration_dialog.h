#pragma once

#include "src/foundation/calibration_store.h"

#include <QDialog>
#include <QImage>
#include <QRect>

class QGraphicsScene;
class QGraphicsView;
class QGraphicsPixmapItem;
class QDoubleSpinBox;
class QLabel;

namespace hsc {

class CalibrationDialog : public QDialog {
    Q_OBJECT

public:
    explicit CalibrationDialog(const QImage& frame, double default_mm = 5.0, QWidget* parent = nullptr);
    ~CalibrationDialog() override;

    std::optional<ScaleCalibration> resultCalibration() const { return result_; }

private slots:
    void onCalculate();
    void onSave();

private:
    void setupUi();
    void updateOverlay();

    QImage frame_;
    double ref_mm_ = 5.0;
    QRect roi1_;
    QRect roi2_;

    QGraphicsView* view_ = nullptr;
    QGraphicsScene* scene_ = nullptr;
    QGraphicsPixmapItem* pixmapItem_ = nullptr;

    QDoubleSpinBox* refMmSpin_ = nullptr;
    QLabel* resultLabel_ = nullptr;

    std::optional<ScaleCalibration> result_;
};

} // namespace hsc
