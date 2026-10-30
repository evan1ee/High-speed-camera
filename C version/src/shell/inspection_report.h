#pragma once

#include <QString>
#include <vector>

namespace hsc {

enum class BadgeStatus {
    Neutral,
    PassGreen,
    WarnAmber,
    FailRed
};

struct KpiCard {
    QString label;    // e.g. "Spray Angle", "Peak Speed", "Pass/Fail"
    QString value;    // e.g. "0.42°", "165.2 mm/s", "PASS (OK)"
    QString subtext;  // e.g. "Trusted Mean (10 frames)", "In tolerance target"
    BadgeStatus status = BadgeStatus::Neutral;
};

struct PlotAttachment {
    QString title;     // e.g. "Displacement vs Time", "Speed vs Time"
    QString imagePath; // PNG chart path
};

struct InspectionReport {
    QString featureId;                 // "spray_angle", "piston", etc.
    QString runTitle;                  // "2026-08-12-14-15-00_320x240"
    QString outputFolder;              // Target folder for "Open Last Folder"
    QString csvPath;                   // Optional CSV report path
    QString videoPath;                 // Optional slowmo.avi path
    std::vector<KpiCard> kpis;         // Dynamic KPI banner cards
    std::vector<QString> framePaths;   // Dynamic frame sequence for scrubber
    std::vector<PlotAttachment> plots; // Dynamic curve plots
    bool valid = false;
};

} // namespace hsc
