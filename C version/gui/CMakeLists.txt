cmake_minimum_required(VERSION 3.16)
project(capture_gui_qt LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# SDK_ROOT points at the "C version" folder that now holds local copies of
# Development/ and Runtime/. gui/ -> "C version" (..).
get_filename_component(SDK_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)

find_package(Qt6 REQUIRED COMPONENTS Widgets)

add_executable(capture_gui_qt WIN32
    main.cpp
    main_window.cpp
    main_window.h
    camera_controller.cpp
    camera_controller.h
)

target_include_directories(capture_gui_qt PRIVATE
    "${SDK_ROOT}/Development/Include/IMV"
)
target_link_directories(capture_gui_qt PRIVATE
    "${SDK_ROOT}/Development/Lib/x64"
)
target_link_libraries(capture_gui_qt PRIVATE Qt6::Widgets MVSDKmd)

if (MSVC)
    target_compile_options(capture_gui_qt PRIVATE /W4)
endif()
