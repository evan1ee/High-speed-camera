#include "app_services.h"

namespace hsc {

AppServices::AppServices(CameraController* camera, QObject* parent)
    : QObject(parent), camera_(camera)
{
}

AppServices::~AppServices() = default;

void AppServices::publishReport(const InspectionReport& report)
{
    emit reportPublished(report);
}

void AppServices::log(const QString& message)
{
    emit logAppended(message);
}

void AppServices::registerFolderAnalyzer(const QString& id, const QString& name, FolderAnalyzerFn fn)
{
    analyzers_[id] = {name, std::move(fn)};
}

std::vector<std::pair<QString, QString>> AppServices::availableAnalyzers() const
{
    std::vector<std::pair<QString, QString>> list;
    for (const auto& kv : analyzers_) {
        list.push_back({kv.first, kv.second.first});
    }
    return list;
}

std::optional<InspectionReport> AppServices::runAnalyzer(const QString& id, const std::filesystem::path& folder,
                                                       std::function<void(int, int, const QString&)> progress)
{
    auto it = analyzers_.find(id);
    if (it == analyzers_.end()) return std::nullopt;
    return it->second.second(folder, progress);
}

} // namespace hsc
