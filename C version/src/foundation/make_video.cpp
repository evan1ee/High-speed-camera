#include "make_video.h"
#include "bmp_io.h"

#include <algorithm>
#include <cstring>
#include <fstream>
#include <iostream>

namespace hsc {

// Helpers for RIFF AVI writing
static void write4(std::ofstream& f, const char* tag) { f.write(tag, 4); }
static void writeU32(std::ofstream& f, uint32_t val) { f.write(reinterpret_cast<const char*>(&val), 4); }
static void writeU16(std::ofstream& f, uint16_t val) { f.write(reinterpret_cast<const char*>(&val), 2); }

bool makeVideo(const std::filesystem::path& source_dir,
               const std::filesystem::path& output_file,
               int fps,
               QString* error)
{
    std::vector<std::filesystem::path> files;
    std::error_code ec;
    for (const auto& entry : std::filesystem::directory_iterator(source_dir, ec)) {
        if (!entry.is_regular_file()) continue;
        auto ext = entry.path().extension().string();
        std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
        if (ext == ".bmp") {
            files.push_back(entry.path());
        }
    }
    std::sort(files.begin(), files.end());

    if (files.empty()) {
        if (error) *error = "No .bmp files found in directory";
        return false;
    }

    BmpHeader first_hdr;
    if (!readBmpHeader(files[0], first_hdr)) {
        if (error) *error = "Cannot read first frame BMP header";
        return false;
    }

    int width = first_hdr.width;
    int height = first_hdr.height;
    int n_frames = static_cast<int>(files.size());
    size_t row_stride = (static_cast<size_t>(width) + 3) & ~size_t(3);
    uint32_t frame_bytes = static_cast<uint32_t>(row_stride * height + 1024); // 8-bit palette + pixels

    std::ofstream out(output_file, std::ios::binary | std::ios::trunc);
    if (!out) {
        if (error) *error = "Cannot open output video file";
        return false;
    }

    // Prepare palette (256-entry BGR0)
    uint8_t pal[1024];
    for (int i = 0; i < 256; ++i) {
        pal[i * 4 + 0] = static_cast<uint8_t>(i);
        pal[i * 4 + 1] = static_cast<uint8_t>(i);
        pal[i * 4 + 2] = static_cast<uint8_t>(i);
        pal[i * 4 + 3] = 0;
    }

    // RIFF AVI structure
    write4(out, "RIFF");
    auto riff_size_pos = out.tellp();
    writeU32(out, 0); // placeholder
    write4(out, "AVI ");

    // LIST 'hdrl'
    write4(out, "LIST");
    auto hdrl_size_pos = out.tellp();
    writeU32(out, 0); // placeholder
    write4(out, "hdrl");

    // 'avih'
    write4(out, "avih");
    writeU32(out, 56);
    uint32_t us_per_frame = 1000000 / std::max(1, fps);
    writeU32(out, us_per_frame); // dwMicroSecPerFrame
    writeU32(out, 0);            // dwMaxBytesPerSec
    writeU32(out, 0);            // dwPaddingGranularity
    writeU32(out, 0x10);         // dwFlags (AVIF_HASINDEX)
    writeU32(out, n_frames);     // dwTotalFrames
    writeU32(out, 0);            // dwInitialFrames
    writeU32(out, 1);            // dwStreams
    writeU32(out, frame_bytes);  // dwSuggestedBufferSize
    writeU32(out, width);        // dwWidth
    writeU32(out, height);       // dwHeight
    writeU32(out, 0); writeU32(out, 0); writeU32(out, 0); writeU32(out, 0); // reserved

    // LIST 'strl'
    write4(out, "LIST");
    auto strl_size_pos = out.tellp();
    writeU32(out, 0); // placeholder
    write4(out, "strl");

    // 'strh'
    write4(out, "strh");
    writeU32(out, 56);
    write4(out, "vids");
    write4(out, "DIB ");
    writeU32(out, 0);  // flags
    writeU16(out, 0);  // priority
    writeU16(out, 0);  // language
    writeU32(out, 0);  // initial frames
    writeU32(out, 1);  // scale
    writeU32(out, fps);// rate
    writeU32(out, 0);  // start
    writeU32(out, n_frames);
    writeU32(out, frame_bytes);
    writeU32(out, 0);  // quality
    writeU32(out, 0);  // sample size
    writeU16(out, 0); writeU16(out, 0); writeU16(out, static_cast<uint16_t>(width)); writeU16(out, static_cast<uint16_t>(height)); // rcFrame

    // 'strf' (BITMAPINFO)
    write4(out, "strf");
    writeU32(out, 40 + 1024);
    writeU32(out, 40); // biSize
    writeU32(out, width);
    writeU32(out, height); // positive: bottom-up DIB
    writeU16(out, 1);  // planes
    writeU16(out, 8);  // bitCount
    writeU32(out, 0);  // BI_RGB
    writeU32(out, static_cast<uint32_t>(row_stride * height));
    writeU32(out, 0); writeU32(out, 0);
    writeU32(out, 256); writeU32(out, 256);
    out.write(reinterpret_cast<const char*>(pal), 1024);

    // Patch strl size
    auto strl_end_pos = out.tellp();
    out.seekp(strl_size_pos);
    writeU32(out, static_cast<uint32_t>(strl_end_pos - strl_size_pos) - 4);
    out.seekp(strl_end_pos);

    // Patch hdrl size
    auto hdrl_end_pos = out.tellp();
    out.seekp(hdrl_size_pos);
    writeU32(out, static_cast<uint32_t>(hdrl_end_pos - hdrl_size_pos) - 4);
    out.seekp(hdrl_end_pos);

    // LIST 'movi'
    write4(out, "LIST");
    auto movi_size_pos = out.tellp();
    writeU32(out, 0); // placeholder
    write4(out, "movi");

    struct IndexEntry {
        uint32_t offset;
        uint32_t length;
    };
    std::vector<IndexEntry> index_entries;
    index_entries.reserve(n_frames);

    std::vector<uint8_t> frame_pixels;
    int w_in, h_in;

    for (int i = 0; i < n_frames; ++i) {
        if (!loadGrayBmp(files[i], w_in, h_in, frame_pixels) || w_in != width || h_in != height) {
            frame_pixels.assign(static_cast<size_t>(width) * height, 0);
        }

        uint32_t chunk_offset = static_cast<uint32_t>(out.tellp() - movi_size_pos) - 4;
        write4(out, "00db");
        uint32_t dib_bytes = static_cast<uint32_t>(row_stride * height);
        writeU32(out, dib_bytes);

        // Write bottom-up rows
        for (int r = height - 1; r >= 0; --r) {
            const uint8_t* row_src = frame_pixels.data() + static_cast<size_t>(r) * width;
            out.write(reinterpret_cast<const char*>(row_src), width);
            if (row_stride > static_cast<size_t>(width)) {
                uint8_t pad_zero[4] = {0};
                out.write(reinterpret_cast<const char*>(pad_zero), row_stride - width);
            }
        }

        // Align chunk to 2 bytes
        if (dib_bytes % 2 != 0) {
            uint8_t zero = 0;
            out.write(reinterpret_cast<const char*>(&zero), 1);
        }

        index_entries.push_back({chunk_offset, dib_bytes});
    }

    // Patch movi size
    auto movi_end_pos = out.tellp();
    out.seekp(movi_size_pos);
    writeU32(out, static_cast<uint32_t>(movi_end_pos - movi_size_pos) - 4);
    out.seekp(movi_end_pos);

    // 'idx1'
    write4(out, "idx1");
    writeU32(out, static_cast<uint32_t>(index_entries.size() * 16));
    for (const auto& ie : index_entries) {
        write4(out, "00db");
        writeU32(out, 0x10); // AVIIF_KEYFRAME
        writeU32(out, ie.offset);
        writeU32(out, ie.length);
    }

    // Patch RIFF size
    auto total_end = out.tellp();
    out.seekp(riff_size_pos);
    writeU32(out, static_cast<uint32_t>(total_end - riff_size_pos) - 4);

    return out.good();
}

} // namespace hsc
