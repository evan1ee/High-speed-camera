#include "app_paths.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QRegularExpression>
#include <QStandardPaths>
#include <cstdlib>
#include <fstream>

namespace hsc {

static bool isPathWritable(const std::filesystem::path& dir)
{
    std::error_code ec;
    if (!std::filesystem::exists(dir, ec)) {
        if (!std::filesystem::create_directories(dir, ec)) {
            return false;
        }
    }
    auto probe = dir / ".hsc_write_probe";
    std::ofstream out(probe);
    if (!out) return false;
    out.close();
    std::filesystem::remove(probe, ec);
    return true;
}

QString safeLabel(const QString& label)
{
    QString s = label.trimmed();
    static const QRegularExpression invalidChars(QStringLiteral(R"([\\/:*?"<>|\s]+)"));
    s.replace(invalidChars, QStringLiteral("_"));
    while (s.startsWith('_')) s.remove(0, 1);
    while (s.endsWith('_')) s.chop(1);
    return s;
}

std::filesystem::path dataRoot()
{
    // 1. Explicit environment override
    if (qEnvironmentVariableIsSet("HSC_DATA_DIR")) {
        std::filesystem::path p = qEnvironmentVariable("HSC_DATA_DIR").toStdString();
        if (isPathWritable(p)) return std::filesystem::absolute(p);
    }

    // 2. Dev tree checks (existing data folders relative to CWD)
    std::filesystem::path p1 = "data";
    if (std::filesystem::exists(p1) && isPathWritable(p1)) return std::filesystem::absolute(p1);

    std::filesystem::path p2 = "../data";
    if (std::filesystem::exists(p2) && isPathWritable(p2)) return std::filesystem::absolute(p2);

    std::filesystem::path p3 = "../High speed camera/data";
    if (std::filesystem::exists(p3) && isPathWritable(p3)) return std::filesystem::absolute(p3);

    // 3. Application directory (e.g. C:\HighSpeedCamera\data)
    if (QCoreApplication::instance()) {
        std::filesystem::path appData = QCoreApplication::applicationDirPath().toStdString();
        appData /= "data";
        if (isPathWritable(appData)) {
            return std::filesystem::absolute(appData);
        }
    }

    // 4. User AppData fallback (guaranteed writable under non-admin operator accounts)
    QString qAppData = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    if (!qAppData.isEmpty()) {
        std::filesystem::path userPath = qAppData.toStdString();
        userPath /= "data";
        if (isPathWritable(userPath)) {
            return std::filesystem::absolute(userPath);
        }
    }

    // Default fallback
    std::error_code ec;
    std::filesystem::create_directories(p1, ec);
    return std::filesystem::absolute(p1);
}

std::filesystem::path settingsDir()
{
    // 1. Explicit environment override
    if (qEnvironmentVariableIsSet("HSC_SETTINGS_DIR")) {
        std::filesystem::path p = qEnvironmentVariable("HSC_SETTINGS_DIR").toStdString();
        if (isPathWritable(p)) return std::filesystem::absolute(p);
    }

    // 2. Dev tree checks
    std::filesystem::path s1 = "settings";
    if (std::filesystem::exists(s1) && isPathWritable(s1)) return std::filesystem::absolute(s1);

    std::filesystem::path s2 = "../settings";
    if (std::filesystem::exists(s2) && isPathWritable(s2)) return std::filesystem::absolute(s2);

    std::filesystem::path s3 = "../High speed camera/settings";
    if (std::filesystem::exists(s3) && isPathWritable(s3)) return std::filesystem::absolute(s3);

    // 3. Application directory (e.g. C:\HighSpeedCamera\settings)
    if (QCoreApplication::instance()) {
        std::filesystem::path appSettings = QCoreApplication::applicationDirPath().toStdString();
        appSettings /= "settings";
        if (isPathWritable(appSettings)) {
            return std::filesystem::absolute(appSettings);
        }
    }

    // 4. User AppData fallback
    QString qAppData = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    if (!qAppData.isEmpty()) {
        std::filesystem::path userSettings = qAppData.toStdString();
        userSettings /= "settings";
        if (isPathWritable(userSettings)) {
            return std::filesystem::absolute(userSettings);
        }
    }

    // Default fallback
    std::error_code ec;
    std::filesystem::create_directories(s1, ec);
    return std::filesystem::absolute(s1);
}

std::filesystem::path settingsPath(const QString& filename)
{
    return settingsDir() / filename.toStdString();
}

std::filesystem::path makeDestDir(const std::filesystem::path& baseDir, const QString& runName)
{
    std::filesystem::path dest = baseDir / runName.toStdString();
    std::error_code ec;
    std::filesystem::create_directories(dest, ec);
    return dest;
}

bool atomicWriteJson(const std::filesystem::path& path, const QByteArray& jsonData, QString* error)
{
    std::error_code ec;
    auto parent = path.parent_path();
    if (!parent.empty() && !std::filesystem::exists(parent, ec)) {
        std::filesystem::create_directories(parent, ec);
    }

    std::filesystem::path tmpPath = path;
    tmpPath += ".tmp";

    std::filesystem::path bakPath = path;
    bakPath += ".bak";

    {
        std::ofstream out(tmpPath, std::ios::binary | std::ios::trunc);
        if (!out) {
            if (error) *error = QString("Cannot open temp file for writing: %1").arg(QString::fromStdString(tmpPath.string()));
            return false;
        }
        out.write(jsonData.constData(), jsonData.size());
        if (!out.good()) {
            if (error) *error = QString("Error writing json data to %1").arg(QString::fromStdString(tmpPath.string()));
            return false;
        }
    }

    // Backup existing if exists
    if (std::filesystem::exists(path, ec)) {
        std::filesystem::copy_file(path, bakPath, std::filesystem::copy_options::overwrite_existing, ec);
    }

    // Atomic rename tmp -> path
    std::filesystem::rename(tmpPath, path, ec);
    if (ec) {
        if (error) *error = QString("Failed to rename %1 to %2: %3")
                                .arg(QString::fromStdString(tmpPath.string()))
                                .arg(QString::fromStdString(path.string()))
                                .arg(QString::fromStdString(ec.message()));
        return false;
    }

    return true;
}

} // namespace hsc
