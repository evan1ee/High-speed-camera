cmake_minimum_required(VERSION 3.16)
project(capture_image_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

get_filename_component(SDK_ROOT "${CMAKE_CURRENT_LIST_DIR}" ABSOLUTE)

add_executable(capture_image_cpp capture_image_cpp.cpp)
target_include_directories(capture_image_cpp PRIVATE
    "${SDK_ROOT}/Development/Include/IMV"
)
target_link_directories(capture_image_cpp PRIVATE
    "${SDK_ROOT}/Development/Lib/x64"
)
target_link_libraries(capture_image_cpp PRIVATE MVSDKmd)

if (MSVC)
    target_compile_options(capture_image_cpp PRIVATE /W4)
endif()
