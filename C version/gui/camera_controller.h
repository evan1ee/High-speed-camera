// CameraController drives the Huaray/iRayple IMV C SDK directly for both
// live preview and deferred-save burst capture. It is a QObject worker that
// is moved onto its own QThread; the GUI talks to it via queued slot calls
// and receives results through signals.
//
// Stop requests (requestStopPreview / requestStopCapture) flip std::atomic
// flags and are safe to call from the GUI thread while a grab loop is busy
// inside the worker thread (the loop polls the flags directly).

#pragma once

#include <QImage>
#include <QMetaType>
#include <QObject>
#include <QString>
#include <QStringList>

#include <atomic>

#include <IMVApi.h>

struct CaptureSettings
{
    int cameraIndex = 1; // 1-based, matches the CLI and Python GUI
    int width = 576;
    int height = 324;
    bool centerRoi = true;
    QString pixelFormat = "Mono8";
    double exposureUs = 1000.0;
    double durationSeconds = 1.0;
    QString outputBaseDir;
    QString ext = ".bmp";
    QString prefix = "frame";
    bool deferSave = true;
    bool timestampDir = true;
    bool noSave = false;
};

Q_DECLARE_METATYPE(CaptureSettings)

class CameraController : public QObject
{
    Q_OBJECT

public:
    explicit CameraController(QObject* parent = nullptr);
    ~CameraController() override;

    // Thread-safe stop requests, called directly from the GUI thread.
    void requestStopPreview() { stopPreview_ = true; }
    void requestStopCapture() { stopCapture_ = true; }

public slots:
    void enumerateDevices();
    void startPreview(const CaptureSettings& settings);
    void runCapture(const CaptureSettings& settings);

signals:
    void devicesEnumerated(const QStringList& devices);
    void previewFrame(const QImage& image);
    void previewStarted();
    void previewStopped();
    void captureStarted();
    void captureFinished(const QString& outputDir, int saved, double fps);
    void logMessage(const QString& text);
    void errorOccurred(const QString& message);

private:
    bool openCamera(const CaptureSettings& settings, IMV_HANDLE& handle, QString& error);
    void configureCamera(IMV_HANDLE handle, const CaptureSettings& settings);
    void closeCamera(IMV_HANDLE handle);

    bool setEnumFeature(IMV_HANDLE handle, const char* name, const QString& value);
    bool setIntFeature(IMV_HANDLE handle, const char* name, int64_t value);
    bool setDoubleFeature(IMV_HANDLE handle, const char* name, double value);

    QImage toQImage(const IMV_Frame& frame) const;
    QString makeOutputDir(const CaptureSettings& settings) const;
    static IMV_ESaveFileType saveTypeFromExt(const QString& ext);
    void saveFrame(IMV_HANDLE handle, const IMV_Frame& frame, const QString& path,
                   IMV_ESaveFileType saveType);

    std::atomic<bool> stopPreview_{false};
    std::atomic<bool> stopCapture_{false};
    std::atomic<bool> busy_{false};
};
