#include "pipeline_runner.h"

#include <chrono>
#include <thread>
#include <QMetaObject>

namespace hsc {

PipelineRunner::PipelineRunner(QObject* parent) : QObject(parent)
{
}

PipelineRunner::~PipelineRunner()
{
    cancel();
}

void PipelineRunner::cancel()
{
    cancel_ = true;
}

void PipelineRunner::runChain(const QString& /*chainTitle*/, const std::vector<PipelineStep>& steps,
                             std::function<void(bool success)> onFinished)
{
    if (running_) return;

    running_ = true;
    cancel_ = false;

    std::thread([this, steps, onFinished]() {
        auto t_start = std::chrono::steady_clock::now();
        int total_steps = static_cast<int>(steps.size());
        bool success = true;

        for (int i = 0; i < total_steps; ++i) {
            if (cancel_) {
                success = false;
                break;
            }

            QMetaObject::invokeMethod(this, [this, i, total_steps, label = steps[i].label]() {
                emit stepStarted(i, total_steps, label);
            }, Qt::QueuedConnection);

            auto prog_fn = [this](int cur, int tot, const QString& msg) {
                QMetaObject::invokeMethod(this, [this, cur, tot, msg]() {
                    emit stepProgress(cur, tot, msg);
                }, Qt::QueuedConnection);
            };

            bool step_ok = steps[i].execute(cancel_, prog_fn);
            if (!step_ok || cancel_) {
                success = false;
                break;
            }
        }

        auto t_end = std::chrono::steady_clock::now();
        double duration = std::chrono::duration<double>(t_end - t_start).count();

        running_ = false;

        QMetaObject::invokeMethod(this, [this, success, duration, onFinished]() {
            emit chainFinished(success, duration);
            if (onFinished) onFinished(success);
        }, Qt::QueuedConnection);
    }).detach();
}

} // namespace hsc
