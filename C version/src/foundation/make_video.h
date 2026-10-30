#pragma once

#include <filesystem>
#include <vector>
#include <QString>

namespace hsc {

// Compiles BMP frames in source_dir into a slow-motion video (e.g. slowmo.avi or slowmo.mp4)
bool makeVideo(const std::filesystem::path& source_dir,
               const std::filesystem::path& output_file,
               int fps = 15,
               QString* error = nullptr);

} // namespace hsc
