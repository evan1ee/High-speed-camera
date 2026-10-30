#include "main_window.h"
#include "src/foundation/app_paths.h"
#include "src/foundation/bmp_io.h"
#include "src/foundation/make_video.h"
#include "src/shell/ui_icons.h"

#include <QButtonGroup>
#include <QCloseEvent>
#include <QDateTime>
#include <QDesktopServices>
#include <QFileDialog>
#include <QGraphicsView>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QMessageBox>
#include <QPainter>
#include <QPainterPath>
#include <QSplitter>
#include <QThread>
#include <QUrl>
#include <QVBoxLayout>
#include <fstream>

namespace hsc {

namespace {

struct AspectPreset {
    const char* name;
    int width;
    int height;
};

const AspectPreset kAspectPresets[] = {
    {"320x240 (~1048 fps)", 320, 240},
    {"320x120 (~1798 fps)", 320, 120},
    {"332x332 (1:1)", 332, 332},
    {"664x332 (2:1)", 664, 332},
    {"432x324 (4:3)", 432, 324},
    {"576x324 (16:9)", 576, 324},
};

QString ensureCheckIcon(const std::filesystem::path& root)
{
    auto icon_path = root / "check_white.png";
    if (!std::filesystem::exists(icon_path)) {
        QPixmap pix(16, 16);
        pix.fill(Qt::transparent);
        {
            QPainter p(&pix);
            p.setRenderHint(QPainter::Antialiasing, true);
            p.setPen(QPen(Qt::white, 2.2, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
            QPainterPath check;
            check.moveTo(3.5, 8.5);
            check.lineTo(6.5, 12.0);
            check.lineTo(12.5, 4.5);
            p.drawPath(check);
        }
        pix.save(QString::fromStdString(icon_path.string()), "PNG");
    }
    QString str = QString::fromStdString(icon_path.generic_string());
    str.replace('\\', '/');
    return str;
}

QString ensureDownArrowIcon(const std::filesystem::path& root)
{
    auto icon_path = root / "down_arrow.png";
    if (!std::filesystem::exists(icon_path)) {
        QPixmap pix(16, 16);
        pix.fill(Qt::transparent);
        {
            QPainter p(&pix);
            p.setRenderHint(QPainter::Antialiasing, true);
            p.setPen(QPen(QColor(71, 84, 103), 1.8, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
            QPainterPath path;
            path.moveTo(4.0, 6.0);
            path.lineTo(8.0, 10.0);
            path.lineTo(12.0, 6.0);
            p.drawPath(path);
        }
        pix.save(QString::fromStdString(icon_path.string()), "PNG");
    }
    QString str = QString::fromStdString(icon_path.generic_string());
    str.replace('\\', '/');
    return str;
}

} // namespace

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent)
{
    setWindowTitle(tr("High-Speed Camera Analysis & Metrology System"));
    setWindowIcon(getAppWindowIcon());
    resize(1024, 658);
    setStyleSheet("QMainWindow { background: #f0f4f9; }");

    // Initialize stores
    calibration_ = ScaleCalibrationStore::load();
    reference_ = NozzleReferenceStore::load();

    // Setup camera controller and worker thread
    workerThread_ = new QThread(this);
    controller_ = new CameraController();
    controller_->moveToThread(workerThread_);

    services_ = std::make_unique<AppServices>(controller_, this);

    connect(workerThread_, &QThread::finished, controller_, &QObject::deleteLater);
    connect(controller_, &CameraController::previewFrame, this, &MainWindow::onPreviewFrame);
    connect(controller_, &CameraController::previewStarted, this, &MainWindow::onPreviewStarted);
    connect(controller_, &CameraController::previewStopped, this, &MainWindow::onPreviewStopped);
    connect(controller_, &CameraController::captureStarted, this, &MainWindow::onCaptureStarted);
    connect(controller_, &CameraController::captureFinished, this, &MainWindow::onCaptureFinished);
    connect(controller_, &CameraController::logMessage, this, &MainWindow::onLogMessage);
    connect(controller_, &CameraController::errorOccurred, this, &MainWindow::onErrorOccurred);

    workerThread_->start();

    setupUi();

    // Connect pipeline runner signals to visual stepper
    connect(&services_->pipeline(), &PipelineRunner::stepStarted, this, [this](int stepIdx, int totalSteps, const QString& label) {
        stepperLabel_->setText(QString("[%1/%2] %3").arg(stepIdx + 1).arg(totalSteps).arg(label));
        stepperProgress_->setValue(static_cast<int>(stepIdx * 100.0 / totalSteps));
    });

    connect(&services_->pipeline(), &PipelineRunner::stepProgress, this, [this](int cur, int tot, const QString& msg) {
        if (tot > 0) {
            stepperProgress_->setValue(static_cast<int>(cur * 100.0 / tot));
        }
    });

    connect(&services_->pipeline(), &PipelineRunner::chainFinished, this, [this](bool success, double elapsed) {
        stepperProgress_->setValue(success ? 100 : 0);
        stepperLabel_->setText(success ? tr("[Pipeline Finished Successfully (100%)]")
                                      : tr("[Pipeline Finished with Warnings / Aborted]"));
        appendLog(QString("Pipeline executed in %1 s (success: %2)").arg(QString::number(elapsed, 'f', 2)).arg(success ? "yes" : "no"));
    });

    connect(services_.get(), &AppServices::reportPublished, this, [this](const InspectionReport& report) {
        if (viewportWidget_) {
            viewportWidget_->displayReport(report);
        }
    });

    connect(services_.get(), &AppServices::logAppended, this, &MainWindow::appendLog);

    updateStatusBadges();
    updatePrimaryActionUi();

    // Start preview immediately if camera is available
    onTogglePreview();
}

MainWindow::~MainWindow()
{
    if (workerThread_ && workerThread_->isRunning()) {
        controller_->requestStopPreview();
        controller_->requestStopCapture();
        workerThread_->quit();
        workerThread_->wait(2000);
    }
}

void MainWindow::closeEvent(QCloseEvent* event)
{
    if (capturing_) {
        auto ret = QMessageBox::question(this, tr("Operation Active"),
                                         tr("A capture is actively running. Do you want to stop and exit?"),
                                         QMessageBox::Yes | QMessageBox::No);
        if (ret != QMessageBox::Yes) {
            event->ignore();
            return;
        }
    }
    controller_->requestStopPreview();
    controller_->requestStopCapture();
    event->accept();
}

void MainWindow::keyPressEvent(QKeyEvent* event)
{
    if (event->key() == Qt::Key_Space) {
        onPrimaryAction();
        event->accept();
        return;
    } else if (event->key() >= Qt::Key_F1 && event->key() <= Qt::Key_F7) {
        int idx = event->key() - Qt::Key_F1;
        if (idx < static_cast<int>(navButtons_.size())) {
            onNavChanged(idx);
            event->accept();
            return;
        }
    }
    QMainWindow::keyPressEvent(event);
}

void MainWindow::setupUi()
{
    auto* central = new QWidget(this);
    central->setObjectName("centralRoot");
    QString checkUrl = ensureCheckIcon(dataRoot());
    central->setStyleSheet(QString(
        "QWidget#centralRoot { background: #f0f4f9; }"
        "QCheckBox { font-size: 11px; color: #1e293b; spacing: 6px; background: transparent; }"
        "QCheckBox::indicator { width: 13px; height: 13px; border: 1px solid #cbd5e1; border-radius: 3px; background-color: #ffffff; }"
        "QCheckBox::indicator:hover { border-color: #0072ce; }"
        "QCheckBox::indicator:checked { background-color: #0072ce; border-color: #0072ce; image: url(\"%1\"); }"
        "QSpinBox, QDoubleSpinBox { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 6px; font-size: 11px; color: #1e293b; min-height: 22px; }"
        "QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #0072ce; }"
        "QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; height: 0px; border: none; }")
        .arg(checkUrl));
    auto* rootLayout = new QVBoxLayout(central);
    rootLayout->setContentsMargins(8, 6, 8, 8);
    rootLayout->setSpacing(6);

    // 1. Top Quick-Parameter Bar
    rootLayout->addWidget(buildTopParameterBar());

    // 2. Central Split Viewport Area (Sidebar + Workspace + Viewport)
    auto* midLayout = new QHBoxLayout();
    midLayout->setContentsMargins(0, 0, 0, 0);
    midLayout->setSpacing(6);

    auto* splitter = new QSplitter(Qt::Horizontal, central);
    splitter->addWidget(buildWorkflowWorkspace());

    viewportWidget_ = new ViewportWidget(splitter);
    viewportWidget_->setReference(reference_);
    splitter->addWidget(viewportWidget_);
    splitter->setStretchFactor(0, 4);
    splitter->setStretchFactor(1, 6);

    midLayout->addWidget(buildSidebar());
    midLayout->addWidget(splitter, 1);
    rootLayout->addLayout(midLayout, 1);

    // 3. Permanent Action Bar & Stepper
    rootLayout->addWidget(buildPipelineStepper());
    rootLayout->addWidget(buildActionBar());

    // 4. System Log
    logCheck_ = new QCheckBox(tr("System Log"), central);
    logCheck_->setChecked(false);
    logCheck_->setStyleSheet("font-size: 11px; font-weight: 600; color: #1e293b; spacing: 6px; background: transparent;");
    rootLayout->addWidget(logCheck_);

    logText_ = new QTextEdit(central);
    logText_->setReadOnly(true);
    logText_->setFixedHeight(52);
    logText_->setStyleSheet(
        "QTextEdit { background: #eef4f9; border: 1px solid #d0d8e2; border-radius: 6px; padding: 4px 6px; font-family: 'Consolas', 'Segoe UI', monospace; font-size: 11px; color: #334155; }");
    rootLayout->addWidget(logText_);

    connect(logCheck_, &QCheckBox::toggled, this, [this](bool checked) {
        logText_->setFixedHeight(checked ? 130 : 52);
    });

    setCentralWidget(central);
}

QWidget* MainWindow::buildTopParameterBar()
{
    auto* bar = new QWidget(this);
    bar->setStyleSheet("background: transparent;");
    auto* l = new QHBoxLayout(bar);
    l->setContentsMargins(4, 2, 4, 4);
    l->setSpacing(6);

    const QString lblStyle = "font-size: 11px; font-weight: 500; color: #1e293b; background: transparent;";
    QString downArrowUrl = ensureDownArrowIcon(dataRoot());

    const QString comboStyle = QString(
        "QComboBox { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 22px 2px 8px; font-size: 11px; color: #1e293b; min-height: 22px; }"
        "QComboBox:focus { border: 1px solid #0072ce; }"
        "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 18px; border: none; }"
        "QComboBox::down-arrow { image: url(\"%1\"); width: 9px; height: 9px; }"
        "QComboBox QAbstractItemView { background: #ffffff; selection-background-color: #0072ce; color: #1e293b; border: 1px solid #cbd5e1; }").arg(downArrowUrl);

    const QString spinStyle =
        "QDoubleSpinBox { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 6px; font-size: 11px; color: #1e293b; min-height: 22px; }"
        "QDoubleSpinBox:focus { border: 1px solid #0072ce; }"
        "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; height: 0px; border: none; }";

    const QString editStyle =
        "QLineEdit { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 6px; font-size: 11px; color: #1e293b; min-height: 22px; }"
        "QLineEdit:focus { border: 1px solid #0072ce; }";

    const QString dotBtnStyle =
        "QPushButton { background: #eef2f7; border: 1px solid #c8d3df; border-radius: 6px; font-size: 11px; font-weight: bold; color: #475467; min-height: 22px; width: 22px; }"
        "QPushButton:hover { background: #e2e8f0; }"
        "QPushButton:pressed { background: #cbd5e1; }";

    auto* roiLbl = new QLabel(tr("ROI Preset:"), bar);
    roiLbl->setStyleSheet(lblStyle);
    l->addWidget(roiLbl);

    aspectCombo_ = new QComboBox(bar);
    aspectCombo_->setStyleSheet(comboStyle);
    for (const auto& p : kAspectPresets) {
        aspectCombo_->addItem(p.name);
    }
    l->addWidget(aspectCombo_);
    connect(aspectCombo_, QOverload<int>::of(&QComboBox::currentIndexChanged), this, &MainWindow::onAspectChanged);

    auto* expLbl = new QLabel(tr("Exposure:"), bar);
    expLbl->setStyleSheet(lblStyle);
    l->addWidget(expLbl);

    exposureSpin_ = new QDoubleSpinBox(bar);
    exposureSpin_->setButtonSymbols(QAbstractSpinBox::NoButtons);
    exposureSpin_->setStyleSheet(spinStyle);
    exposureSpin_->setRange(10.0, 50000.0);
    exposureSpin_->setValue(497.0);
    exposureSpin_->setDecimals(2);
    exposureSpin_->setSuffix(tr(" us"));
    l->addWidget(exposureSpin_);

    auto* durLbl = new QLabel(tr("Duration:"), bar);
    durLbl->setStyleSheet(lblStyle);
    l->addWidget(durLbl);

    durationSpin_ = new QDoubleSpinBox(bar);
    durationSpin_->setButtonSymbols(QAbstractSpinBox::NoButtons);
    durationSpin_->setStyleSheet(spinStyle);
    durationSpin_->setRange(0.1, 30.0);
    durationSpin_->setValue(3.0);
    durationSpin_->setDecimals(2);
    durationSpin_->setSuffix(tr(" s"));
    l->addWidget(durationSpin_);

    auto* lblLbl = new QLabel(tr("Run Label:"), bar);
    lblLbl->setStyleSheet(lblStyle);
    l->addWidget(lblLbl);

    runLabelEdit_ = new QLineEdit(bar);
    runLabelEdit_->setStyleSheet(editStyle);
    runLabelEdit_->setFixedWidth(75);
    l->addWidget(runLabelEdit_);

    browseLabelBtn_ = new QPushButton(tr("..."), bar);
    browseLabelBtn_->setStyleSheet(dotBtnStyle);
    l->addWidget(browseLabelBtn_);
    connect(browseLabelBtn_, &QPushButton::clicked, this, [this]() {
        QString dir = QFileDialog::getExistingDirectory(this, tr("Select Output Directory"),
                                                        QString::fromStdString(dataRoot().string()));
        if (!dir.isEmpty()) {
            lastOutputDir_ = dir;
            appendLog(tr("Output directory set to: %1").arg(dir));
        }
    });

    l->addStretch();

    // Status Badges / Pills
    scaleBadge_ = new QLabel(bar);
    refBadge_ = new QLabel(bar);
    camBadge_ = new QLabel(tr("Camera: Connecting..."), bar);
    camBadge_->setStyleSheet(
        "background: #e8edf3; color: #334155; font-weight: 600; font-size: 11px; padding: 2px 10px; border-radius: 12px; border: 1px solid #cbd5e1;");

    l->addWidget(scaleBadge_);
    l->addWidget(refBadge_);
    l->addWidget(camBadge_);

    return bar;
}

QWidget* MainWindow::buildSidebar()
{
    auto* sidebar = new QWidget(this);
    sidebar->setFixedWidth(52);
    sidebar->setObjectName("sidebarBar");
    sidebar->setStyleSheet(
        "QWidget#sidebarBar { background: #dce5ef; border: 1px solid #c8d6e5; border-radius: 8px; }"
        "QToolButton { background: transparent; color: #1e293b; font-size: 10px; font-weight: 600; border: none; border-radius: 6px; padding: 2px 0px; margin: 1px 1px; }"
        "QToolButton:hover { background: rgba(255, 255, 255, 0.45); color: #0f172a; }"
        "QToolButton:checked { background: #0072ce; color: #ffffff; }");
    auto* l = new QVBoxLayout(sidebar);
    l->setContentsMargins(3, 4, 3, 4);
    l->setSpacing(4);

    auto* btnGroup = new QButtonGroup(sidebar);
    int navId = 0;

    for (size_t i = 0; i < workflowModules_.size(); ++i) {
        auto* mod = workflowModules_[i];
        auto* btn = new QToolButton(sidebar);
        btn->setToolButtonStyle(Qt::ToolButtonTextUnderIcon);
        btn->setText(mod->title());
        btn->setIcon(getNavIcon(mod->id()));
        btn->setIconSize(QSize(20, 20));
        btn->setToolTip(mod->tooltip());
        btn->setCheckable(true);
        btn->setChecked(navId == 0);
        btn->setFixedSize(46, 44);
        btnGroup->addButton(btn, navId);
        navButtons_.push_back(btn);
        l->addWidget(btn);
        ++navId;
    }

    // Setup tab (aggregating setup tools)
    auto setupTools = FeatureRegistry::instance().modulesByCategory(FeatureCategory::SetupTool);
    if (!setupTools.empty()) {
        auto* btn = new QToolButton(sidebar);
        btn->setToolButtonStyle(Qt::ToolButtonTextUnderIcon);
        btn->setText(tr("Setup"));
        btn->setIcon(getNavIcon("setup"));
        btn->setIconSize(QSize(20, 20));
        btn->setToolTip(tr("Scale Calibration & Nozzle Reference"));
        btn->setCheckable(true);
        btn->setChecked(navId == 0);
        btn->setFixedSize(46, 44);
        btnGroup->addButton(btn, navId);
        navButtons_.push_back(btn);
        l->addWidget(btn);
        ++navId;
    }

    // Settings tab
    auto* setBtn = new QToolButton(sidebar);
    setBtn->setToolButtonStyle(Qt::ToolButtonTextUnderIcon);
    setBtn->setText(tr("Settings"));
    setBtn->setIcon(getNavIcon("settings"));
    setBtn->setIconSize(QSize(20, 20));
    setBtn->setToolTip(tr("Hardware & Algorithm Configuration"));
    setBtn->setCheckable(true);
    btnGroup->addButton(setBtn, navId);
    navButtons_.push_back(setBtn);
    l->addWidget(setBtn);

    connect(btnGroup, &QButtonGroup::idClicked, this, &MainWindow::onNavChanged);
    l->addStretch();
    return sidebar;
}

QWidget* MainWindow::buildWorkflowWorkspace()
{
    workspaceStack_ = new QStackedWidget(this);
    workspaceStack_->setMinimumWidth(340);
    workspaceStack_->setMaximumWidth(440);

    const auto& allModules = FeatureRegistry::instance().modules();
    for (const auto& mod : allModules) {
        mod->initialize(*services_);
        if (mod->category() == FeatureCategory::WorkflowTab) {
            workflowModules_.push_back(mod.get());
            QWidget* page = mod->createWidget(*services_, workspaceStack_);
            workspaceStack_->addWidget(page);
        }
    }

    // Setup Tools workspace page
    auto setupTools = FeatureRegistry::instance().modulesByCategory(FeatureCategory::SetupTool);
    if (!setupTools.empty()) {
        workspaceStack_->addWidget(buildSetupWorkspace());
    }

    // Settings workspace page
    workspaceStack_->addWidget(buildSettingsWorkspace());

    return workspaceStack_;
}

QWidget* MainWindow::buildSetupWorkspace()
{
    auto* w = new QWidget(workspaceStack_);
    auto* l = new QVBoxLayout(w);
    l->setContentsMargins(6, 6, 6, 6);

    auto* title = new QLabel(tr("📏 Rig Calibration & Setup"), w);
    title->setStyleSheet("font-size: 15px; font-weight: bold; color: #202530;");
    l->addWidget(title);

    auto setupTools = FeatureRegistry::instance().modulesByCategory(FeatureCategory::SetupTool);
    for (auto* tool : setupTools) {
        tool->initialize(*services_);
        QWidget* card = tool->createWidget(*services_, w);
        l->addWidget(card);
    }

    l->addStretch();
    return w;
}

QWidget* MainWindow::buildSettingsWorkspace()
{
    auto* w = new QWidget(workspaceStack_);
    auto* l = new QVBoxLayout(w);
    l->setContentsMargins(6, 6, 6, 6);

    auto* title = new QLabel(tr("⚙️ System & Hardware Settings"), w);
    title->setStyleSheet("font-size: 15px; font-weight: bold; color: #202530;");
    l->addWidget(title);

    auto* info = new QLabel(
        tr("<b>Camera Driver:</b> Huaray/iRayple IMV C SDK<br>"
           "<b>Format:</b> Monochrome 8-bit (Mono8)<br>"
           "<b>Output Directory:</b> data/captures/<br>"
           "<b>Log File:</b> data/app.log<br><br>"
           "All settings, calibrations, and feature configurations are stored atomically in <code>settings/</code>."),
        w);
    info->setWordWrap(true);
    info->setStyleSheet("background: #f8f9fa; border: 1px solid #dcdfe6; border-radius: 6px; padding: 10px;");
    l->addWidget(info);

    l->addStretch();
    return w;
}

QWidget* MainWindow::buildPipelineStepper()
{
    auto* bar = new QWidget(this);
    bar->setObjectName("stepperContainer");
    bar->setFixedHeight(28);
    bar->setStyleSheet("QWidget#stepperContainer { background: #ffffff; border: 1px solid #d8e0ea; border-radius: 6px; }");
    auto* l = new QHBoxLayout(bar);
    l->setContentsMargins(10, 2, 10, 2);
    l->setSpacing(8);

    stepperLabel_ = new QLabel(tr("[1. Capture] -> [2. Extract Window] -> [3. Measure] -> [4. Slow-Mo Video]"), bar);
    stepperLabel_->setStyleSheet("font-weight: bold; color: #1e293b; font-size: 11px; background: transparent;");
    l->addWidget(stepperLabel_);

    stepperProgress_ = new QProgressBar(bar);
    stepperProgress_->setRange(0, 100);
    stepperProgress_->setValue(0);
    stepperProgress_->setFixedHeight(12);
    stepperProgress_->setTextVisible(false);
    stepperProgress_->setStyleSheet(
        "QProgressBar { border: 1px solid #cbd5e1; border-radius: 5px; background: #dbe5ef; }"
        "QProgressBar::chunk { background: #0072ce; border-radius: 4px; }");
    l->addWidget(stepperProgress_, 1);

    return bar;
}

QWidget* MainWindow::buildActionBar()
{
    auto* bar = new QWidget(this);
    auto* l = new QHBoxLayout(bar);
    l->setContentsMargins(0, 2, 0, 0);
    l->setSpacing(8);

    primaryActionBtn_ = new QPushButton(tr("CAPTURE SPRAY (Space)"), bar);
    primaryActionBtn_->setFixedHeight(38);
    primaryActionBtn_->setStyleSheet(
        "QPushButton { background: #0072ce; color: #ffffff; font-size: 13px; font-weight: bold; border: none; border-radius: 6px; }"
        "QPushButton:hover { background: #0060ad; }"
        "QPushButton:pressed { background: #004c8c; }");
    l->addWidget(primaryActionBtn_, 2);

    const QString secBtnStyle =
        "QPushButton { background: #eef2f7; border: 1px solid #c8d3df; color: #1e293b; font-size: 12px; font-weight: 500; border-radius: 6px; }"
        "QPushButton:hover { background: #e2e8f0; }"
        "QPushButton:pressed { background: #cbd5e1; }";

    previewBtn_ = new QPushButton(tr("Stop Preview"), bar);
    previewBtn_->setFixedHeight(38);
    previewBtn_->setStyleSheet(secBtnStyle);
    l->addWidget(previewBtn_, 1);

    openFolderBtn_ = new QPushButton(tr("Open Last Folder"), bar);
    openFolderBtn_->setFixedHeight(38);
    openFolderBtn_->setStyleSheet(secBtnStyle);
    l->addWidget(openFolderBtn_, 1);

    connect(primaryActionBtn_, &QPushButton::clicked, this, &MainWindow::onPrimaryAction);
    connect(previewBtn_, &QPushButton::clicked, this, &MainWindow::onTogglePreview);
    connect(openFolderBtn_, &QPushButton::clicked, this, &MainWindow::onOpenLastFolder);

    return bar;
}

void MainWindow::onNavChanged(int index)
{
    activeNavIndex_ = index;
    workspaceStack_->setCurrentIndex(index);
    for (size_t i = 0; i < navButtons_.size(); ++i) {
        navButtons_[i]->setChecked(static_cast<int>(i) == index);
    }
    updatePrimaryActionUi();
}

void MainWindow::updatePrimaryActionUi()
{
    if (capturing_) {
        primaryActionBtn_->setText(tr("STOP (Space)"));
        primaryActionBtn_->setStyleSheet(
            "QPushButton { background: #d32f2f; color: #ffffff; font-size: 14px; font-weight: bold; border-radius: 6px; }");
        return;
    }

    if (activeNavIndex_ < static_cast<int>(workflowModules_.size())) {
        auto* mod = workflowModules_[activeNavIndex_];
        QString label = mod->primaryActionLabel();
        if (label.isEmpty()) label = tr("READY");
        primaryActionBtn_->setText(label);
        QString color = mod->primaryActionColor().isEmpty() ? "#0072ce" : mod->primaryActionColor();
        primaryActionBtn_->setStyleSheet(
            QString("QPushButton { background: %1; color: #ffffff; font-size: 14px; font-weight: bold; border-radius: 6px; padding: 0 24px; }"
                    "QPushButton:hover { opacity: 0.9; }").arg(color));
    } else {
        primaryActionBtn_->setText(tr("READY"));
        primaryActionBtn_->setStyleSheet(
            "QPushButton { background: #78909c; color: #ffffff; font-size: 14px; font-weight: bold; border-radius: 6px; }");
    }
}

void MainWindow::updateStatusBadges()
{
    // Scale badge
    calibration_ = ScaleCalibrationStore::load();
    if (calibration_ && calibration_->isValid()) {
        scaleBadge_->setText(QString("Scale: %1 mm/px [OK]").arg(QString::number(calibration_->mm_per_px, 'f', 4)));
        scaleBadge_->setStyleSheet(
            "background: #dcfce7; color: #15803d; border: 1px solid #86efac; font-weight: 600; font-size: 11px; padding: 2px 10px; border-radius: 12px;");
    } else {
        scaleBadge_->setText(tr("Scale: Default (0.052) [WARN]"));
        scaleBadge_->setStyleSheet(
            "background: #fef3c7; color: #b45309; border: 1px solid #fcd34d; font-weight: 600; font-size: 11px; padding: 2px 10px; border-radius: 12px;");
    }

    // Ref badge
    reference_ = NozzleReferenceStore::load();
    int cur_idx = aspectCombo_->currentIndex();
    int cur_w = kAspectPresets[cur_idx].width;
    int cur_h = kAspectPresets[cur_idx].height;

    if (reference_ && reference_->isValid()) {
        if (reference_->image_width == cur_w && reference_->image_height == cur_h) {
            refBadge_->setText(QString("Nozzle Ref: %1x%2 [OK]").arg(cur_w).arg(cur_h));
            refBadge_->setStyleSheet(
                "background: #dcfce7; color: #15803d; border: 1px solid #86efac; font-weight: 600; font-size: 11px; padding: 2px 10px; border-radius: 12px;");
        } else {
            refBadge_->setText(QString("Nozzle Ref: %1x%2 [MISMATCH!]").arg(reference_->image_width).arg(reference_->image_height));
            refBadge_->setStyleSheet(
                "background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; font-weight: 600; font-size: 11px; padding: 2px 10px; border-radius: 12px;");
        }
    } else {
        refBadge_->setText(tr("Nozzle Ref: None (Cone mode)"));
        refBadge_->setStyleSheet(
            "background: #e8edf3; color: #334155; border: 1px solid #cbd5e1; font-weight: 600; font-size: 11px; padding: 2px 10px; border-radius: 12px;");
    }
}

CaptureSettings MainWindow::collectSettings() const
{
    CaptureSettings s;
    int idx = aspectCombo_->currentIndex();
    s.width = kAspectPresets[idx].width;
    s.height = kAspectPresets[idx].height;
    s.exposureUs = exposureSpin_->value();
    s.durationSeconds = durationSpin_->value();
    s.outputBaseDir = QString::fromStdString(dataRoot().string());
    s.deferSave = true;
    s.timestampDir = true;
    return s;
}

void MainWindow::onAspectChanged(int /*index*/)
{
    updateStatusBadges();
    if (previewing_) {
        controller_->requestStopPreview();
        CaptureSettings s = collectSettings();
        QMetaObject::invokeMethod(controller_, "startPreview", Qt::QueuedConnection, Q_ARG(CaptureSettings, s));
    }
}

void MainWindow::onTogglePreview()
{
    if (previewing_) {
        controller_->requestStopPreview();
        previewBtn_->setText(tr("Start Preview"));
    } else {
        CaptureSettings s = collectSettings();
        QMetaObject::invokeMethod(controller_, "startPreview", Qt::QueuedConnection, Q_ARG(CaptureSettings, s));
        previewBtn_->setText(tr("Stop Preview"));
    }
}

void MainWindow::onPrimaryAction()
{
    if (capturing_) {
        controller_->requestStopCapture();
        return;
    }

    if (activeNavIndex_ < static_cast<int>(workflowModules_.size())) {
        auto* mod = workflowModules_[activeNavIndex_];
        mod->onPrimaryActionTriggered(*services_);

        if (mod->usesCamera()) {
            capturing_ = true;
            updatePrimaryActionUi();
            stepperProgress_->setValue(10);
            stepperLabel_->setText(tr("[1. Grabbing Camera Burst into RAM...]"));

            CaptureSettings s = collectSettings();
            QMetaObject::invokeMethod(controller_, "runCapture", Qt::QueuedConnection, Q_ARG(CaptureSettings, s));
        }
    }
}

void MainWindow::onPreviewFrame(const QImage& image)
{
    lastGrabbedStill_ = image;
    if (viewportWidget_) {
        viewportWidget_->updateLiveFrame(image);
    }
}

void MainWindow::onPreviewStarted()
{
    previewing_ = true;
    camBadge_->setText(tr("Camera: AH7040MU000 [Online]"));
    camBadge_->setStyleSheet("background: #dcfce7; color: #15803d; border: 1px solid #86efac; font-weight: 600; font-size: 11px; padding: 2px 10px; border-radius: 12px;");
    previewBtn_->setText(tr("Stop Preview"));
    emit cameraInitFinished();
}

void MainWindow::onPreviewStopped()
{
    previewing_ = false;
    camBadge_->setText(tr("Camera: Offline"));
    camBadge_->setStyleSheet("background: #e8edf3; color: #334155; border: 1px solid #cbd5e1; font-weight: 600; font-size: 11px; padding: 2px 10px; border-radius: 12px;");
    previewBtn_->setText(tr("Start Preview"));
}

void MainWindow::onCaptureStarted()
{
    capturing_ = true;
    updatePrimaryActionUi();
    appendLog(tr("Burst capture started..."));
}

void MainWindow::onCaptureFinished(const QString& outputDir, int saved, double fps)
{
    capturing_ = false;
    updatePrimaryActionUi();
    lastOutputDir_ = outputDir;

    appendLog(QString("Capture complete: %1 frames saved @ %2 fps into %3")
                  .arg(saved).arg(QString::number(fps, 'f', 1)).arg(outputDir));

    std::filesystem::path capture_path = outputDir.toStdString();
    if (activeNavIndex_ >= static_cast<int>(workflowModules_.size())) return;

    auto* activeMod = workflowModules_[activeNavIndex_];
    QString modId = activeMod->id();

    // Compose asynchronous multi-step pipeline
    std::vector<PipelineStep> steps;

    steps.push_back({tr("Analyzing Capture Data"), [this, modId, capture_path](std::atomic<bool>& cancel, std::function<void(int, int, const QString&)> progress) -> bool {
        if (cancel) return false;
        auto rep = services_->runAnalyzer(modId, capture_path, progress);
        if (rep) {
            services_->publishReport(*rep);
        }
        return true;
    }});

    steps.push_back({tr("Generating Slow-Motion Video"), [capture_path](std::atomic<bool>& cancel, std::function<void(int, int, const QString&)> progress) -> bool {
        if (cancel) return false;
        auto video_path = capture_path / "slowmo.avi";
        if (!std::filesystem::exists(video_path)) {
            makeVideo(capture_path, video_path, 15);
        }
        return true;
    }});

    services_->pipeline().runChain(activeMod->title() + " Pipeline", steps, [this, outputDir](bool success) {
        appendLog(QString("Pipeline completed for %1 (success=%2)").arg(outputDir).arg(success));
    });
}

void MainWindow::onOpenLastFolder()
{
    if (lastOutputDir_.isEmpty() || !QDir(lastOutputDir_).exists()) {
        lastOutputDir_ = QString::fromStdString(dataRoot().string());
    }
    QDesktopServices::openUrl(QUrl::fromLocalFile(lastOutputDir_));
}

void MainWindow::onLogMessage(const QString& text)
{
    appendLog(text);
}

void MainWindow::onErrorOccurred(const QString& message)
{
    appendLog(QString("[ERROR] %1").arg(message));
    emit cameraInitFinished();
}

void MainWindow::appendLog(const QString& text)
{
    QString timestamp = QDateTime::currentDateTime().toString("hh:mm:ss.zzz");
    QString line;
    if (text.startsWith("[ERROR]")) {
        QString msg = text.mid(7).trimmed();
        line = QString("<span style=\"color:#64748b;\">[%1]</span> <span style=\"color:#d32f2f; font-weight:bold;\">[ERROR]</span> %2")
                   .arg(timestamp, msg.toHtmlEscaped());
    } else {
        line = QString("<span style=\"color:#64748b;\">[%1]</span> %2").arg(timestamp, text.toHtmlEscaped());
    }
    if (logText_) {
        logText_->append(line);
    }

    auto log_path = dataRoot() / "app.log";
    std::ofstream lf(log_path, std::ios::app);
    if (lf) {
        lf << QString("[%1] %2\n").arg(timestamp, text).toStdString();
    }
}

} // namespace hsc
