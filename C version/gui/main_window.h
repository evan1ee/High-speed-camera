#pragma once

#include "camera_controller.h"
#include "src/foundation/calibration_store.h"
#include "src/foundation/reference_store.h"
#include "src/shell/app_services.h"
#include "src/shell/feature_registry.h"
#include "src/shell/i_feature_module.h"
#include "src/shell/inspection_report.h"
#include "src/shell/pipeline_runner.h"
#include "src/shell/viewport_widget.h"

#include <memory>
#include <vector>
#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QLabel>
#include <QLineEdit>
#include <QMainWindow>
#include <QProgressBar>
#include <QPushButton>
#include <QStackedWidget>
#include <QTextEdit>
#include <QToolButton>

namespace hsc {

using ::CameraController;

class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

signals:
    void cameraInitFinished();

protected:
    void closeEvent(QCloseEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;

private slots:
    void onNavChanged(int index);
    void onAspectChanged(int index);
    void onPrimaryAction();
    void onTogglePreview();
    void onOpenLastFolder();

    // Camera worker slots
    void onPreviewFrame(const QImage& image);
    void onPreviewStarted();
    void onPreviewStopped();
    void onCaptureStarted();
    void onCaptureFinished(const QString& outputDir, int saved, double fps);
    void onLogMessage(const QString& text);
    void onErrorOccurred(const QString& message);

private:
    void setupUi();
    QWidget* buildTopParameterBar();
    QWidget* buildSidebar();
    QWidget* buildWorkflowWorkspace();
    QWidget* buildActionBar();
    QWidget* buildPipelineStepper();
    QWidget* buildSetupWorkspace();
    QWidget* buildSettingsWorkspace();

    void updateStatusBadges();
    void updatePrimaryActionUi();
    void appendLog(const QString& text);
    CaptureSettings collectSettings() const;

    // Controllers & Services
    QThread* workerThread_ = nullptr;
    CameraController* controller_ = nullptr;
    std::unique_ptr<AppServices> services_;

    // Top parameter bar widgets
    QComboBox* aspectCombo_ = nullptr;
    QDoubleSpinBox* exposureSpin_ = nullptr;
    QDoubleSpinBox* durationSpin_ = nullptr;
    QLineEdit* runLabelEdit_ = nullptr;
    QPushButton* browseLabelBtn_ = nullptr;
    QLabel* scaleBadge_ = nullptr;
    QLabel* refBadge_ = nullptr;
    QLabel* camBadge_ = nullptr;

    // Sidebar & Workspace
    QStackedWidget* workspaceStack_ = nullptr;
    ViewportWidget* viewportWidget_ = nullptr;
    std::vector<QToolButton*> navButtons_;
    std::vector<IFeatureModule*> workflowModules_;
    int activeNavIndex_ = 0;

    // Permanent action bar & Stepper
    QPushButton* primaryActionBtn_ = nullptr;
    QPushButton* previewBtn_ = nullptr;
    QPushButton* openFolderBtn_ = nullptr;
    QLabel* stepperLabel_ = nullptr;
    QProgressBar* stepperProgress_ = nullptr;
    QCheckBox* logCheck_ = nullptr;
    QTextEdit* logText_ = nullptr;

    // Calibration & Reference
    std::optional<ScaleCalibration> calibration_;
    std::optional<NozzleReference> reference_;

    QString lastOutputDir_;
    bool previewing_ = false;
    bool capturing_ = false;
    QImage lastGrabbedStill_;
};

} // namespace hsc
