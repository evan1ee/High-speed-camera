#pragma once

#include <cstdint>
#include <filesystem>
#include <vector>

namespace hsc {

struct BmpHeader {
    uint32_t offset = 0;
    int32_t width = 0;
    int32_t height = 0; // absolute height
    int32_t raw_height = 0; // original signed height
    uint16_t bpp = 0;
    bool bottom_up = false;
};

// Reads header and orientation info from an 8-bit uncompressed BMP
bool readBmpHeader(const std::filesystem::path& path, BmpHeader& header);

// Loads 8-bit uncompressed BMP, flipping rows if stored bottom-up so rows are always top-to-bottom in memory
bool loadGrayBmp(const std::filesystem::path& path, int& width, int& height, std::vector<uint8_t>& pixels);

// Saves 8-bit uncompressed BMP with 256-entry grayscale palette
bool saveGrayBmp(const std::filesystem::path& path, int width, int height, const uint8_t* pixels, bool bottom_up = false);

} // namespace hsc
