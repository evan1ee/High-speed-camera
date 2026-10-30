#pragma once

#include <QIcon>
#include <QPixmap>
#include <QString>

namespace hsc {

// Generates crisp vector-drawn icons for sidebar navigation
QIcon getNavIcon(const QString& id);

// Generates tab icons for right workspace
QIcon getTabCameraIcon();
QIcon getTabInspectorIcon();

// Generates spray angle header concentric target icon
QPixmap getSprayHeaderIcon();

// Generates window application icon
QIcon getAppWindowIcon();

} // namespace hsc
