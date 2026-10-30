#pragma once

#include "i_feature_module.h"

#include <memory>
#include <vector>

namespace hsc {

class FeatureRegistry {
public:
    static FeatureRegistry& instance();

    bool registerModule(std::unique_ptr<IFeatureModule> module);
    const std::vector<std::unique_ptr<IFeatureModule>>& modules() const { return modules_; }
    IFeatureModule* findModule(const QString& id) const;
    std::vector<IFeatureModule*> modulesByCategory(FeatureCategory category) const;

    void clear();

private:
    FeatureRegistry() = default;
    std::vector<std::unique_ptr<IFeatureModule>> modules_;
};

} // namespace hsc

#define HSC_REGISTER_FEATURE(ModuleClass) \
    namespace { \
    struct FeatureModuleRegistrar { \
        FeatureModuleRegistrar() { \
            ::hsc::FeatureRegistry::instance().registerModule(std::make_unique<ModuleClass>()); \
        } \
    }; \
    static const FeatureModuleRegistrar s_feature_module_registrar; \
    }

