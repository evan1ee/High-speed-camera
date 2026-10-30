#include <cassert>
#include <cmath>
#include <iostream>
#include <fstream>
#include <numeric>
#include <vector>
#include <filesystem>


#include "src/foundation/app_paths.h"
#include "src/foundation/bmp_io.h"
#include "src/foundation/calibration_store.h"
#include "src/foundation/reference_store.h"
#include "src/foundation/summary_calc.h"
#include "src/foundation/temporal_scanner.h"
#include "src/foundation/tls_fit.h"
#include "src/features/angle_block/measure_block.h"
#include "src/features/calibration/calibrate_scale.h"
#include "src/features/piston/piston_track.h"
#include "src/features/spray_angle/erf_edge.h"
#include "src/features/spray_angle/measure_angle.h"
#include "src/foundation/make_video.h"
#include "src/shell/feature_registry.h"
#include "src/shell/app_services.h"
#include "src/shell/ui_icons.h"
#include "src/shell/app_icon_fallback.h"
#include "src/features/calibration/calibration_dialog.h"
#include <memory>
#include <QApplication>
#include <QAbstractSpinBox>

using namespace hsc;




int g_pass = 0;
int g_fail = 0;

#define TEST_ASSERT(cond, msg) \
    do { \
        if (!(cond)) { \
            std::cerr << "  [FAIL] " << msg << " (" << __FILE__ << ":" << __LINE__ << ")\n"; \
            ++g_fail; \
        } else { \
            ++g_pass; \
        } \
    } while (0)

void test_bmp_io()
{
    std::cout << "[RUN] test_bmp_io\n";
    int w = 64, h = 48;
    std::vector<uint8_t> pixels(static_cast<size_t>(w) * h);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            pixels[static_cast<size_t>(y) * w + x] = static_cast<uint8_t>((y * 4 + x) % 256);
        }
    }

    std::filesystem::path top_down_path = "test_top_down.bmp";
    std::filesystem::path bottom_up_path = "test_bottom_up.bmp";

    TEST_ASSERT(saveGrayBmp(top_down_path, w, h, pixels.data(), false), "Save top-down BMP");
    TEST_ASSERT(saveGrayBmp(bottom_up_path, w, h, pixels.data(), true), "Save bottom-up BMP");

    int lw1, lh1, lw2, lh2;
    std::vector<uint8_t> lp1, lp2;

    TEST_ASSERT(loadGrayBmp(top_down_path, lw1, lh1, lp1), "Load top-down BMP");
    TEST_ASSERT(loadGrayBmp(bottom_up_path, lw2, lh2, lp2), "Load bottom-up BMP");

    TEST_ASSERT(lw1 == w && lh1 == h, "Top-down dimensions match");
    TEST_ASSERT(lw2 == w && lh2 == h, "Bottom-up dimensions match");

    TEST_ASSERT(lp1 == pixels, "Top-down pixels exact match");
    TEST_ASSERT(lp2 == pixels, "Bottom-up rows flipped to match memory layout");

    std::filesystem::remove(top_down_path);
    std::filesystem::remove(bottom_up_path);
}

void test_paths_and_stores()
{
    std::cout << "[RUN] test_paths_and_stores\n";
    TEST_ASSERT(safeLabel(" shot/01:test*? ") == "shot_01_test", "safeLabel sanitization");

    // Scale calibration store
    ScaleCalibration cal;
    cal.mm_per_px = 0.052341;
    cal.ref_mm = 5.0;
    cal.distance_px = 95.527;
    cal.image_width = 320;
    cal.image_height = 240;

    TEST_ASSERT(ScaleCalibrationStore::save(cal), "Save calibration store");
    auto loaded = ScaleCalibrationStore::load();
    TEST_ASSERT(loaded.has_value(), "Load calibration store");
    if (loaded) {
        TEST_ASSERT(std::abs(loaded->mm_per_px - 0.052341) < 1e-6, "mm_per_px parity");
        TEST_ASSERT(loaded->image_width == 320 && loaded->image_height == 240, "Calibration image size parity");
    }

    // Nozzle reference store
    NozzleReference ref = NozzleReferenceStore::buildFromTip(QPoint(305, 85), QPoint(305, 155), 0.052, 320, 240);
    TEST_ASSERT(ref.isValid(), "Nozzle reference valid");
    TEST_ASSERT(std::abs(ref.blue_a.y() - 120.0) < 1e-5, "Midpoint Y at 120");
    TEST_ASSERT(ref.blue_b.x() == 0.0, "Centerline intersects x=0");

    TEST_ASSERT(NozzleReferenceStore::save(ref), "Save reference store");
    auto loaded_ref = NozzleReferenceStore::load();
    TEST_ASSERT(loaded_ref.has_value(), "Load reference store");

    // Jet-in-rect check
    // Horizontal edges at y=118 and y=122 must be inside rect
    TEST_ASSERT(ref.jetInRect(0.0, 118.0, 0.0, 122.0), "Jet inside tolerance rect");
    // Diverging edges at y=50 and y=190 must be NG
    TEST_ASSERT(!ref.jetInRect(0.0, 50.0, 0.0, 190.0), "Jet outside tolerance rect");

    // Test environment override for user-writable rig paths
    {
        std::filesystem::path customData = "test_custom_data_dir";
        std::filesystem::path customSettings = "test_custom_settings_dir";
        qputenv("HSC_DATA_DIR", customData.string().c_str());
        qputenv("HSC_SETTINGS_DIR", customSettings.string().c_str());

        TEST_ASSERT(dataRoot() == std::filesystem::absolute(customData), "HSC_DATA_DIR environment override");
        TEST_ASSERT(settingsDir() == std::filesystem::absolute(customSettings), "HSC_SETTINGS_DIR environment override");

        qunsetenv("HSC_DATA_DIR");
        qunsetenv("HSC_SETTINGS_DIR");
        std::error_code ec;
        std::filesystem::remove_all(customData, ec);
        std::filesystem::remove_all(customSettings, ec);
    }
}

void test_tls_and_ransac()
{
    std::cout << "[RUN] test_tls_and_ransac\n";

    // 1. Robust sigma
    std::vector<double> r = {0.1, -0.1, 0.2, -0.05, 0.0, 0.15, -0.2, 50.0}; // 50 is outlier
    double sigma = robustSigma(r);
    TEST_ASSERT(sigma < 1.0, "Robust sigma rejects huge outlier");

    // 2. Parabolic vertex
    double g[5] = {2.0, 8.0, 10.0, 6.0, 1.0};
    double off = parabolicVertexOffset(g, 2, 5);
    // a=8, b=10, c=6 => denom = 8 - 20 + 6 = -6 => off = 0.5 * (8-6)/(-6) = -1/6 = -0.1667
    TEST_ASSERT(std::abs(off - (-1.0 / 6.0)) < 1e-4, "Parabolic vertex offset accurate");

    // 3. TLS line fit on clean line y = 0.5*x + 10
    std::vector<std::pair<double, double>> pts;
    for (int x = 0; x < 20; ++x) {
        pts.push_back({static_cast<double>(x), 0.5 * x + 10.0});
    }
    auto line = tlsFit(pts);
    TEST_ASSERT(line.valid, "TLS line valid");
    TEST_ASSERT(std::abs(line.k - 0.5) < 1e-4, "TLS slope accurate");
    TEST_ASSERT(std::abs(line.b - 10.0) < 1e-4, "TLS intercept accurate");

    // 4. RANSAC with 5 huge outliers
    pts.push_back({5.0, 100.0});
    pts.push_back({10.0, -80.0});
    pts.push_back({15.0, 200.0});
    auto ransac_line = ransacTlsFit(pts, 2.5);
    TEST_ASSERT(ransac_line.valid, "RANSAC line valid");
    TEST_ASSERT(std::abs(ransac_line.k - 0.5) < 1e-3, "RANSAC recovers true slope despite outliers");

    // 5. Savitzky-Golay derivative on constant ramp y = 20 * t (dt = 0.1 => v = 20)
    std::vector<double> y_ramp(25);
    for (int i = 0; i < 25; ++i) y_ramp[i] = 20.0 * (i * 0.1);
    auto dy = savgolDerivative15(y_ramp, 0.1);
    for (size_t i = 7; i < 18; ++i) {
        TEST_ASSERT(std::abs(dy[i] - 20.0) < 1e-3, "Savitzky-Golay derivative recovers exact velocity");
    }
}

void test_erf_edge_model()
{
    std::cout << "[RUN] test_erf_edge_model\n";
    // Construct synthetic erf blurred step at mu=12.35
    std::vector<double> seg(25);
    double mu_true = 12.35;
    double sigma_true = 1.2;
    double base_true = 15.0;
    double amp_true = 200.0;

    for (int i = 0; i < 25; ++i) {
        double z = (i - mu_true) / (sigma_true * std::sqrt(2.0));
        seg[i] = base_true + amp_true * 0.5 * (1.0 + std::erf(z));
    }

    auto res = fitErfEdge(seg, 12, 22, true);
    TEST_ASSERT(res.valid, "Erf fit valid");
    TEST_ASSERT(std::abs(res.subpixel_pos - mu_true) < 0.15, "Erf recovers subpixel position");
    TEST_ASSERT(res.confidence > 0.85, "High confidence for clean step");

    // Flat column failure test
    std::vector<double> flat(25, 20.0);
    auto res_flat = fitErfEdge(flat, 12, 20, true);
    TEST_ASSERT(!res_flat.valid, "Flat column rejected gracefully");
}

void test_synthetic_spray_wedge()
{
    std::cout << "[RUN] test_synthetic_spray_wedge\n";
    int w = 320, h = 240;
    std::vector<uint8_t> img(static_cast<size_t>(w) * h, 15);

    // Apex on right at (300, 120), jet length 270 px, half angle = 5 deg (total 10 deg)
    double half_ang_rad = 5.0 * 3.14159265358979323846 / 180.0;
    double k = std::tan(half_ang_rad);

    for (int x = 30; x <= 300; ++x) {
        double dist = 300 - x;
        double half_w = dist * k + 2.0;
        int y_top = static_cast<int>(std::round(120.0 - half_w));
        int y_bot = static_cast<int>(std::round(120.0 + half_w));

        for (int y = std::max(0, y_top); y <= std::min(h - 1, y_bot); ++y) {
            img[static_cast<size_t>(y) * w + x] = 230;
        }
    }

    SprayMeasureOptions opts;
    opts.draw_ref_lines = false;
    opts.use_erf = false;

    auto res = measureFrame(img.data(), w, h, nullptr, opts);
    TEST_ASSERT(res.valid, "Synthetic wedge measured successfully");
    TEST_ASSERT(std::abs(res.angle - 10.0) < 1.0, "Measured opening angle within 1.0 deg of ground truth");
    TEST_ASSERT(res.confidence_str == "High", "Clean synthetic wedge produces High confidence");
}

void test_piston_tracking_and_hydrodynamics()
{
    std::cout << "[RUN] test_piston_tracking_and_hydrodynamics\n";
    int w = 320, h = 240;

    // Simulate 30 frames of dark piston traveling down bright barrel
    std::vector<std::vector<uint8_t>> frames(30, std::vector<uint8_t>(static_cast<size_t>(w) * h, 20));

    // Barrel interior is rows 60..180 (bright, value 230)
    for (int i = 0; i < 30; ++i) {
        int piston_x = 50 + i * 4; // travels rightwards from x=50 to x=166
        for (int y = 60; y <= 180; ++y) {
            for (int x = 0; x < w; ++x) {
                if (x >= piston_x) {
                    frames[i][static_cast<size_t>(y) * w + x] = 10; // piston body is dark
                } else {
                    frames[i][static_cast<size_t>(y) * w + x] = 230; // barrel is bright
                }
            }
        }
    }

    std::vector<const uint8_t*> ptrs(30);
    for (int i = 0; i < 30; ++i) ptrs[i] = frames[i].data();

    auto prof = buildBarrelProfile(ptrs, w, h);
    TEST_ASSERT(prof.valid, "Barrel profile built successfully");
    TEST_ASSERT(prof.y_top >= 60 && prof.y_bot <= 180, "Barrel row band correctly identified inside walls");

    std::vector<PistonFrameEdge> edges(30);
    for (int i = 0; i < 30; ++i) {
        edges[i] = measurePistonEdge(frames[i].data(), w, h, prof);
        TEST_ASSERT(edges[i].detected, "Piston edge detected on frame");
    }

    auto positions = applyCommonSlope(edges, h);
    TEST_ASSERT(positions.size() == 30, "Aligned positions count matches");
    TEST_ASSERT(positions.back() > positions.front() + 100.0, "Total stroke travel detected in px");

    // Hydrodynamic math check: D_barrel=6.12, D_orifice=0.155
    // Area ratio = (6.12/0.155)^2 = 1559.0
    // If v_piston = 100 mm/s => v_jet = 100 * 1559.0 * 1e-3 = 155.9 m/s
    // Stagnation pressure = 0.5 * 1000 * 155.9^2 * 1e-6 = 12.15 MPa
    double v_p = 100.0;
    double ratio = (6.12 * 6.12) / (0.155 * 0.155);
    double v_jet = v_p * ratio * 1e-3;
    double p_stag = 0.5 * 1000.0 * v_jet * v_jet * 1e-6;

    TEST_ASSERT(std::abs(v_jet - 155.90) < 0.2, "Jet exit speed formula parity");
    TEST_ASSERT(std::abs(p_stag - 12.15) < 0.2, "Stagnation pressure formula parity");
}

void test_temporal_motion_scanner()
{
    std::cout << "[RUN] test_temporal_motion_scanner\n";
    int w = 64, h = 48;
    int n = 20;
    std::vector<std::vector<uint8_t>> frames(n, std::vector<uint8_t>(static_cast<size_t>(w) * h, 50));

    // Inject motion at frame 10 (change half the image by 100)
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w / 2; ++x) {
            frames[10][static_cast<size_t>(y) * w + x] = 180;
        }
    }

    std::vector<const uint8_t*> ptrs(n);
    for (int i = 0; i < n; ++i) ptrs[i] = frames[i].data();

    auto signal = scanMotionSignalBuffers(ptrs, w, h, 25);
    TEST_ASSERT(signal.size() == static_cast<size_t>(n), "Signal size matches");
    TEST_ASSERT(signal[10] > 1000, "Spike at frame 10 recorded");
    TEST_ASSERT(signal[0] == 0 && signal[2] == 0, "Quiescent frames produce 0 signal");
}

void test_batch_summary_stats()
{
    std::cout << "[RUN] test_batch_summary_stats\n";
    std::vector<double> vals = {10.0, 12.0, 11.0, 9.0, 10.5};
    auto stats = computeStats(vals);

    TEST_ASSERT(stats.n == 5, "Count n=5");
    TEST_ASSERT(std::abs(stats.mean - 10.5) < 1e-4, "Mean = 10.5");
    TEST_ASSERT(stats.min == 9.0 && stats.max == 12.0, "Min/Max exact");
    TEST_ASSERT(stats.median == 10.5, "Median = 10.5");
    TEST_ASSERT(stats.cv_percent > 0.0, "CV% computed");
}

void test_savgol_smooth()
{
    std::cout << "[RUN] test_savgol_smooth\n";
    int n = 25;
    std::vector<double> y_noisy(n);
    for (int i = 0; i < n; ++i) {
        double noise = (i % 2 == 0) ? 1.5 : -1.5;
        y_noisy[i] = 3.0 * i + 10.0 + noise;
    }
    auto y_smooth = savgolSmooth21(y_noisy);
    TEST_ASSERT(y_smooth.size() == static_cast<size_t>(n), "Smoothed vector size matches");

    for (int i = 8; i < 17; ++i) {
        double expected = 3.0 * i + 10.0;
        TEST_ASSERT(std::abs(y_smooth[i] - expected) < 1.0, "Noise dampened by SG smooth");
    }

    std::vector<double> y_short(12);
    for (int i = 0; i < 12; ++i) y_short[i] = 2.0 * i + ((i % 2 == 0) ? 1.0 : -1.0);
    auto y_short_s = savgolSmooth21(y_short);
    TEST_ASSERT(y_short_s.size() == 12, "Adaptive smoothing on shorter span");
}

void test_timebase_resolution()
{
    std::cout << "[RUN] test_timebase_resolution\n";
    int n = 50;
    std::vector<double> us_stamps(n);
    for (int i = 0; i < n; ++i) {
        us_stamps[i] = 10000000.0 + i * 954.19847;
    }

    auto res = resolveTimebase(us_stamps, n, 1048.0, 0.05);
    TEST_ASSERT(res.verified, "Timebase inferred successfully");
    TEST_ASSERT(res.source_name.find("us") != std::string::npos, "Unit inferred as us");
    TEST_ASSERT(std::abs(res.implied_fps - 1048.0) < 1.0, "Implied FPS matches 1048");
    TEST_ASSERT(std::abs(res.times_s[0]) < 1e-9, "Normalized t0 is 0.0");
    TEST_ASSERT(std::abs(res.times_s.back() - (n - 1) / 1048.0) < 1e-4, "End time matches duration");

    std::vector<double> bad_stamps = {1.0, 2.0};
    auto fallback_res = resolveTimebase(bad_stamps, 50, 1000.0);
    TEST_ASSERT(!fallback_res.verified, "Mismatched size falls back gracefully");
    TEST_ASSERT(fallback_res.implied_fps == 1000.0, "Fallback FPS used");
}

void test_measure_angle_block()
{
    std::cout << "[RUN] test_measure_angle_block\n";
    int w = 200, h = 150;
    std::vector<uint8_t> img(static_cast<size_t>(w) * h, 30);

    double slope = std::tan(7.5 * 3.14159265358979323846 / 180.0);
    for (int x = 30; x < 180; ++x) {
        double dist = x - 30;
        double hw = dist * slope + 5.0;
        int y0 = static_cast<int>(std::round(75.0 - hw));
        int y1 = static_cast<int>(std::round(75.0 + hw));
        for (int y = std::max(0, y0); y <= std::min(h - 1, y1); ++y) {
            img[static_cast<size_t>(y) * w + x] = 220;
        }
    }

    auto res = measureAngleBlock(img.data(), w, h);
    TEST_ASSERT(res.valid, "Angle block detected via Otsu + component + RANSAC TLS");
    TEST_ASSERT(std::abs(res.angle_deg - 15.0) < 1.0, "Measured acute angle within 1.0 deg");
    TEST_ASSERT(res.line1.valid && res.line2.valid, "Both block boundary lines fitted");
}

void test_make_video_avi()
{
    std::cout << "[RUN] test_make_video_avi\n";
    auto tmp_dir = std::filesystem::temp_directory_path() / "hsc_avi_test";
    std::error_code ec;
    std::filesystem::create_directories(tmp_dir, ec);

    int w = 64, h = 48;
    std::vector<uint8_t> frame(static_cast<size_t>(w) * h, 100);

    for (int i = 0; i < 5; ++i) {
        frame[0] = static_cast<uint8_t>(i * 50);
        char name[64];
        std::snprintf(name, sizeof(name), "frame_%06d.bmp", i + 1);
        saveGrayBmp(tmp_dir / name, w, h, frame.data(), false);
    }

    auto out_avi = tmp_dir / "test.avi";
    QString err;
    bool ok = makeVideo(tmp_dir, out_avi, 15, &err);
    TEST_ASSERT(ok, "makeVideo succeeded");
    TEST_ASSERT(std::filesystem::exists(out_avi), "Output AVI file created");

    std::ifstream avi_file(out_avi, std::ios::binary);
    TEST_ASSERT(avi_file.good(), "AVI readable");
    char magic[12];
    avi_file.read(magic, 12);
    TEST_ASSERT(std::memcmp(magic, "RIFF", 4) == 0, "RIFF header magic");
    TEST_ASSERT(std::memcmp(magic + 8, "AVI ", 4) == 0, "AVI fourCC magic");

    avi_file.close();
    std::filesystem::remove_all(tmp_dir, ec);
}

void test_feature_registry()
{
    std::cout << "[RUN] test_feature_registry\n";
    const auto& mods = FeatureRegistry::instance().modules();
    TEST_ASSERT(!mods.empty(), "Registered modules present");

    auto* spray = FeatureRegistry::instance().findModule("spray_angle");
    TEST_ASSERT(spray != nullptr, "Spray Angle module registered");
    if (spray) {
        TEST_ASSERT(spray->title() == "Spray", "Spray module title matches");
        TEST_ASSERT(spray->usesCamera(), "Spray module uses camera");
    }

    auto* piston = FeatureRegistry::instance().findModule("piston");
    TEST_ASSERT(piston != nullptr, "Piston module registered");

    auto* gel = FeatureRegistry::instance().findModule("gel");
    TEST_ASSERT(gel != nullptr, "Gel module registered");

    auto* monitor = FeatureRegistry::instance().findModule("monitor");
    TEST_ASSERT(monitor != nullptr, "Monitor module registered");

    auto* summary = FeatureRegistry::instance().findModule("summary");
    TEST_ASSERT(summary != nullptr, "Summary module registered");

    auto setupTools = FeatureRegistry::instance().modulesByCategory(FeatureCategory::SetupTool);
    TEST_ASSERT(!setupTools.empty(), "Setup tools registered");
}

void test_app_icon()
{
    std::cout << "[RUN] test_app_icon\n";
    QIcon icon = getAppWindowIcon();
    TEST_ASSERT(!icon.isNull(), "Application window icon is not null");
    auto sizes = icon.availableSizes();
    TEST_ASSERT(!sizes.empty(), "Application icon has available resolutions");
    bool has_16 = false, has_24 = false, has_32 = false, has_48 = false, has_64 = false, has_128 = false, has_256 = false;
    for (const auto& sz : sizes) {
        if (sz.width() == 16 && sz.height() == 16) has_16 = true;
        if (sz.width() == 24 && sz.height() == 24) has_24 = true;
        if (sz.width() == 32 && sz.height() == 32) has_32 = true;
        if (sz.width() == 48 && sz.height() == 48) has_48 = true;
        if (sz.width() == 64 && sz.height() == 64) has_64 = true;
        if (sz.width() == 128 && sz.height() == 128) has_128 = true;
        if (sz.width() == 256 && sz.height() == 256) has_256 = true;
    }
    TEST_ASSERT(has_16, "Icon contains 16x16 resolution");
    TEST_ASSERT(has_24, "Icon contains 24x24 resolution");
    TEST_ASSERT(has_32, "Icon contains 32x32 resolution");
    TEST_ASSERT(has_48, "Icon contains 48x48 resolution");
    TEST_ASSERT(has_64, "Icon contains 64x64 resolution");
    TEST_ASSERT(has_128, "Icon contains 128x128 resolution");
    TEST_ASSERT(has_256, "Icon contains 256x256 resolution");

    // Pixmap render test
    QPixmap p16 = icon.pixmap(16, 16);
    TEST_ASSERT(!p16.isNull(), "16x16 pixmap renders valid");
    QPixmap p32 = icon.pixmap(32, 32);
    TEST_ASSERT(!p32.isNull(), "32x32 pixmap renders valid");
    QPixmap p256 = icon.pixmap(256, 256);
    TEST_ASSERT(!p256.isNull(), "256x256 pixmap renders valid");

    // Fallback embedded array test
    QImage fbImg;
    bool fbLoaded = fbImg.loadFromData(detail::kIcon_app_fallback, detail::kIcon_app_fallback_len);
    TEST_ASSERT(fbLoaded, "Embedded fallback byte array loads as valid image");
    TEST_ASSERT(fbImg.width() >= 128 && fbImg.height() >= 128, "Embedded fallback image has sufficient resolution");
}

void test_spinbox_no_buttons()
{
    std::cout << "[RUN] test_spinbox_no_buttons\n";

    AppServices services(nullptr);

    // 1. Spray feature module spinboxes
    auto* sprayModule = FeatureRegistry::instance().findModule("spray_angle");
    TEST_ASSERT(sprayModule != nullptr, "Spray angle module exists");
    if (sprayModule) {
        std::unique_ptr<QWidget> w(sprayModule->createWidget(services, nullptr));
        TEST_ASSERT(w != nullptr, "Spray angle widget created");
        auto spinBoxes = w->findChildren<QAbstractSpinBox*>();
        TEST_ASSERT(spinBoxes.size() >= 2, "Spray angle widget has at least 2 spinboxes (From/To)");
        for (auto* sb : spinBoxes) {
            TEST_ASSERT(sb->buttonSymbols() == QAbstractSpinBox::NoButtons,
                        "Spray angle spinbox has NoButtons stepper symbol");
        }
    }

    // 2. Piston feature module spinboxes
    auto* pistonModule = FeatureRegistry::instance().findModule("piston");
    TEST_ASSERT(pistonModule != nullptr, "Piston module exists");
    if (pistonModule) {
        std::unique_ptr<QWidget> w(pistonModule->createWidget(services, nullptr));
        TEST_ASSERT(w != nullptr, "Piston widget created");
        auto spinBoxes = w->findChildren<QAbstractSpinBox*>();
        TEST_ASSERT(spinBoxes.size() >= 3, "Piston widget has at least 3 spinboxes (Barrel/Orifice/FPS)");
        for (auto* sb : spinBoxes) {
            TEST_ASSERT(sb->buttonSymbols() == QAbstractSpinBox::NoButtons,
                        "Piston spinbox has NoButtons stepper symbol");
        }
    }

    // 3. Calibration feature module spinbox
    auto* calibModule = FeatureRegistry::instance().findModule("calibration");
    TEST_ASSERT(calibModule != nullptr, "Calibration module exists");
    if (calibModule) {
        std::unique_ptr<QWidget> w(calibModule->createWidget(services, nullptr));
        TEST_ASSERT(w != nullptr, "Calibration widget created");
        auto spinBoxes = w->findChildren<QAbstractSpinBox*>();
        TEST_ASSERT(spinBoxes.size() >= 1, "Calibration widget has at least 1 spinbox (thickness)");
        for (auto* sb : spinBoxes) {
            TEST_ASSERT(sb->buttonSymbols() == QAbstractSpinBox::NoButtons,
                        "Calibration spinbox has NoButtons stepper symbol");
        }
    }

    // 4. Calibration dialog spinbox
    {
        QImage dummy(100, 100, QImage::Format_Grayscale8);
        dummy.fill(0);
        CalibrationDialog dlg(dummy, 5.0);
        auto spinBoxes = dlg.findChildren<QAbstractSpinBox*>();
        TEST_ASSERT(spinBoxes.size() >= 1, "Calibration dialog has at least 1 spinbox (ref mm)");
        for (auto* sb : spinBoxes) {
            TEST_ASSERT(sb->buttonSymbols() == QAbstractSpinBox::NoButtons,
                        "Calibration dialog spinbox has NoButtons stepper symbol");
        }
        dlg.resize(800, 600);
        QPixmap pix = dlg.grab();
        pix.save("test_screen_calib_dialog.png");
    }

    // 5. Exhaustive check across ALL registered feature modules
    for (const auto& mod : FeatureRegistry::instance().modules()) {
        std::unique_ptr<QWidget> w(mod->createWidget(services, nullptr));
        if (w) {
            auto spinBoxes = w->findChildren<QAbstractSpinBox*>();
            for (auto* sb : spinBoxes) {
                TEST_ASSERT(sb->buttonSymbols() == QAbstractSpinBox::NoButtons,
                            "Every spinbox in all registered feature modules must have NoButtons stepper symbol");
            }
        }
    }
}

int main(int argc, char** argv)
{
    QApplication app(argc, argv);

    std::cout << "====================================================\n";
    std::cout << "Starting C++ Refactoring Test Suite (hsc_tests)\n";
    std::cout << "====================================================\n";

    test_bmp_io();
    test_paths_and_stores();
    test_tls_and_ransac();
    test_savgol_smooth();
    test_timebase_resolution();
    test_erf_edge_model();
    test_synthetic_spray_wedge();
    test_piston_tracking_and_hydrodynamics();
    test_measure_angle_block();
    test_temporal_motion_scanner();
    test_batch_summary_stats();
    test_make_video_avi();
    test_feature_registry();
    test_app_icon();
    test_spinbox_no_buttons();

    std::cout << "====================================================\n";
    std::cout << "Test Summary: " << g_pass << " PASSED, " << g_fail << " FAILED\n";
    std::cout << "====================================================\n";

    return (g_fail == 0) ? 0 : 1;
}

