#pragma once

#include "inspection_report.h"
#include "pipeline_runner.h"

#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <vector>
#include <QObject>
#include <QString>

class CameraController;

namespace hsc {

using ::CameraController;

using FolderAnalyzerFn = std::function<InspectionReport(
    const std::filesystem::path& folder,
    std::function<void(int, int, const QString&)> progress)>;

class AppServices : public QObject {
    Q_OBJECT

public:
    explicit AppServices(CameraController* camera, QObject* parent = nullptr);
    ~AppServices() override;

    CameraController* camera() { return camera_; }
    PipelineRunner& pipeline() { return pipeline_; }

    void publishReport(const InspectionReport& report);
    void log(const QString& message);

    void registerFolderAnalyzer(const QString& id, const QString& name, FolderAnalyzerFn fn);
    std::vector<std::pair<QString, QString>> availableAnalyzers() const;
    std::optional<InspectionReport> runAnalyzer(const QString& id, const std::filesystem::path& folder,
                                              std::function<void(int, int, const QString&)> progress = nullptr);

signals:
    void reportPublished(const InspectionReport& report);
    void logAppended(const QString& message);

private:
    CameraController* camera_ = nullptr;
    PipelineRunner pipeline_;
    std::map<QString, std::pair<QString, FolderAnalyzerFn>> analyzers_;
};

} // namespace hsc
