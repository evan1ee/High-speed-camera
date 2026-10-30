// C++ version of capture_image.py for Huaray/iRayple IMV SDK.
//
// Default behavior:
//   - Camera index: 1
//   - Aspect preset: 16:9 -> 576 x 324
//   - PixelFormat: Mono8
//   - ExposureTime: 1000 us
//   - Duration: 1 second
//   - Defer-save: clone frames during capture, then save after grabbing stops
//   - Timestamp output folder per run
//
// Build from a "x64 Native Tools Command Prompt for VS":
//   build_msvc.bat
//
// Run:
//   run_capture.bat
//
// Useful command line overrides:
//   capture_image_cpp.exe --aspect 320x240 --exposure-us 100 --duration 1
//   capture_image_cpp.exe --width 320 --height 240 --exposure-us 100
//   capture_image_cpp.exe --list

#include <IMVApi.h>

#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <ctime>
#include <vector>

namespace fs = std::filesystem;

struct Config
{
    bool listOnly = false;
    bool deferSave = true;
    bool timestampDir = true;
    bool noSave = false;
    unsigned int cameraIndexOneBased = 1;
    double durationSeconds = 1.0;
    std::string aspect = "16:9";
    unsigned int width = 0;
    unsigned int height = 0;
    bool manualSize = false;
    std::string pixelFormat = "Mono8";
    double exposureUs = 1000.0;
    bool setFrameRate = false;
    double frameRate = 0.0;
    std::string burstDir = "captures/burst_16x9_820fps_cpp";
    std::string ext = ".bmp";
    std::string prefix = "frame";
};

static const std::map<std::string, std::pair<unsigned int, unsigned int>> kAspectPresets = {
    {"1:1", {332, 332}},
    {"2:1", {664, 332}},
    {"4:3", {432, 324}},
    {"16:9", {576, 324}},
    {"320x240", {320, 240}},
};

static void check(int ret, const std::string& action)
{
    if (ret != IMV_OK)
    {
        std::ostringstream oss;
        oss << action << " failed, SDK error code: " << ret;
        throw std::runtime_error(oss.str());
    }
}

static bool featureAvailable(IMV_HANDLE handle, const char* name)
{
    return IMV_FeatureIsAvailable(handle, name);
}

static bool setEnumFeature(IMV_HANDLE handle, const char* name, const std::string& value, bool required = false)
{
    if (!featureAvailable(handle, name))
    {
        if (required)
            throw std::runtime_error(std::string("Feature is not available: ") + name);
        std::cout << "Skip " << name << ": not available\n";
        return false;
    }

    int ret = IMV_SetEnumFeatureSymbol(handle, name, value.c_str());
    if (ret != IMV_OK)
    {
        if (required)
            check(ret, std::string("Set ") + name);
        std::cout << "Skip " << name << ": SDK error code " << ret << "\n";
        return false;
    }

    std::cout << "Set " << name << " = " << value << "\n";
    return true;
}

static bool setIntFeature(IMV_HANDLE handle, const char* name, int64_t value, bool required = false)
{
    if (!featureAvailable(handle, name))
    {
        if (required)
            throw std::runtime_error(std::string("Feature is not available: ") + name);
        std::cout << "Skip " << name << ": not available\n";
        return false;
    }

    int ret = IMV_SetIntFeatureValue(handle, name, value);
    if (ret != IMV_OK)
    {
        if (required)
            check(ret, std::string("Set ") + name);
        std::cout << "Skip " << name << ": SDK error code " << ret << "\n";
        return false;
    }

    int64_t actual = 0;
    if (IMV_GetIntFeatureValue(handle, name, &actual) == IMV_OK)
        std::cout << "Set " << name << " = " << actual << "\n";
    else
        std::cout << "Set " << name << " = " << value << "\n";
    return true;
}

static bool setDoubleFeature(IMV_HANDLE handle, const char* name, double value, bool required = false)
{
    if (!featureAvailable(handle, name))
    {
        if (required)
            throw std::runtime_error(std::string("Feature is not available: ") + name);
        std::cout << "Skip " << name << ": not available\n";
        return false;
    }

    int ret = IMV_SetDoubleFeatureValue(handle, name, value);
    if (ret != IMV_OK)
    {
        if (required)
            check(ret, std::string("Set ") + name);
        std::cout << "Skip " << name << ": SDK error code " << ret << "\n";
        return false;
    }

    double actual = 0.0;
    if (IMV_GetDoubleFeatureValue(handle, name, &actual) == IMV_OK)
        std::cout << "Set " << name << " = " << std::fixed << std::setprecision(3) << actual << "\n";
    else
        std::cout << "Set " << name << " = " << value << "\n";
    return true;
}

static int64_t getIntFeatureMax(IMV_HANDLE handle, const char* name)
{
    int64_t value = 0;
    check(IMV_GetIntFeatureMax(handle, name, &value), std::string("Get ") + name + " max");
    return value;
}

static int64_t getIntFeatureInc(IMV_HANDLE handle, const char* name)
{
    int64_t value = 1;
    check(IMV_GetIntFeatureInc(handle, name, &value), std::string("Get ") + name + " inc");
    return value == 0 ? 1 : value;
}

static void printIntRange(IMV_HANDLE handle, const char* name)
{
    if (!featureAvailable(handle, name))
        return;

    int64_t value = 0;
    int64_t minValue = 0;
    int64_t maxValue = 0;
    int64_t incValue = 0;
    IMV_GetIntFeatureValue(handle, name, &value);
    IMV_GetIntFeatureMin(handle, name, &minValue);
    IMV_GetIntFeatureMax(handle, name, &maxValue);
    IMV_GetIntFeatureInc(handle, name, &incValue);
    std::cout << name << ": current=" << value << ", min=" << minValue
              << ", max=" << maxValue << ", inc=" << incValue << "\n";
}

static void printDoubleRange(IMV_HANDLE handle, const char* name)
{
    if (!featureAvailable(handle, name))
        return;

    double value = 0.0;
    double minValue = 0.0;
    double maxValue = 0.0;
    IMV_GetDoubleFeatureValue(handle, name, &value);
    IMV_GetDoubleFeatureMin(handle, name, &minValue);
    IMV_GetDoubleFeatureMax(handle, name, &maxValue);
    std::cout << name << ": current=" << std::fixed << std::setprecision(3) << value
              << ", min=" << minValue << ", max=" << maxValue << "\n";
}

static std::string cameraTypeName(IMV_ECameraType type)
{
    switch (type)
    {
    case typeGigeCamera:
        return "GigE";
    case typeU3vCamera:
        return "USB3/U3V";
    case typeCLCamera:
        return "CL";
    case typePCIeCamera:
        return "PCIe";
    default:
        return "Unknown";
    }
}

static void printDevices(const IMV_DeviceList& list)
{
    std::cout << "Index  Type      Vendor              Model              Serial\n";
    std::cout << "-----  --------  ------------------  -----------------  ----------------\n";
    for (unsigned int i = 0; i < list.nDevNum; ++i)
    {
        const IMV_DeviceInfo& info = list.pDevInfo[i];
        std::cout << std::left << std::setw(5) << (i + 1) << "  "
                  << std::setw(8) << cameraTypeName(info.nCameraType) << "  "
                  << std::setw(18) << info.vendorName << "  "
                  << std::setw(17) << info.modelName << "  "
                  << info.serialNumber << "\n";
    }
}

static IMV_ESaveFileType saveTypeFromExt(const std::string& ext)
{
    if (ext == ".bmp")
        return typeSaveBmp;
    if (ext == ".jpg" || ext == ".jpeg")
        return typeSaveJpeg;
    if (ext == ".png")
        return typeSavePng;
    if (ext == ".tif" || ext == ".tiff")
        return typeSaveTiff;
    throw std::runtime_error("Unsupported extension. Use .bmp, .jpg, .png, or .tif");
}

static std::string timestampString()
{
    const auto now = std::chrono::system_clock::now();
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;
    const std::time_t t = std::chrono::system_clock::to_time_t(now);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif

    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y%m%d_%H%M%S_") << std::setw(3) << std::setfill('0') << ms.count();
    return oss.str();
}

static fs::path makeOutputDir(const Config& cfg)
{
    fs::path dir(cfg.burstDir);
    if (cfg.timestampDir && !cfg.noSave)
    {
        std::string aspect = cfg.aspect;
        for (char& ch : aspect)
        {
            if (ch == ':')
                ch = 'x';
        }
        dir /= timestampString() + "_" + aspect + "_" + std::to_string(cfg.width) + "x" + std::to_string(cfg.height);
    }
    return fs::absolute(dir);
}

static fs::path makeFramePath(const fs::path& outputDir, const std::string& prefix, unsigned int frameNo, const std::string& ext)
{
    std::ostringstream name;
    name << prefix << "_" << std::setw(6) << std::setfill('0') << frameNo << ext;
    return outputDir / name.str();
}

static void saveFrame(IMV_HANDLE handle, const IMV_Frame& frame, const fs::path& outputPath, IMV_ESaveFileType saveType)
{
    IMV_SaveImageToFileParam param;
    std::memset(&param, 0, sizeof(param));

    const std::string path = outputPath.string();
    param.nWidth = frame.frameInfo.width;
    param.nHeight = frame.frameInfo.height;
    param.ePixelFormat = frame.frameInfo.pixelFormat;
    param.pSrcData = frame.pData;
    param.nSrcDataLen = frame.frameInfo.size;
    param.eImageType = saveType;
    param.pImagePath = const_cast<char*>(path.c_str());
    param.eBayerDemosaic = demosaicEdgeSensing;
    if (saveType == typeSaveJpeg)
        param.nQuality = 90;
    else if (saveType == typeSavePng)
        param.nQuality = 8;

    check(IMV_SaveImageToFile(handle, &param), "Save image");
}

static void configureCamera(IMV_HANDLE handle, Config& cfg)
{
    setEnumFeature(handle, "TriggerMode", "Off", true);
    setEnumFeature(handle, "PixelFormat", cfg.pixelFormat, false);

    setIntFeature(handle, "OffsetX", 0, false);
    setIntFeature(handle, "OffsetY", 0, false);
    setIntFeature(handle, "Width", cfg.width, true);
    setIntFeature(handle, "Height", cfg.height, true);

    if (featureAvailable(handle, "OffsetX"))
    {
        const int64_t inc = getIntFeatureInc(handle, "OffsetX");
        const int64_t centered = (getIntFeatureMax(handle, "OffsetX") / 2 / inc) * inc;
        setIntFeature(handle, "OffsetX", centered, false);
    }
    if (featureAvailable(handle, "OffsetY"))
    {
        const int64_t inc = getIntFeatureInc(handle, "OffsetY");
        const int64_t centered = (getIntFeatureMax(handle, "OffsetY") / 2 / inc) * inc;
        setIntFeature(handle, "OffsetY", centered, false);
    }

    setDoubleFeature(handle, "ExposureTime", cfg.exposureUs, false);
    if (cfg.setFrameRate)
    {
        setEnumFeature(handle, "AcquisitionFrameRateEnable", "On", false);
        setDoubleFeature(handle, "AcquisitionFrameRate", cfg.frameRate, false);
    }

    printIntRange(handle, "Width");
    printIntRange(handle, "Height");
    printIntRange(handle, "OffsetX");
    printIntRange(handle, "OffsetY");
    printDoubleRange(handle, "ExposureTime");
    printDoubleRange(handle, "AcquisitionFrameRate");
}

static Config parseArgs(int argc, char** argv)
{
    Config cfg;
    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        auto needValue = [&](const std::string& name) -> std::string {
            if (i + 1 >= argc)
                throw std::runtime_error("Missing value for " + name);
            return argv[++i];
        };

        if (arg == "--help" || arg == "-h")
        {
            std::cout
                << "Usage: capture_image_cpp.exe [options]\n"
                << "  --list\n"
                << "  --duration SECONDS\n"
                << "  --index CAMERA_INDEX_1_BASED\n"
                << "  --aspect 1:1|2:1|4:3|16:9|320x240\n"
                << "  --width PIXELS --height PIXELS\n"
                << "  --pixel-format Mono8\n"
                << "  --exposure-us MICROSECONDS\n"
                << "  --frame-rate FPS\n"
                << "  --burst-dir OUTPUT_BASE_DIR\n"
                << "  --ext .bmp|.png|.jpg|.tif\n"
                << "  --no-defer-save\n"
                << "  --no-timestamp-dir\n"
                << "  --no-save\n";
            std::exit(0);
        }
        else if (arg == "--list")
            cfg.listOnly = true;
        else if (arg == "--duration")
            cfg.durationSeconds = std::stod(needValue(arg));
        else if (arg == "--index")
            cfg.cameraIndexOneBased = static_cast<unsigned int>(std::stoul(needValue(arg)));
        else if (arg == "--aspect")
            cfg.aspect = needValue(arg);
        else if (arg == "--width")
        {
            cfg.width = static_cast<unsigned int>(std::stoul(needValue(arg)));
            cfg.manualSize = true;
        }
        else if (arg == "--height")
        {
            cfg.height = static_cast<unsigned int>(std::stoul(needValue(arg)));
            cfg.manualSize = true;
        }
        else if (arg == "--pixel-format")
            cfg.pixelFormat = needValue(arg);
        else if (arg == "--exposure-us")
            cfg.exposureUs = std::stod(needValue(arg));
        else if (arg == "--frame-rate")
        {
            cfg.frameRate = std::stod(needValue(arg));
            cfg.setFrameRate = true;
        }
        else if (arg == "--burst-dir")
            cfg.burstDir = needValue(arg);
        else if (arg == "--ext")
            cfg.ext = needValue(arg);
        else if (arg == "--prefix")
            cfg.prefix = needValue(arg);
        else if (arg == "--no-defer-save")
            cfg.deferSave = false;
        else if (arg == "--defer-save")
            cfg.deferSave = true;
        else if (arg == "--no-timestamp-dir")
            cfg.timestampDir = false;
        else if (arg == "--timestamp-dir")
            cfg.timestampDir = true;
        else if (arg == "--no-save")
            cfg.noSave = true;
        else
            throw std::runtime_error("Unknown argument: " + arg);
    }

    if (!cfg.manualSize)
    {
        const auto it = kAspectPresets.find(cfg.aspect);
        if (it == kAspectPresets.end())
            throw std::runtime_error("Unknown aspect preset: " + cfg.aspect);
        cfg.width = it->second.first;
        cfg.height = it->second.second;
    }
    else if (cfg.width == 0 || cfg.height == 0)
    {
        throw std::runtime_error("Manual ROI needs both --width and --height.");
    }

    if (cfg.ext.empty() || cfg.ext[0] != '.')
        cfg.ext = "." + cfg.ext;

    return cfg;
}

int main(int argc, char** argv)
{
    IMV_HANDLE handle = nullptr;
    std::vector<IMV_Frame> clonedFrames;

    try
    {
        Config cfg = parseArgs(argc, argv);

        IMV_DeviceList deviceList;
        std::memset(&deviceList, 0, sizeof(deviceList));
        check(IMV_EnumDevices(&deviceList, interfaceTypeAll), "Enumerate devices");

        if (deviceList.nDevNum == 0)
            throw std::runtime_error("No camera found. Check USB cable, power, and driver.");

        printDevices(deviceList);

        if (cfg.listOnly)
            return 0;

        if (cfg.cameraIndexOneBased < 1 || cfg.cameraIndexOneBased > deviceList.nDevNum)
            throw std::runtime_error("Camera index out of range.");

        unsigned int cameraIndexZeroBased = cfg.cameraIndexOneBased - 1;
        check(IMV_CreateHandle(&handle, modeByIndex, &cameraIndexZeroBased), "Create camera handle");
        check(IMV_Open(handle), "Open camera");

        configureCamera(handle, cfg);

        const IMV_ESaveFileType saveType = saveTypeFromExt(cfg.ext);
        const fs::path outputDir = makeOutputDir(cfg);
        if (!cfg.noSave)
            fs::create_directories(outputDir);

        check(IMV_StartGrabbing(handle), "Start grabbing");

        unsigned int captured = 0;
        unsigned int saved = 0;
        uint64_t firstBlockId = 0;
        uint64_t lastBlockId = 0;
        const auto start = std::chrono::steady_clock::now();
        const auto deadline = start + std::chrono::duration<double>(cfg.durationSeconds);

        while (std::chrono::steady_clock::now() < deadline)
        {
            IMV_Frame frame;
            std::memset(&frame, 0, sizeof(frame));
            const int ret = IMV_GetFrame(handle, &frame, 1000);
            if (ret != IMV_OK)
            {
                std::cout << "Get frame skipped, SDK error code: " << ret << "\n";
                continue;
            }

            ++captured;
            if (firstBlockId == 0)
                firstBlockId = frame.frameInfo.blockId;
            lastBlockId = frame.frameInfo.blockId;

            try
            {
                if (!cfg.noSave)
                {
                    if (cfg.deferSave)
                    {
                        IMV_Frame clone;
                        std::memset(&clone, 0, sizeof(clone));
                        check(IMV_CloneFrame(handle, &frame, &clone), "Clone frame");
                        clonedFrames.push_back(clone);
                    }
                    else
                    {
                        saveFrame(handle, frame, makeFramePath(outputDir, cfg.prefix, captured, cfg.ext), saveType);
                        ++saved;
                    }
                }
            }
            catch (...)
            {
                IMV_ReleaseFrame(handle, &frame);
                throw;
            }
            IMV_ReleaseFrame(handle, &frame);
        }

        const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        const double fps = elapsed > 0.0 ? captured / elapsed : 0.0;

        if (cfg.deferSave && !clonedFrames.empty())
        {
            if (IMV_IsGrabbing(handle))
                IMV_StopGrabbing(handle);

            const auto saveStart = std::chrono::steady_clock::now();
            for (unsigned int i = 0; i < clonedFrames.size(); ++i)
            {
                saveFrame(handle, clonedFrames[i], makeFramePath(outputDir, cfg.prefix, i + 1, cfg.ext), saveType);
                ++saved;
            }
            const auto saveElapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - saveStart).count();
            std::cout << "Captured " << captured << " frames in " << std::fixed << std::setprecision(3)
                      << elapsed << "s, capture FPS: " << std::setprecision(1) << fps << "\n";
            std::cout << "Saved " << saved << " cloned frames to " << outputDir.string()
                      << " in " << std::setprecision(3) << saveElapsed << "s\n";
        }
        else
        {
            std::cout << (cfg.noSave ? "Captured " : "Saved ") << captured << " frames";
            if (!cfg.noSave)
                std::cout << " to " << outputDir.string();
            std::cout << "\nElapsed: " << std::fixed << std::setprecision(3) << elapsed
                      << "s, effective " << (cfg.noSave ? "capture" : "saved")
                      << " FPS: " << std::setprecision(1) << fps << "\n";
        }

        if (firstBlockId != 0)
            std::cout << "BlockId: " << firstBlockId << ".." << lastBlockId << "\n";

        for (IMV_Frame& clone : clonedFrames)
            IMV_ReleaseFrame(handle, &clone);
        clonedFrames.clear();

        if (IMV_IsGrabbing(handle))
            IMV_StopGrabbing(handle);
        if (IMV_IsOpen(handle))
            IMV_Close(handle);
        IMV_DestroyHandle(handle);
        handle = nullptr;
        return 0;
    }
    catch (const std::exception& ex)
    {
        std::cerr << "ERROR: " << ex.what() << "\n";

        if (handle)
        {
            for (IMV_Frame& clone : clonedFrames)
                IMV_ReleaseFrame(handle, &clone);
            if (IMV_IsGrabbing(handle))
                IMV_StopGrabbing(handle);
            if (IMV_IsOpen(handle))
                IMV_Close(handle);
            IMV_DestroyHandle(handle);
        }
        return 1;
    }
}
