#include "gel_feature.h"
#include "src/shell/feature_registry.h"
#include "src/foundation/app_paths.h"
#include "src/foundation/bmp_io.h"
#include "src/foundation/make_video.h"
#include "src/foundation/temporal_scanner.h"

#include <QFileDialog>
#include <QGroupBox>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

namespace hsc {

GelFeatureModule::GelFeatureModule() = default;
GelFeatureModule::~GelFeatureModule() = default;

void GelFeatureModule::initialize(AppServices& services)
{
    services.registerFolderAnalyzer("gel", "Gel Injection Extraction",
        [](const std::filesystem::path& folder, std::function<void(int, int, const QString&)> progress) {
            auto signal = scanMotionSignalFolder(folder);
            int n = static_cast<int>(signal.size());

            InspectionReport r;
            r.featureId = "gel";
            r.runTitle = QString::fromStdString(folder.filename().string());
            r.outputFolder = QString::fromStdString(folder.string());
            r.valid = true;

            auto vid_path = folder / "slowmo.avi";
            if (!std::filesystem::exists(vid_path)) {
                makeVideo(folder, vid_path, 15);
            }
            r.videoPath = QString::fromStdString(vid_path.string());
            r.kpis.push_back({"Gel Injection", "Extracted", "Temporal Rule", BadgeStatus::PassGreen});
            r.kpis.push_back({"Frames", QString::number(n), "Extracted Window", BadgeStatus::Neutral});
            return r;
        });
}

QWidget* GelFeatureModule::createWidget(AppServices& services, QWidget* parent)
{
    auto* w = new QWidget(parent);
    auto* l = new QVBoxLayout(w);
    l->setContentsMargins(6, 6, 6, 6);

    auto* title = new QLabel(QObject::tr("🧊 Gel Injection Capture"), w);
    title->setStyleSheet("font-size: 15px; font-weight: bold; color: #202530;");
    l->addWidget(title);

    auto* note = new QLabel(
        QObject::tr("In ballistic gelatin, fluid accumulation and cavity expansion mean the scene never clears "
                    "back to baseline. The event end is detected when <b>frame-to-frame motion drops below noise</b> "
                    "(<code>end_rule=\"temporal\"</code>). Smart save is forced OFF."),
        w);
    note->setWordWrap(true);
    note->setStyleSheet("background: #eef9fa; border: 1px solid #b2ebf2; border-radius: 6px; padding: 10px; color: #006064;");
    l->addWidget(note);

    auto* offlineGroup = new QGroupBox(QObject::tr("Offline Re-Processing"), w);
    auto* offL = new QVBoxLayout(offlineGroup);
    auto* btnExtract = new QPushButton(QObject::tr("Extract Gel Injection Window..."), offlineGroup);
    auto* btnVideo = new QPushButton(QObject::tr("Generate Gel Slow-Mo Video..."), offlineGroup);
    offL->addWidget(btnExtract);
    offL->addWidget(btnVideo);
    l->addWidget(offlineGroup);

    QObject::connect(btnExtract, &QPushButton::clicked, [&services, parent]() {
        QString dir = QFileDialog::getExistingDirectory(parent, QObject::tr("Select Gel Burst Folder"));
        if (dir.isEmpty()) return;

        services.log(QObject::tr("Scanning motion in %1 with temporal end-rule...").arg(dir));
        auto rep = services.runAnalyzer("gel", dir.toStdString(), [](int cur, int tot, const QString& msg) {});
        if (rep && rep->valid) {
            services.publishReport(*rep);
            services.log(QObject::tr("Gel event processed for %1").arg(dir));
        }
    });

    QObject::connect(btnVideo, &QPushButton::clicked, [&services, parent]() {
        QString dir = QFileDialog::getExistingDirectory(parent, QObject::tr("Select Gel Folder to Make Video"));
        if (dir.isEmpty()) return;
        auto out_vid = std::filesystem::path(dir.toStdString()) / "slowmo.avi";
        if (makeVideo(dir.toStdString(), out_vid, 15)) {
            QMessageBox::information(parent, QObject::tr("Video Created"),
                                    QObject::tr("Saved: %1").arg(QString::fromStdString(out_vid.string())));
        }
    });

    l->addStretch();
    return w;
}

void GelFeatureModule::onPrimaryActionTriggered(AppServices& services)
{
    services.log("Gel capture requested.");
}

} // namespace hsc

HSC_REGISTER_FEATURE(::hsc::GelFeatureModule)
