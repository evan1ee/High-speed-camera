#pragma once

#include "inspection_report.h"

#include <atomic>
#include <functional>
#include <memory>
#include <string>
#include <vector>
#include <QObject>
#include <QString>

namespace hsc {

struct PipelineStep {
    QString label;
    std::function<bool(std::atomic<bool>& cancel, std::function<void(int, int, const QString&)> progress)> execute;
};

class PipelineRunner : public QObject {
    Q_OBJECT

public:
    explicit PipelineRunner(QObject* parent = nullptr);
    ~PipelineRunner() override;

    void runChain(const QString& chainTitle, const std::vector<PipelineStep>& steps,
                  std::function<void(bool success)> onFinished = nullptr);

    void cancel();
    bool isRunning() const { return running_; }

signals:
    void stepStarted(int stepIndex, int totalSteps, const QString& stepLabel);
    void stepProgress(int current, int total, const QString& message);
    void chainFinished(bool success, double totalDurationSeconds);

private:
    std::atomic<bool> running_{false};
    std::atomic<bool> cancel_{false};
};

} // namespace hsc
