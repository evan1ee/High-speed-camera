// MainWindow mirrors the layout/UX of the Python tkinter capture_gui.py:
// a capture-settings panel, a live preview pane, action buttons, a status
// line, and an output log. All camera work happens in a CameraController on
// a worker thread; this class only builds the UI and relays signals.

#pragma once

#include <QMainWindow>

#include "camera_controller.h"

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QPlainTextEdit;
class QPushButton;
class QSpinBox;
class QThread;

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

protected:
    void closeEvent(QCloseEvent* event) override;

private slots:
    void onAspectChanged(int index);
    void onBrowse();
    void onRefreshDevices();
    void onTogglePreview();
    void onRunCapture();
    void onStop();
    void onOpenLastFolder();

    void onDevicesEnumerated(const QStringList& devices);
    void onPreviewFrame(const QImage& image);
    void onPreviewStarted();
    void onPreviewStopped();
    void onCaptureStarted();
    void onCaptureFinished(const QString& outputDir, int saved, double fps);
    void onLogMessage(const QString& text);
    void onErrorOccurred(const QString& message);

private:
    QWidget* buildSettingsPanel();
    QWidget* buildPreviewPanel();
    QWidget* buildActionBar();
    void appendLog(const QString& text);
    bool collectSettings(CaptureSettings& out, QString& error) const;
    void updatePreviewLabel();

    // Settings widgets
    QDoubleSpinBox* durationSpin_ = nullptr;
    QComboBox* aspectCombo_ = nullptr;
    QDoubleSpinBox* exposureSpin_ = nullptr;
    QSpinBox* cameraIndexSpin_ = nullptr;
    QComboBox* extCombo_ = nullptr;
    QLineEdit* outputDirEdit_ = nullptr;
    QCheckBox* deferSaveCheck_ = nullptr;
    QCheckBox* timestampCheck_ = nullptr;
    QCheckBox* noSaveCheck_ = nullptr;

    // Action widgets
    QPushButton* previewButton_ = nullptr;
    QPushButton* runButton_ = nullptr;
    QPushButton* stopButton_ = nullptr;
    QPushButton* openButton_ = nullptr;
    QPushButton* refreshButton_ = nullptr;
    QLabel* statusLabel_ = nullptr;

    // Preview + log
    QLabel* previewLabel_ = nullptr;
    QPlainTextEdit* logText_ = nullptr;
    QImage lastPreview_;

    int aspectWidth_ = 576;
    int aspectHeight_ = 324;
    QString lastOutputDir_;

    bool previewing_ = false;
    bool capturing_ = false;

    QThread* workerThread_ = nullptr;
    CameraController* controller_ = nullptr;
};
