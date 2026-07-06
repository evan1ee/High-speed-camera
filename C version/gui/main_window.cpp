#include "main_window.h"

#include <QCheckBox>
#include <QCloseEvent>
#include <QComboBox>
#include <QDesktopServices>
#include <QDir>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSpinBox>
#include <QThread>
#include <QUrl>
#include <QVBoxLayout>

namespace {

struct AspectPreset
{
    const char* name;
    int width;
    int height;
};

const AspectPreset kAspectPresets[] = {
    {"1:1", 332, 332},
    {"2:1", 664, 332},
    {"4:3", 432, 324},
    {"16:9", 576, 324},
    {"320x240", 320, 240},
};

} // namespace

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent)
{
    setWindowTitle(tr("High Speed Camera Capture"));
    resize(1040, 720);

    auto* central = new QWidget(this);
    auto* rootLayout = new QVBoxLayout(central);

    auto* top = new QHBoxLayout();
    top->addWidget(buildSettingsPanel(), 1);
    top->addWidget(buildPreviewPanel(), 0);
    rootLayout->addLayout(top);

    rootLayout->addWidget(buildActionBar());

    auto* logGroup = new QGroupBox(tr("Output"), central);
    auto* logLayout = new QVBoxLayout(logGroup);
    logText_ = new QPlainTextEdit(logGroup);
    logText_->setReadOnly(true);
    logLayout->addWidget(logText_);
    rootLayout->addWidget(logGroup, 1);

    setCentralWidget(central);

    // Worker thread + controller
    workerThread_ = new QThread(this);
    controller_ = new CameraController();
    controller_->moveToThread(workerThread_);

    connect(workerThread_, &QThread::finished, controller_, &QObject::deleteLater);
    connect(controller_, &CameraController::devicesEnumerated, this, &MainWindow::onDevicesEnumerated);
    connect(controller_, &CameraController::previewFrame, this, &MainWindow::onPreviewFrame);
    connect(controller_, &CameraController::previewStarted, this, &MainWindow::onPreviewStarted);
    connect(controller_, &CameraController::previewStopped, this, &MainWindow::onPreviewStopped);
    connect(controller_, &CameraController::captureStarted, this, &MainWindow::onCaptureStarted);
    connect(controller_, &CameraController::captureFinished, this, &MainWindow::onCaptureFinished);
    connect(controller_, &CameraController::logMessage, this, &MainWindow::onLogMessage);
    connect(controller_, &CameraController::errorOccurred, this, &MainWindow::onErrorOccurred);

    workerThread_->start();

    onAspectChanged(aspectCombo_->currentIndex());
    statusLabel_->setText(tr("Ready"));
}

MainWindow::~MainWindow() = default;

QWidget* MainWindow::buildSettingsPanel()
{
    auto* group = new QGroupBox(tr("Capture Settings"), this);
    auto* form = new QFormLayout(group);

    durationSpin_ = new QDoubleSpinBox(group);
    durationSpin_->setRange(0.01, 3600.0);
    durationSpin_->setDecimals(2);
    durationSpin_->setValue(1.0);
    durationSpin_->setSuffix(tr(" s"));
    form->addRow(tr("Capture time"), durationSpin_);

    aspectCombo_ = new QComboBox(group);
    for (const auto& preset : kAspectPresets)
        aspectCombo_->addItem(QString::fromLatin1(preset.name));
    aspectCombo_->setCurrentText(QStringLiteral("16:9"));
    connect(aspectCombo_, qOverload<int>(&QComboBox::currentIndexChanged), this, &MainWindow::onAspectChanged);
    form->addRow(tr("Aspect preset"), aspectCombo_);

    exposureSpin_ = new QDoubleSpinBox(group);
    exposureSpin_->setRange(1.0, 1000000.0);
    exposureSpin_->setDecimals(1);
    exposureSpin_->setValue(1000.0);
    exposureSpin_->setSuffix(tr(" us"));
    form->addRow(tr("Exposure"), exposureSpin_);

    cameraIndexSpin_ = new QSpinBox(group);
    cameraIndexSpin_->setRange(1, 64);
    cameraIndexSpin_->setValue(1);
    form->addRow(tr("Camera index"), cameraIndexSpin_);

    extCombo_ = new QComboBox(group);
    extCombo_->addItems({".bmp", ".png", ".jpg", ".tif"});
    form->addRow(tr("Image type"), extCombo_);

    auto* dirRow = new QHBoxLayout();
    outputDirEdit_ = new QLineEdit(group);
    outputDirEdit_->setText(QDir(QDir::currentPath()).filePath("captures/burst_16x9_820fps_cpp"));
    auto* browseButton = new QPushButton(tr("Browse"), group);
    connect(browseButton, &QPushButton::clicked, this, &MainWindow::onBrowse);
    dirRow->addWidget(outputDirEdit_);
    dirRow->addWidget(browseButton);
    form->addRow(tr("Output base folder"), dirRow);

    auto* checks = new QHBoxLayout();
    deferSaveCheck_ = new QCheckBox(tr("Defer save"), group);
    deferSaveCheck_->setChecked(true);
    timestampCheck_ = new QCheckBox(tr("Timestamp folder"), group);
    timestampCheck_->setChecked(true);
    noSaveCheck_ = new QCheckBox(tr("Test only, do not save"), group);
    checks->addWidget(deferSaveCheck_);
    checks->addWidget(timestampCheck_);
    checks->addWidget(noSaveCheck_);
    checks->addStretch();
    form->addRow(checks);

    return group;
}

QWidget* MainWindow::buildPreviewPanel()
{
    auto* group = new QGroupBox(tr("Live Preview"), this);
    auto* layout = new QVBoxLayout(group);
    previewLabel_ = new QLabel(tr("Preview stopped"), group);
    previewLabel_->setAlignment(Qt::AlignCenter);
    previewLabel_->setMinimumSize(420, 320);
    previewLabel_->setStyleSheet("QLabel { background: #202020; color: #cccccc; }");
    layout->addWidget(previewLabel_);
    return group;
}

QWidget* MainWindow::buildActionBar()
{
    auto* bar = new QWidget(this);
    auto* layout = new QHBoxLayout(bar);
    layout->setContentsMargins(0, 0, 0, 0);

    previewButton_ = new QPushButton(tr("Start Preview"), bar);
    runButton_ = new QPushButton(tr("Run Capture"), bar);
    stopButton_ = new QPushButton(tr("Stop"), bar);
    openButton_ = new QPushButton(tr("Open Last Folder"), bar);
    refreshButton_ = new QPushButton(tr("Refresh Devices"), bar);
    stopButton_->setEnabled(false);

    connect(previewButton_, &QPushButton::clicked, this, &MainWindow::onTogglePreview);
    connect(runButton_, &QPushButton::clicked, this, &MainWindow::onRunCapture);
    connect(stopButton_, &QPushButton::clicked, this, &MainWindow::onStop);
    connect(openButton_, &QPushButton::clicked, this, &MainWindow::onOpenLastFolder);
    connect(refreshButton_, &QPushButton::clicked, this, &MainWindow::onRefreshDevices);

    statusLabel_ = new QLabel(tr("Ready"), bar);

    layout->addWidget(previewButton_);
    layout->addWidget(runButton_);
    layout->addWidget(stopButton_);
    layout->addWidget(openButton_);
    layout->addWidget(refreshButton_);
    layout->addSpacing(16);
    layout->addWidget(statusLabel_, 1);

    return bar;
}

void MainWindow::onAspectChanged(int index)
{
    if (index < 0 || index >= static_cast<int>(std::size(kAspectPresets)))
        return;
    aspectWidth_ = kAspectPresets[index].width;
    aspectHeight_ = kAspectPresets[index].height;
}

void MainWindow::onBrowse()
{
    const QString start = outputDirEdit_->text().isEmpty() ? QDir::currentPath() : outputDirEdit_->text();
    const QString selected = QFileDialog::getExistingDirectory(this, tr("Select output base folder"), start);
    if (!selected.isEmpty())
        outputDirEdit_->setText(selected);
}

bool MainWindow::collectSettings(CaptureSettings& out, QString& error) const
{
    out.cameraIndex = cameraIndexSpin_->value();
    out.width = aspectWidth_;
    out.height = aspectHeight_;
    out.centerRoi = true;
    out.pixelFormat = QStringLiteral("Mono8");
    out.exposureUs = exposureSpin_->value();
    out.durationSeconds = durationSpin_->value();
    out.outputBaseDir = outputDirEdit_->text().trimmed();
    out.ext = extCombo_->currentText();
    out.prefix = QStringLiteral("frame");
    out.deferSave = deferSaveCheck_->isChecked();
    out.timestampDir = timestampCheck_->isChecked();
    out.noSave = noSaveCheck_->isChecked();

    if (out.durationSeconds <= 0.0)
    {
        error = tr("Capture time must be a positive number.");
        return false;
    }
    if (out.exposureUs <= 0.0)
    {
        error = tr("Exposure must be a positive number.");
        return false;
    }
    if (!out.noSave && out.outputBaseDir.isEmpty())
    {
        error = tr("Output base folder is required when saving.");
        return false;
    }
    return true;
}

void MainWindow::onRefreshDevices()
{
    appendLog(tr("Enumerating devices...\n"));
    QMetaObject::invokeMethod(controller_, "enumerateDevices", Qt::QueuedConnection);
}

void MainWindow::onTogglePreview()
{
    if (previewing_)
    {
        statusLabel_->setText(tr("Stopping preview..."));
        controller_->requestStopPreview();
        return;
    }

    if (capturing_)
    {
        statusLabel_->setText(tr("Wait until capture finishes."));
        return;
    }

    CaptureSettings settings;
    QString error;
    if (!collectSettings(settings, error))
    {
        statusLabel_->setText(error);
        return;
    }

    statusLabel_->setText(tr("Starting preview..."));
    previewButton_->setEnabled(false);
    QMetaObject::invokeMethod(controller_, "startPreview", Qt::QueuedConnection,
                              Q_ARG(CaptureSettings, settings));
}

void MainWindow::onRunCapture()
{
    if (previewing_)
    {
        statusLabel_->setText(tr("Stop preview before capturing."));
        return;
    }
    if (capturing_)
        return;

    CaptureSettings settings;
    QString error;
    if (!collectSettings(settings, error))
    {
        statusLabel_->setText(error);
        return;
    }

    logText_->clear();
    appendLog(tr("Running capture...\n"));
    statusLabel_->setText(tr("Capturing..."));
    lastOutputDir_.clear();

    QMetaObject::invokeMethod(controller_, "runCapture", Qt::QueuedConnection,
                              Q_ARG(CaptureSettings, settings));
}

void MainWindow::onStop()
{
    if (previewing_)
    {
        statusLabel_->setText(tr("Stopping preview..."));
        controller_->requestStopPreview();
    }
    if (capturing_)
    {
        statusLabel_->setText(tr("Stopping capture..."));
        controller_->requestStopCapture();
    }
}

void MainWindow::onOpenLastFolder()
{
    QString folder = lastOutputDir_.isEmpty() ? outputDirEdit_->text() : lastOutputDir_;
    if (folder.isEmpty() || !QDir(folder).exists())
    {
        statusLabel_->setText(tr("No output folder found yet."));
        return;
    }
    QDesktopServices::openUrl(QUrl::fromLocalFile(folder));
}

void MainWindow::onDevicesEnumerated(const QStringList& devices)
{
    if (devices.isEmpty())
    {
        appendLog(tr("No cameras found.\n"));
        return;
    }
    appendLog(tr("Cameras:\n"));
    for (const QString& d : devices)
        appendLog(QStringLiteral("  ") + d + QStringLiteral("\n"));
}

void MainWindow::onPreviewFrame(const QImage& image)
{
    lastPreview_ = image;
    updatePreviewLabel();
}

void MainWindow::updatePreviewLabel()
{
    if (lastPreview_.isNull())
        return;
    previewLabel_->setPixmap(QPixmap::fromImage(lastPreview_)
                                 .scaled(previewLabel_->size(), Qt::KeepAspectRatio,
                                         Qt::SmoothTransformation));
}

void MainWindow::onPreviewStarted()
{
    previewing_ = true;
    previewButton_->setEnabled(true);
    previewButton_->setText(tr("Stop Preview"));
    stopButton_->setEnabled(true);
    runButton_->setEnabled(false);
    statusLabel_->setText(tr("Preview running..."));
}

void MainWindow::onPreviewStopped()
{
    previewing_ = false;
    previewButton_->setEnabled(true);
    previewButton_->setText(tr("Start Preview"));
    stopButton_->setEnabled(capturing_);
    runButton_->setEnabled(true);
    previewLabel_->setText(tr("Preview stopped"));
    previewLabel_->setPixmap(QPixmap());
    lastPreview_ = QImage();
    statusLabel_->setText(tr("Preview stopped"));
}

void MainWindow::onCaptureStarted()
{
    capturing_ = true;
    runButton_->setEnabled(false);
    previewButton_->setEnabled(false);
    stopButton_->setEnabled(true);
    statusLabel_->setText(tr("Capturing..."));
}

void MainWindow::onCaptureFinished(const QString& outputDir, int saved, double fps)
{
    capturing_ = false;
    runButton_->setEnabled(true);
    previewButton_->setEnabled(true);
    stopButton_->setEnabled(previewing_);
    if (!outputDir.isEmpty())
        lastOutputDir_ = outputDir;
    statusLabel_->setText(tr("Done. Saved %1 frames, %2 FPS.").arg(saved).arg(fps, 0, 'f', 1));
}

void MainWindow::onLogMessage(const QString& text)
{
    appendLog(text + QStringLiteral("\n"));
}

void MainWindow::onErrorOccurred(const QString& message)
{
    appendLog(tr("[Error] %1\n").arg(message));
    statusLabel_->setText(tr("Error: %1").arg(message));
    // Reset transient UI state so the user can retry.
    if (!previewing_)
    {
        previewButton_->setEnabled(true);
        previewButton_->setText(tr("Start Preview"));
    }
    if (!capturing_)
        runButton_->setEnabled(true);
    stopButton_->setEnabled(previewing_ || capturing_);
}

void MainWindow::appendLog(const QString& text)
{
    logText_->moveCursor(QTextCursor::End);
    logText_->insertPlainText(text);
    logText_->moveCursor(QTextCursor::End);
}

void MainWindow::closeEvent(QCloseEvent* event)
{
    controller_->requestStopPreview();
    controller_->requestStopCapture();

    workerThread_->quit();
    workerThread_->wait(3000);

    event->accept();
}
