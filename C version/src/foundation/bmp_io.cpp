#include "bmp_io.h"

#include <cmath>
#include <cstring>
#include <fstream>

namespace hsc {

bool readBmpHeader(const std::filesystem::path& path, BmpHeader& header)
{
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;

    uint8_t h[54];
    f.read(reinterpret_cast<char*>(h), 54);
    if (f.gcount() < 54) return false;

    if (h[0] != 'B' || h[1] != 'M') return false;

    std::memcpy(&header.offset, h + 10, 4);
    std::memcpy(&header.width, h + 18, 4);
    std::memcpy(&header.raw_height, h + 22, 4);
    std::memcpy(&header.bpp, h + 28, 2);

    if (header.width <= 0 || header.raw_height == 0) return false;

    header.height = std::abs(header.raw_height);
    header.bottom_up = (header.raw_height > 0);

    return true;
}

bool loadGrayBmp(const std::filesystem::path& path, int& width, int& height, std::vector<uint8_t>& pixels)
{
    BmpHeader hdr;
    if (!readBmpHeader(path, hdr)) return false;
    if (hdr.bpp != 8) return false;

    std::ifstream f(path, std::ios::binary);
    if (!f) return false;

    f.seekg(hdr.offset, std::ios::beg);

    width = hdr.width;
    height = hdr.height;
    pixels.resize(static_cast<size_t>(width) * height);

    const size_t row_stride = (static_cast<size_t>(width) + 3) & ~size_t(3);
    std::vector<uint8_t> row_buf(row_stride);

    for (int r = 0; r < height; ++r) {
        f.read(reinterpret_cast<char*>(row_buf.data()), static_cast<std::streamsize>(row_stride));
        if (static_cast<size_t>(f.gcount()) < row_stride) return false;

        int dest_row = hdr.bottom_up ? (height - 1 - r) : r;
        uint8_t* dest_ptr = pixels.data() + static_cast<size_t>(dest_row) * width;
        std::memcpy(dest_ptr, row_buf.data(), width);
    }

    return true;
}

bool saveGrayBmp(const std::filesystem::path& path, int width, int height, const uint8_t* pixels, bool bottom_up)
{
    if (width <= 0 || height <= 0 || !pixels) return false;

    std::ofstream f(path, std::ios::binary | std::ios::trunc);
    if (!f) return false;

    const size_t row_stride = (static_cast<size_t>(width) + 3) & ~size_t(3);
    const uint32_t image_size = static_cast<uint32_t>(row_stride * height);
    const uint32_t file_size = 14 + 40 + 1024 + image_size;
    const uint32_t offset = 14 + 40 + 1024;

    uint8_t fh[14] = {0};
    fh[0] = 'B';
    fh[1] = 'M';
    std::memcpy(fh + 2, &file_size, 4);
    std::memcpy(fh + 10, &offset, 4);
    f.write(reinterpret_cast<const char*>(fh), 14);

    uint8_t ih[40] = {0};
    uint32_t biSize = 40;
    int32_t biWidth = width;
    int32_t biHeight = bottom_up ? height : -height;
    uint16_t biPlanes = 1;
    uint16_t biBitCount = 8;
    uint32_t biCompression = 0;
    uint32_t biClrUsed = 256;
    uint32_t biClrImportant = 256;

    std::memcpy(ih + 0, &biSize, 4);
    std::memcpy(ih + 4, &biWidth, 4);
    std::memcpy(ih + 8, &biHeight, 4);
    std::memcpy(ih + 12, &biPlanes, 2);
    std::memcpy(ih + 14, &biBitCount, 2);
    std::memcpy(ih + 16, &biCompression, 4);
    std::memcpy(ih + 20, &image_size, 4);
    std::memcpy(ih + 32, &biClrUsed, 4);
    std::memcpy(ih + 36, &biClrImportant, 4);
    f.write(reinterpret_cast<const char*>(ih), 40);

    // 256-entry grayscale palette (B, G, R, 0)
    uint8_t pal[1024];
    for (int i = 0; i < 256; ++i) {
        pal[i * 4 + 0] = static_cast<uint8_t>(i);
        pal[i * 4 + 1] = static_cast<uint8_t>(i);
        pal[i * 4 + 2] = static_cast<uint8_t>(i);
        pal[i * 4 + 3] = 0;
    }
    f.write(reinterpret_cast<const char*>(pal), 1024);

    std::vector<uint8_t> row_buf(row_stride, 0);
    for (int r = 0; r < height; ++r) {
        int src_row = bottom_up ? (height - 1 - r) : r;
        const uint8_t* src_ptr = pixels + static_cast<size_t>(src_row) * width;
        std::memcpy(row_buf.data(), src_ptr, width);
        f.write(reinterpret_cast<const char*>(row_buf.data()), static_cast<std::streamsize>(row_stride));
    }

    return f.good();
}

} // namespace hsc
