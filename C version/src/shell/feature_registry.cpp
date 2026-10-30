#include "feature_registry.h"

#include <algorithm>

namespace hsc {

FeatureRegistry& FeatureRegistry::instance()
{
    static FeatureRegistry inst;
    return inst;
}

bool FeatureRegistry::registerModule(std::unique_ptr<IFeatureModule> module)
{
    if (!module) return false;
    modules_.push_back(std::move(module));
    std::sort(modules_.begin(), modules_.end(),
              [](const auto& a, const auto& b) {
                  return a->displayOrder() < b->displayOrder();
              });
    return true;
}

IFeatureModule* FeatureRegistry::findModule(const QString& id) const
{
    for (const auto& m : modules_) {
        if (m->id() == id) return m.get();
    }
    return nullptr;
}

std::vector<IFeatureModule*> FeatureRegistry::modulesByCategory(FeatureCategory category) const
{
    std::vector<IFeatureModule*> list;
    for (const auto& m : modules_) {
        if (m->category() == category) list.push_back(m.get());
    }
    return list;
}

void FeatureRegistry::clear()
{
    modules_.clear();
}

} // namespace hsc
