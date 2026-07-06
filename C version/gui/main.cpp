#include <QApplication>

#include "camera_controller.h"
#include "main_window.h"

int main(int argc, char** argv)
{
    QApplication app(argc, argv);

    // CaptureSettings crosses thread boundaries via queued slot calls.
    qRegisterMetaType<CaptureSettings>("CaptureSettings");

    MainWindow window;
    window.show();

    return app.exec();
}
