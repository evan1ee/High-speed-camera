// injection_scan.cpp
// Fast motion-signal scanner for high-speed burst frames.
//
// Reads every .bmp frame in a folder, computes for each frame the number of
// pixels that changed by more than a threshold versus the previous frame,
// and writes the resulting signal to stdout as little-endian int32 values
// (one per frame, in filename order). Python does the (cheap) injection
// detection on that signal.
//
// Frames are processed in parallel chunks with OpenMP so that file I/O and
// the per-pixel diff are spread across CPU cores -- the big win on cold cache.
//
// Build (MinGW g++):
//   g++ -O3 -fopenmp -std=c++17 injection_scan.cpp -o injection_scan.exe
//
// Usage:
//   injection_scan.exe "<folder>" <diff_thresh>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#ifdef _OPENMP
#include <omp.h>
#endif

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace fs = std::filesystem;

struct BmpInfo {
    uint32_t offset = 0;
    int32_t width = 0;
    int32_t height = 0;   // stored value; negative means top-down
    uint16_t bpp = 0;
};

static bool read_header(const std::string& path, BmpInfo& info) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    unsigned char h[54];
    f.read(reinterpret_cast<char*>(h), 54);
    if (f.gcount() < 54) return false;
    if (h[0] != 'B' || h[1] != 'M') return false;
    std::memcpy(&info.offset, h + 10, 4);
    std::memcpy(&info.width, h + 18, 4);
    std::memcpy(&info.height, h + 22, 4);
    std::memcpy(&info.bpp, h + 28, 2);
    return true;
}

// Read the raw 8-bit pixel block (npix bytes at `offset`) into buf.
static bool read_pixels(const std::string& path, uint32_t offset, size_t npix,
                        std::vector<uint8_t>& buf) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    f.seekg(offset, std::ios::beg);
    buf.resize(npix);
    f.read(reinterpret_cast<char*>(buf.data()), static_cast<std::streamsize>(npix));
    return static_cast<size_t>(f.gcount()) == npix;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: injection_scan <folder> [diff_thresh]\n");
        return 2;
    }
    std::string folder = argv[1];
    int thresh = (argc >= 3) ? std::atoi(argv[2]) : 25;

#ifdef _WIN32
    // Write raw int32 to stdout without CR/LF translation.
    _setmode(_fileno(stdout), _O_BINARY);
#endif

    // Collect and sort .bmp files by name (zero-padded -> lexical == numeric).
    std::vector<std::string> files;
    std::error_code ec;
    for (auto& e : fs::directory_iterator(folder, ec)) {
        if (!e.is_regular_file()) continue;
        auto p = e.path();
        auto ext = p.extension().string();
        std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
        if (ext == ".bmp") files.push_back(p.string());
    }
    if (files.empty()) {
        std::fprintf(stderr, "no .bmp frames in %s\n", folder.c_str());
        return 3;
    }
    std::sort(files.begin(), files.end());

    BmpInfo info;
    if (!read_header(files[0], info) || info.bpp != 8) {
        std::fprintf(stderr, "unsupported BMP (need uncompressed 8-bit)\n");
        return 4;
    }
    const size_t npix =
        static_cast<size_t>(info.width) * static_cast<size_t>(std::abs(info.height));

    const int n = static_cast<int>(files.size());
    std::vector<int32_t> signal(n, 0);

    // Parallel over contiguous chunks. Each chunk loads its own frames plus the
    // one preceding frame so the diff at the chunk boundary stays correct.
    #pragma omp parallel
    {
        std::vector<uint8_t> prev, cur;
        #pragma omp for schedule(dynamic)
        for (int start = 1; start < n; start += 64) {
            int end = std::min(start + 64, n);
            if (!read_pixels(files[start - 1], info.offset, npix, prev)) continue;
            for (int i = start; i < end; ++i) {
                if (!read_pixels(files[i], info.offset, npix, cur)) {
                    prev.swap(cur);
                    continue;
                }
                int32_t count = 0;
                const uint8_t* a = cur.data();
                const uint8_t* b = prev.data();
                for (size_t k = 0; k < npix; ++k) {
                    int d = static_cast<int>(a[k]) - static_cast<int>(b[k]);
                    if (d < 0) d = -d;
                    if (d > thresh) ++count;
                }
                signal[i] = count;
                prev.swap(cur);
            }
        }
    }

    // Emit signal as little-endian int32, one per frame.
    std::fwrite(signal.data(), sizeof(int32_t), static_cast<size_t>(n), stdout);
    return 0;
}
