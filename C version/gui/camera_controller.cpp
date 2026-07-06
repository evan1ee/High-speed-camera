#include "camera_controller.h"

#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QThread>

#include <cstring>
#include <vector>

namespace {

QString cameraTypeName(IMV_ECameraType type)
{
    switch (type)
    {
    case typeGigeCamera:
        return QStringLiteral("GigE");
    case typeU3vCamera:
        return QStringLiteral("USB3/U3V");
    case typeCLCamera:
        return QStringLiteral("CL");
    case typePCIeCamera:
        return QStringLiteral("PCIe");
    default:
        return QStringLiteral("Unknown");
    }
}

int64_t intFeatureMax(IMV_HANDLE handle, const char* name)
{
    int64_t value = 0;
    IMV_GetIntFeatureMax(handle, name, &value);
    return value;
}

int64_t intFeatureInc(IMV_HANDLE handle, const char* name)
{
    int64_t value = 1;
    IMV_GetIntFeatureInc(handle, name, &value);
    return value == 0 ? 1 : value;
}

} // namespace

CameraController::CameraController(QObject* parent) : QObject(parent) {}

CameraController::~CameraController() = default;

bool CameraController::setEnumFeature(IMV_HANDLE handle, const char* name, const QString& value)
{
    if (!IMV_FeatureIsAvailable(handle, name))
    {
        emit logMessage(QStringLiteral("Skip %1: not available").arg(name));
        return false;
    }
    const QByteArray raw = value.toLatin1();
    const int ret = IMV_SetEnumFeatureSymbol(handle, name, raw.constData());
    if (ret != IMV_OK)
    {
        emit logMessage(QStringLiteral("Skip %1: SDK error code %2").arg(name).arg(ret));
        return false;
    }
    emit logMessage(QStringLiteral("Set %1 = %2").arg(name, value));
    return true;
}

bool CameraController::setIntFeature(IMV_HANDLE handle, const char* name, int64_t value)
{
    if (!IMV_FeatureIsAvailable(handle, name))
    {
        emit logMessage(QStringLiteral("Skip %1: not available").arg(name));
        return false;
    }
    const int ret = IMV_SetIntFeatureValue(handle, name, value);
    if (ret != IMV_OK)
    {
        emit logMessage(QStringLiteral("Skip %1: SDK error code %2").arg(name).arg(ret));
        return false;
    }
    int64_t actual = value;
    IMV_GetIntFeatureValue(handle, name, &actual);
    emit logMessage(QStringLiteral("Set %1 = %2").arg(name).arg(actual));
    return true;
}

bool CameraController::setDoubleFeature(IMV_HANDLE handle, const char* name, double value)
{
    if (!IMV_FeatureIsAvailable(handle, name))
    {
        emit logMessage(QStringLiteral("Skip %1: not available").arg(name));
        return false;
    }
    const int ret = IMV_SetDoubleFeatureValue(handle, name, value);
    if (ret != IMV_OK)
    {
        emit logMessage(QStringLiteral("Skip %1: SDK error code %2").arg(name).arg(ret));
        return false;
    }
    double actual = value;
    IMV_GetDoubleFeatureValue(handle, name, &actual);
    emit logMessage(QStringLiteral("Set %1 = %2").arg(name).arg(actual, 0, 'f', 3));
    return true;
}

void CameraController::enumerateDevices()
{
    IMV_DeviceList deviceList;
    std::memset(&deviceList, 0, sizeof(deviceList));
    const int ret = IMV_EnumDevices(&deviceList, interfaceTypeAll);
    if (ret != IMV_OK)
    {
        emit errorOccurred(QStringLiteral("Enumerate devices failed, SDK error code: %1").arg(ret));
        return;
    }

    QStringList devices;
    for (unsigned int i = 0; i < deviceList.nDevNum; ++i)
    {
        const IMV_DeviceInfo& info = deviceList.pDevInfo[i];
        devices << QStringLiteral("%1: %2  %3  %4  %5")
                       .arg(i + 1)
                       .arg(cameraTypeName(info.nCameraType))
                       .arg(QString::fromLatin1(info.vendorName))
                       .arg(QString::fromLatin1(info.modelName))
                       .arg(QString::fromLatin1(info.serialNumber));
    }
    emit devicesEnumerated(devices);
}

bool CameraController::openCamera(const CaptureSettings& settings, IMV_HANDLE& handle, QString& error)
{
    handle = nullptr;

    IMV_DeviceList deviceList;
    std::memset(&deviceList, 0, sizeof(deviceList));
    int ret = IMV_EnumDevices(&deviceList, interfaceTypeAll);
    if (ret != IMV_OK)
    {
        error = QStringLiteral("Enumerate devices failed, SDK error code: %1").arg(ret);
        return false;
    }
    if (deviceList.nDevNum == 0)
    {
        error = QStringLiteral("No camera found. Check USB cable, power, and driver.");
        return false;
    }
    if (settings.cameraIndex < 1 || settings.cameraIndex > static_cast<int>(deviceList.nDevNum))
    {
        error = QStringLiteral("Camera index must be 1..%1").arg(deviceList.nDevNum);
        return false;
    }

    unsigned int indexZeroBased = static_cast<unsigned int>(settings.cameraIndex - 1);
    ret = IMV_CreateHandle(&handle, modeByIndex, &indexZeroBased);
    if (ret != IMV_OK)
    {
        error = QStringLiteral("Create camera handle failed, SDK error code: %1").arg(ret);
        handle = nullptr;
        return false;
    }
    ret = IMV_Open(handle);
    if (ret != IMV_OK)
    {
        error = QStringLiteral("Open camera failed, SDK error code: %1").arg(ret);
        IMV_DestroyHandle(handle);
        handle = nullptr;
        return false;
    }
    return true;
}

void CameraController::configureCamera(IMV_HANDLE handle, const CaptureSettings& settings)
{
    setEnumFeature(handle, "TriggerMode", QStringLiteral("Off"));
    setEnumFeature(handle, "PixelFormat", settings.pixelFormat);

    setIntFeature(handle, "OffsetX", 0);
    setIntFeature(handle, "OffsetY", 0);
    setIntFeature(handle, "Width", settings.width);
    setIntFeature(handle, "Height", settings.height);

    if (settings.centerRoi && IMV_FeatureIsAvailable(handle, "OffsetX"))
    {
        const int64_t inc = intFeatureInc(handle, "OffsetX");
        const int64_t centered = (intFeatureMax(handle, "OffsetX") / 2 / inc) * inc;
        setIntFeature(handle, "OffsetX", centered);
    }
    if (settings.centerRoi && IMV_FeatureIsAvailable(handle, "OffsetY"))
    {
        const int64_t inc = intFeatureInc(handle, "OffsetY");
        const int64_t centered = (intFeatureMax(handle, "OffsetY") / 2 / inc) * inc;
        setIntFeature(handle, "OffsetY", centered);
    }

    setDoubleFeature(handle, "ExposureTime", settings.exposureUs);
}

void CameraController::closeCamera(IMV_HANDLE handle)
{
    if (!handle)
        return;
    if (IMV_IsGrabbing(handle))
        IMV_StopGrabbing(handle);
    if (IMV_IsOpen(handle))
        IMV_Close(handle);
    IMV_DestroyHandle(handle);
}

QImage CameraController::toQImage(const IMV_Frame& frame) const
{
    const int width = static_cast<int>(frame.frameInfo.width);
    const int height = static_cast<int>(frame.frameInfo.height);
    if (width <= 0 || height <= 0 || frame.pData == nullptr)
        return QImage();

    // Preview path assumes Mono8 (one byte per pixel), matching the Python GUI.
    const QImage view(frame.pData, width, height, width, QImage::Format_Grayscale8);
    return view.copy(); // detach from SDK-owned buffer before the frame is released
}

void CameraController::startPreview(const CaptureSettings& settings)
{
    if (busy_.exchange(true))
    {
        emit errorOccurred(QStringLiteral("Camera is busy."));
        return;
    }

    stopPreview_ = false;
    IMV_HANDLE handle = nullptr;
    QString error;

    if (!openCamera(settings, handle, error))
    {
        busy_ = false;
        emit errorOccurred(error);
        return;
    }

    configureCamera(handle, settings);

    int ret = IMV_StartGrabbing(handle);
    if (ret != IMV_OK)
    {
        closeCamera(handle);
        busy_ = false;
        emit errorOccurred(QStringLiteral("Start grabbing failed, SDK error code: %1").arg(ret));
        return;
    }

    emit previewStarted();

    while (!stopPreview_)
    {
        IMV_Frame frame;
        std::memset(&frame, 0, sizeof(frame));
        ret = IMV_GetFrame(handle, &frame, 1000);
        if (ret != IMV_OK)
            continue;

        const QImage image = toQImage(frame);
        IMV_ReleaseFrame(handle, &frame);

        if (!image.isNull())
            emit previewFrame(image);

        QThread::msleep(20);
    }

    closeCamera(handle);
    busy_ = false;
    emit previewStopped();
}

QString CameraController::makeOutputDir(const CaptureSettings& settings) const
{
    QString base = settings.outputBaseDir;
    if (base.isEmpty())
        base = QStringLiteral("captures");

    QDir dir(base);
    if (settings.timestampDir && !settings.noSave)
    {
        const QString stamp = QDateTime::currentDateTime().toString("yyyyMMdd_HHmmss_zzz");
        const QString leaf = QStringLiteral("%1_%2x%3").arg(stamp).arg(settings.width).arg(settings.height);
        return QDir(dir.filePath(leaf)).absolutePath();
    }
    return dir.absolutePath();
}

IMV_ESaveFileType CameraController::saveTypeFromExt(const QString& ext)
{
    const QString e = ext.toLower();
    if (e == QLatin1String(".bmp"))
        return typeSaveBmp;
    if (e == QLatin1String(".jpg") || e == QLatin1String(".jpeg"))
        return typeSaveJpeg;
    if (e == QLatin1String(".png"))
        return typeSavePng;
    if (e == QLatin1String(".tif") || e == QLatin1String(".tiff"))
        return typeSaveTiff;
    return typeSaveBmp;
}

void CameraController::saveFrame(IMV_HANDLE handle, const IMV_Frame& frame, const QString& path,
                                 IMV_ESaveFileType saveType)
{
    IMV_SaveImageToFileParam param;
    std::memset(&param, 0, sizeof(param));

    const QByteArray rawPath = QDir::toNativeSeparators(path).toLocal8Bit();
    param.nWidth = frame.frameInfo.width;
    param.nHeight = frame.frameInfo.height;
    param.ePixelFormat = frame.frameInfo.pixelFormat;
    param.pSrcData = frame.pData;
    param.nSrcDataLen = frame.frameInfo.size;
    param.eImageType = saveType;
    param.pImagePath = const_cast<char*>(rawPath.constData());
    param.eBayerDemosaic = demosaicEdgeSensing;
    if (saveType == typeSaveJpeg)
        param.nQuality = 90;
    else if (saveType == typeSavePng)
        param.nQuality = 8;

    const int ret = IMV_SaveImageToFile(handle, &param);
    if (ret != IMV_OK)
        emit logMessage(QStringLiteral("Save image failed (%1), SDK error code: %2").arg(path).arg(ret));
}

void CameraController::runCapture(const CaptureSettings& settings)
{
    if (busy_.exchange(true))
    {
        emit errorOccurred(QStringLiteral("Camera is busy."));
        return;
    }

    stopCapture_ = false;
    IMV_HANDLE handle = nullptr;
    QString error;

    if (!openCamera(settings, handle, error))
    {
        busy_ = false;
        emit errorOccurred(error);
        return;
    }

    configureCamera(handle, settings);

    const IMV_ESaveFileType saveType = saveTypeFromExt(settings.ext);
    const QString outputDir = makeOutputDir(settings);
    if (!settings.noSave)
        QDir().mkpath(outputDir);

    int ret = IMV_StartGrabbing(handle);
    if (ret != IMV_OK)
    {
        closeCamera(handle);
        busy_ = false;
        emit errorOccurred(QStringLiteral("Start grabbing failed, SDK error code: %1").arg(ret));
        return;
    }

    emit captureStarted();
    emit logMessage(QStringLiteral("Capturing for %1 s ...").arg(settings.durationSeconds, 0, 'f', 3));

    std::vector<IMV_Frame> clonedFrames;
    int captured = 0;
    int saved = 0;

    QElapsedTimer timer;
    timer.start();
    const qint64 deadlineMs = static_cast<qint64>(settings.durationSeconds * 1000.0);

    while (timer.elapsed() < deadlineMs && !stopCapture_)
    {
        IMV_Frame frame;
        std::memset(&frame, 0, sizeof(frame));
        ret = IMV_GetFrame(handle, &frame, 1000);
        if (ret != IMV_OK)
            continue;

        ++captured;

        if (!settings.noSave)
        {
            if (settings.deferSave)
            {
                IMV_Frame clone;
                std::memset(&clone, 0, sizeof(clone));
                if (IMV_CloneFrame(handle, &frame, &clone) == IMV_OK)
                    clonedFrames.push_back(clone);
            }
            else
            {
                const QString path = QDir(outputDir).filePath(
                    QStringLiteral("%1_%2%3")
                        .arg(settings.prefix)
                        .arg(captured, 6, 10, QChar('0'))
                        .arg(settings.ext));
                saveFrame(handle, frame, path, saveType);
                ++saved;
            }
        }

        IMV_ReleaseFrame(handle, &frame);
    }

    const double elapsed = timer.elapsed() / 1000.0;
    const double fps = elapsed > 0.0 ? captured / elapsed : 0.0;

    if (IMV_IsGrabbing(handle))
        IMV_StopGrabbing(handle);

    if (settings.deferSave && !clonedFrames.empty())
    {
        for (size_t i = 0; i < clonedFrames.size(); ++i)
        {
            const QString path = QDir(outputDir).filePath(
                QStringLiteral("%1_%2%3")
                    .arg(settings.prefix)
                    .arg(static_cast<int>(i) + 1, 6, 10, QChar('0'))
                    .arg(settings.ext));
            saveFrame(handle, clonedFrames[i], path, saveType);
            ++saved;
        }
    }

    for (IMV_Frame& clone : clonedFrames)
        IMV_ReleaseFrame(handle, &clone);
    clonedFrames.clear();

    emit logMessage(QStringLiteral("Captured %1 frames in %2 s, capture FPS: %3")
                        .arg(captured)
                        .arg(elapsed, 0, 'f', 3)
                        .arg(fps, 0, 'f', 1));
    if (!settings.noSave)
        emit logMessage(QStringLiteral("Saved %1 frames to %2").arg(saved).arg(outputDir));

    closeCamera(handle);
    busy_ = false;
    emit captureFinished(settings.noSave ? QString() : outputDir, saved, fps);
}
