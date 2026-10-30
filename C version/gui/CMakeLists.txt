cmake_minimum_required(VERSION 3.16)
project(capture_gui_qt LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

get_filename_component(SDK_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)

find_package(Qt6 REQUIRED COMPONENTS Widgets Gui Core)
find_package(OpenMP)

set(FOUNDATION_SOURCES
    ../src/foundation/app_paths.h
    ../src/foundation/app_paths.cpp
    ../src/foundation/bmp_io.h
    ../src/foundation/bmp_io.cpp
    ../src/foundation/calibration_store.h
    ../src/foundation/calibration_store.cpp
    ../src/foundation/reference_store.h
    ../src/foundation/reference_store.cpp
    ../src/foundation/tls_fit.h
    ../src/foundation/tls_fit.cpp
    ../src/foundation/temporal_scanner.h
    ../src/foundation/temporal_scanner.cpp
    ../src/foundation/summary_calc.h
    ../src/foundation/summary_calc.cpp
    ../src/foundation/make_video.h
    ../src/foundation/make_video.cpp
)

set(SHELL_SOURCES
    ../src/shell/inspection_report.h
    ../src/shell/pipeline_runner.h
    ../src/shell/pipeline_runner.cpp
    ../src/shell/app_services.h
    ../src/shell/app_services.cpp
    ../src/shell/i_feature_module.h
    ../src/shell/feature_registry.h
    ../src/shell/feature_registry.cpp
    ../src/shell/viewport_widget.h
    ../src/shell/viewport_widget.cpp
    ../src/shell/ui_icons.h
    ../src/shell/ui_icons.cpp
)

set(GUI_RESOURCES
    resources.qrc
)

set(GUI_WIN32_RESOURCES
    app_icon.rc
)

# Load modular feature slices (options: HSC_ENABLE_SPRAY_ANGLE, HSC_ENABLE_PISTON, etc.)
include(${CMAKE_CURRENT_LIST_DIR}/../src/features/CMakeLists.txt)

add_executable(capture_gui_qt WIN32
    main.cpp
    main_window.cpp
    main_window.h
    camera_controller.cpp
    camera_controller.h
    ${FOUNDATION_SOURCES}
    ${FEATURES_SOURCES}
    ${SHELL_SOURCES}
    ${GUI_RESOURCES}
    ${GUI_WIN32_RESOURCES}
)

target_include_directories(capture_gui_qt PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/.."
    "${CMAKE_CURRENT_LIST_DIR}"
    "${SDK_ROOT}/Development/Include/IMV"
)

target_link_directories(capture_gui_qt PRIVATE
    "${SDK_ROOT}/Development/Lib/x64"
)

target_link_libraries(capture_gui_qt PRIVATE
    Qt6::Widgets
    Qt6::Gui
    Qt6::Core
    MVSDKmd
)

if(OpenMP_CXX_FOUND)
    target_link_libraries(capture_gui_qt PRIVATE OpenMP::OpenMP_CXX)
endif()

if (MSVC)
    target_compile_options(capture_gui_qt PRIVATE /W4 /openmp)
endif()

add_custom_command(TARGET capture_gui_qt POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/app_icon.ico"
        "$<TARGET_FILE_DIR:capture_gui_qt>/app_icon.ico"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/app_icon.png"
        "$<TARGET_FILE_DIR:capture_gui_qt>/app_icon.png"
)

# Verification Test Suite target
add_executable(hsc_tests
    ../tests/test_main.cpp
    ${FOUNDATION_SOURCES}
    ${FEATURES_SOURCES}
    ${SHELL_SOURCES}
    ${GUI_RESOURCES}
)

target_include_directories(hsc_tests PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/.."
    "${CMAKE_CURRENT_LIST_DIR}"
)

target_link_libraries(hsc_tests PRIVATE
    Qt6::Widgets
    Qt6::Gui
    Qt6::Core
)

if(OpenMP_CXX_FOUND)
    target_link_libraries(hsc_tests PRIVATE OpenMP::OpenMP_CXX)
endif()

if (MSVC)
    target_compile_options(hsc_tests PRIVATE /W4 /openmp)
endif()
