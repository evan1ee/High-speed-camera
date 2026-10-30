#include "calibration_dialog.h"
#include "calibrate_scale.h"

#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QGraphicsPixmapItem>
#include <QGraphicsScene>
#include <QGraphicsView>
#include <QHBoxLayout>
#include <QLabel>
#include <QMessageBox>
#include <QPainter>
#include <QPen>
#include <QPushButton>
#include <QVBoxLayout>

namespace hsc {

CalibrationDialog::CalibrationDialog(const QImage& frame, double default_mm, QWidget* parent)
    : QDialog(parent), frame_(frame), ref_mm_(default_mm)
{
    setWindowTitle(tr("Spatial Scale Calibration (mm/px)"));
    resize(860, 640);
    setupUi();
}

CalibrationDialog::~CalibrationDialog() = default;

void CalibrationDialog::setupUi()
{
    auto* root = new QVBoxLayout(this);

    const QString spinStyle =
        "QDoubleSpinBox { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 6px; font-size: 11px; color: #1e293b; min-height: 22px; }"
        "QDoubleSpinBox:focus { border: 1px solid #0072ce; }"
        "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; height: 0px; border: none; }";

    auto* topBar = new QHBoxLayout();
    topBar->addWidget(new QLabel(tr("Known gauge distance:"), this));
    refMmSpin_ = new QDoubleSpinBox(this);
    refMmSpin_->setButtonSymbols(QAbstractSpinBox::NoButtons);
    refMmSpin_->setStyleSheet(spinStyle);
    refMmSpin_->setRange(0.1, 100.0);
    refMmSpin_->setDecimals(3);
    refMmSpin_->setValue(ref_mm_);
    refMmSpin_->setSuffix(tr(" mm"));
    topBar->addWidget(refMmSpin_);

    auto* calcBtn = new QPushButton(tr("Detect Edges & Calculate"), this);
    topBar->addWidget(calcBtn);
    topBar->addStretch();
    root->addLayout(topBar);

    scene_ = new QGraphicsScene(this);
    pixmapItem_ = scene_->addPixmap(QPixmap::fromImage(frame_));
    view_ = new QGraphicsView(scene_, this);
    view_->setStyleSheet("background: #202020;");
    root->addWidget(view_, 1);

    resultLabel_ = new QLabel(tr("Default ROIs loaded. Click 'Detect Edges & Calculate' to test."), this);
    resultLabel_->setStyleSheet("font-weight: bold; font-size: 13px; color: #0072ce;");
    root->addWidget(resultLabel_);

    auto* btnBox = new QDialogButtonBox(QDialogButtonBox::Save | QDialogButtonBox::Cancel, this);
    root->addWidget(btnBox);

    connect(calcBtn, &QPushButton::clicked, this, &CalibrationDialog::onCalculate);
    connect(btnBox, &QDialogButtonBox::accepted, this, &CalibrationDialog::onSave);
    connect(btnBox, &QDialogButtonBox::rejected, this, &QDialog::reject);

    // Initial default ROIs (dual horizontal bars in left third)
    int w = frame_.width();
    int h = frame_.height();
    int rw = std::min(w / 3, 100);
    roi1_ = QRect(20, h / 4 - 15, rw, 30);
    roi2_ = QRect(20, (3 * h) / 4 - 15, rw, 30);

    onCalculate();
}

void CalibrationDialog::onCalculate()
{
    if (frame_.isNull()) return;

    ref_mm_ = refMmSpin_->value();
    QImage gray = frame_.convertToFormat(QImage::Format_Grayscale8);
    int w = gray.width();
    int h = gray.height();

    // Auto calibrate
    auto auto_res = autoCalibrate(gray.constBits(), w, h, ref_mm_);
    if (auto_res.valid) {
        ScaleCalibration cal;
        cal.mm_per_px = auto_res.mm_per_px;
        cal.ref_mm = ref_mm_;
        cal.distance_px = auto_res.distance_px;
        cal.edge1 = auto_res.edge1;
        cal.edge2 = auto_res.edge2;
        cal.mode = "step";
        cal.image_width = w;
        cal.image_height = h;

        result_ = cal;
        roi1_ = cal.edge1.roi;
        roi2_ = cal.edge2.roi;

        resultLabel_->setText(QString("Success: %1 mm/px (Distance: %2 px)")
                                  .arg(QString::number(cal.mm_per_px, 'f', 6))
                                  .arg(QString::number(cal.distance_px, 'f', 2)));
        resultLabel_->setStyleSheet("color: #1a9d38; font-weight: bold; font-size: 13px;");
    } else {
        // Fallback dual ROIs
        auto cal = calibrateFromRois(gray.constBits(), w, h, roi1_, roi2_, ref_mm_, "step");
        if (cal) {
            result_ = *cal;
            resultLabel_->setText(QString("Calibrated: %1 mm/px (Distance: %2 px)")
                                      .arg(QString::number(cal->mm_per_px, 'f', 6))
                                      .arg(QString::number(cal->distance_px, 'f', 2)));
            resultLabel_->setStyleSheet("color: #1a9d38; font-weight: bold; font-size: 13px;");
        } else {
            resultLabel_->setText(tr("Could not detect gauge edges in ROIs. Try repositioning gauge block."));
            resultLabel_->setStyleSheet("color: #d32f2f; font-weight: bold; font-size: 13px;");
        }
    }

    updateOverlay();
}

void CalibrationDialog::updateOverlay()
{
    QImage display = frame_.copy();
    QPainter p(&display);
    p.setRenderHint(QPainter::Antialiasing, true);

    // Draw ROIs (cyan dashed)
    p.setPen(QPen(QColor(0, 255, 255), 1, Qt::DashLine));
    p.drawRect(roi1_);
    p.drawRect(roi2_);

    // Draw fitted edge lines (green solid)
    if (result_) {
        p.setPen(QPen(QColor(0, 255, 0), 1.5));
        double x0 = 0, x1 = frame_.width();
        p.drawLine(QPointF(x0, result_->edge1.k * x0 + result_->edge1.b),
                   QPointF(x1, result_->edge1.k * x1 + result_->edge1.b));
        p.drawLine(QPointF(x0, result_->edge2.k * x0 + result_->edge2.b),
                   QPointF(x1, result_->edge2.k * x1 + result_->edge2.b));
    }

    p.end();
    pixmapItem_->setPixmap(QPixmap::fromImage(display));
}

void CalibrationDialog::onSave()
{
    if (!result_ || !result_->isValid()) {
        QMessageBox::warning(this, tr("Calibration Error"), tr("Please calculate a valid calibration first."));
        return;
    }

    QString err;
    if (!ScaleCalibrationStore::save(*result_, &err)) {
        QMessageBox::critical(this, tr("Save Failed"), tr("Failed to save calibration: %1").arg(err));
        return;
    }

    accept();
}

} // namespace hsc
