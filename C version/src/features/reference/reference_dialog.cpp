#include "reference_dialog.h"
#include "src/foundation/calibration_store.h"

#include <QDialogButtonBox>
#include <QGraphicsPixmapItem>
#include <QGraphicsScene>
#include <QGraphicsSceneMouseEvent>
#include <QGraphicsView>
#include <QHBoxLayout>
#include <QLabel>
#include <QMessageBox>
#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QPushButton>
#include <QVBoxLayout>

namespace hsc {

ReferenceDialog::ReferenceDialog(const QImage& frame, double mm_per_px, QWidget* parent)
    : QDialog(parent), frame_(frame), mm_per_px_(mm_per_px)
{
    setWindowTitle(tr("Nozzle Reference & Tolerance Alignment"));
    resize(860, 640);
    setupUi();
}

ReferenceDialog::~ReferenceDialog() = default;

void ReferenceDialog::setupUi()
{
    auto* root = new QVBoxLayout(this);

    auto* topBar = new QHBoxLayout();
    auto* autoBtn = new QPushButton(tr("Auto-Detect Nozzle Tip"), this);
    topBar->addWidget(autoBtn);
    statusLabel_ = new QLabel(tr("Drag the yellow line across nozzle tip face. Blue axis and red box update live."), this);
    statusLabel_->setStyleSheet("color: #606266; font-size: 12px;");
    topBar->addWidget(statusLabel_);
    topBar->addStretch();
    root->addLayout(topBar);

    scene_ = new QGraphicsScene(this);
    pixmapItem_ = scene_->addPixmap(QPixmap::fromImage(frame_));
    view_ = new QGraphicsView(scene_, this);
    view_->setStyleSheet("background: #202020;");
    view_->viewport()->installEventFilter(this);
    root->addWidget(view_, 1);

    auto* btnBox = new QDialogButtonBox(QDialogButtonBox::Save | QDialogButtonBox::Cancel, this);
    root->addWidget(btnBox);

    connect(autoBtn, &QPushButton::clicked, this, &ReferenceDialog::onAutoDetect);
    connect(btnBox, &QDialogButtonBox::accepted, this, &ReferenceDialog::onSave);
    connect(btnBox, &QDialogButtonBox::rejected, this, &QDialog::reject);

    // Initial default tip position on right side
    int w = frame_.width();
    int h = frame_.height();
    p0_ = QPoint(w - 20, h / 3);
    p1_ = QPoint(w - 20, (2 * h) / 3);

    // Load existing reference if available
    auto existing = NozzleReferenceStore::load();
    if (existing && existing->isValid() && existing->image_width == w && existing->image_height == h) {
        p0_ = existing->red_p0;
        p1_ = existing->red_p1;
    }

    onAutoDetect();
}

bool ReferenceDialog::eventFilter(QObject* obj, QEvent* event)
{
    if (obj == view_->viewport()) {
        if (event->type() == QEvent::MouseButtonPress) {
            auto* me = static_cast<QMouseEvent*>(event);
            if (me->button() == Qt::LeftButton) {
                QPointF scenePt = view_->mapToScene(me->pos());
                p0_ = scenePt.toPoint();
                p1_ = p0_;
                dragging_ = true;
                return true;
            }
        } else if (event->type() == QEvent::MouseMove) {
            if (dragging_) {
                auto* me = static_cast<QMouseEvent*>(event);
                QPointF scenePt = view_->mapToScene(me->pos());
                p1_ = scenePt.toPoint();
                result_ = NozzleReferenceStore::buildFromTip(p0_, p1_, mm_per_px_, frame_.width(), frame_.height());
                updateOverlay();
                return true;
            }
        } else if (event->type() == QEvent::MouseButtonRelease) {
            if (dragging_) {
                dragging_ = false;
                result_ = NozzleReferenceStore::buildFromTip(p0_, p1_, mm_per_px_, frame_.width(), frame_.height());
                updateOverlay();
                return true;
            }
        }
    }
    return QDialog::eventFilter(obj, event);
}

void ReferenceDialog::onAutoDetect()
{
    int w = frame_.width();
    int h = frame_.height();

    // Default right side tip
    p0_ = QPoint(w - 25, h / 3);
    p1_ = QPoint(w - 25, (2 * h) / 3);

    result_ = NozzleReferenceStore::buildFromTip(p0_, p1_, mm_per_px_, w, h);
    updateOverlay();
}

void ReferenceDialog::updateOverlay()
{
    QImage display = frame_.copy();
    QPainter p(&display);
    p.setRenderHint(QPainter::Antialiasing, true);

    if (result_ && result_->isValid()) {
        // Red target box
        if (!result_->rect.isEmpty()) {
            p.setPen(QPen(QColor(255, 0, 0), 1.2));
            p.drawRect(result_->rect);
        }

        // Blue centerline axis
        p.setPen(QPen(QColor(0, 128, 255), 1.5));
        p.drawLine(result_->blue_a, result_->blue_b);
    }

    // Yellow nozzle tip line
    p.setPen(QPen(QColor(255, 255, 0), 2.0));
    p.drawLine(p0_, p1_);

    p.end();
    pixmapItem_->setPixmap(QPixmap::fromImage(display));
}

void ReferenceDialog::onSave()
{
    if (!result_ || !result_->isValid()) {
        QMessageBox::warning(this, tr("Reference Error"), tr("Please mark a valid nozzle tip line first."));
        return;
    }

    QString err;
    if (!NozzleReferenceStore::save(*result_, &err)) {
        QMessageBox::critical(this, tr("Save Failed"), tr("Failed to save reference lines: %1").arg(err));
        return;
    }

    accept();
}

} // namespace hsc
