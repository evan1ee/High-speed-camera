#pragma once

#include <QString>
#include <QStringList>
#include <filesystem>

namespace hsc {

// Path sanitization and directory helpers
QString safeLabel(const QString& label);
std::filesystem::path dataRoot();
std::filesystem::path settingsDir();
std::filesystem::path settingsPath(const QString& filename);
std::filesystem::path makeDestDir(const std::filesystem::path& baseDir, const QString& runName);

// Atomic JSON file save: writes to temp, backs up existing file to .bak, replaces atomically
bool atomicWriteJson(const std::filesystem::path& path, const QByteArray& jsonData, QString* error = nullptr);

} // namespace hsc
