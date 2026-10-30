#include <QApplication>
#include <QTimer>

#include "camera_controller.h"
#include "main_window.h"
#include "src/shell/ui_icons.h"

#ifdef _WIN32
#include <windows.h>
#include <shobjidl_core.h>
#endif

int main(int argc, char** argv)
{
#ifdef _WIN32
    // Explicit AppUserModelID ensures Windows Taskbar groups and pins the application with its custom icon
    SetCurrentProcessExplicitAppUserModelID(L"HighSpeedCamera.AnalysisMetrologySystem.1.0");
#endif

    QApplication app(argc, argv);

    // Set default application icon for all windows, dialogs, and taskbar
    app.setWindowIcon(hsc::getAppWindowIcon());

    // Clean, modern styling for numeric inputs with stepper arrow buttons removed
    app.setStyleSheet(
        "QSpinBox, QDoubleSpinBox { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px 6px; font-size: 11px; color: #1e293b; min-height: 22px; }"
        "QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #0072ce; }"
        "QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; height: 0px; border: none; }"
    );

    // CaptureSettings crosses thread boundaries via queued slot calls.
    qRegisterMetaType<CaptureSettings>("CaptureSettings");

    hsc::MainWindow window;
    window.resize(1024, 658);
    window.show();

    QString screenshotPath;
    int targetTab = 0;
    QStringList args = QCoreApplication::arguments();
    for (int i = 1; i < args.size(); ++i) {
        if (args[i] == "--screenshot" && i + 1 < args.size()) {
            screenshotPath = args[i + 1];
        } else if (args[i] == "--tab" && i + 1 < args.size()) {
            targetTab = args[i + 1].toInt();
        }
    }

    if (!screenshotPath.isEmpty()) {
        auto takeScreenshot = [screenshotPath, targetTab, &window, &app]() {
            if (targetTab > 0) {
                QMetaObject::invokeMethod(&window, "onNavChanged", Qt::DirectConnection, Q_ARG(int, targetTab));
            }
            app.processEvents();
            QPixmap pix = window.grab();
            pix.save(screenshotPath, "PNG");
            app.quit();
        };

        // Capture screenshot right after camera initialization and logging completes
        QObject::connect(&window, &hsc::MainWindow::cameraInitFinished, [takeScreenshot]() {
            QTimer::singleShot(150, takeScreenshot);
        });

        // Safety fallback timer if no camera event arrives within 15 seconds
        QTimer::singleShot(15000, takeScreenshot);
    }

    return app.exec();
}

