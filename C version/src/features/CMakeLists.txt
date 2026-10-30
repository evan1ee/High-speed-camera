option(HSC_ENABLE_SPRAY_ANGLE "Enable Spray Angle Measurement module"     ON)
option(HSC_ENABLE_PISTON      "Enable Piston Speed & Tracking module"     ON)
option(HSC_ENABLE_GEL         "Enable Gel Injection Capture module"       ON)
option(HSC_ENABLE_MONITOR     "Enable Continuous Online Monitor module"   ON)
option(HSC_ENABLE_CALIBRATION "Enable Spatial Scale Calibration module"   ON)
option(HSC_ENABLE_REFERENCE   "Enable Nozzle Reference Alignment module"  ON)
option(HSC_ENABLE_ANGLE_BLOCK "Enable Angle Block Verification module"    ON)
option(HSC_ENABLE_SUMMARY     "Enable Cross-Run Batch Summary module"     ON)

set(FEATURES_SOURCES "")

if(HSC_ENABLE_SPRAY_ANGLE)
    list(APPEND FEATURES_SOURCES
        ${CMAKE_CURRENT_LIST_DIR}/spray_angle/erf_edge.h
        ${CMAKE_CURRENT_LIST_DIR}/spray_angle/erf_edge.cpp
        ${CMAKE_CURRENT_LIST_DIR}/spray_angle/measure_angle.h
        ${CMAKE_CURRENT_LIST_DIR}/spray_angle/measure_angle.cpp
        ${CMAKE_CURRENT_LIST_DIR}/spray_angle/smart_save.h
        ${CMAKE_CURRENT_LIST_DIR}/spray_angle/smart_save.cpp
        ${CMAKE_CURRENT_LIST_DIR}/spray_angle/spray_feature.h
        ${CMAKE_CURRENT_LIST_DIR}/spray_angle/spray_feature.cpp
    )
endif()

if(HSC_ENABLE_PISTON)
    list(APPEND FEATURES_SOURCES
        ${CMAKE_CURRENT_LIST_DIR}/piston/piston_track.h
        ${CMAKE_CURRENT_LIST_DIR}/piston/piston_track.cpp
        ${CMAKE_CURRENT_LIST_DIR}/piston/measure_piston.h
        ${CMAKE_CURRENT_LIST_DIR}/piston/measure_piston.cpp
        ${CMAKE_CURRENT_LIST_DIR}/piston/piston_plot.h
        ${CMAKE_CURRENT_LIST_DIR}/piston/piston_plot.cpp
        ${CMAKE_CURRENT_LIST_DIR}/piston/piston_feature.h
        ${CMAKE_CURRENT_LIST_DIR}/piston/piston_feature.cpp
    )
endif()

if(HSC_ENABLE_GEL)
    list(APPEND FEATURES_SOURCES
        ${CMAKE_CURRENT_LIST_DIR}/gel/gel_feature.h
        ${CMAKE_CURRENT_LIST_DIR}/gel/gel_feature.cpp
    )
endif()

if(HSC_ENABLE_MONITOR)
    list(APPEND FEATURES_SOURCES
        ${CMAKE_CURRENT_LIST_DIR}/monitor/monitor_engine.h
        ${CMAKE_CURRENT_LIST_DIR}/monitor/monitor_engine.cpp
        ${CMAKE_CURRENT_LIST_DIR}/monitor/event_writer.h
        ${CMAKE_CURRENT_LIST_DIR}/monitor/event_writer.cpp
        ${CMAKE_CURRENT_LIST_DIR}/monitor/monitor_feature.h
        ${CMAKE_CURRENT_LIST_DIR}/monitor/monitor_feature.cpp
    )
endif()

if(HSC_ENABLE_CALIBRATION)
    list(APPEND FEATURES_SOURCES
        ${CMAKE_CURRENT_LIST_DIR}/calibration/calibrate_scale.h
        ${CMAKE_CURRENT_LIST_DIR}/calibration/calibrate_scale.cpp
        ${CMAKE_CURRENT_LIST_DIR}/calibration/calibration_dialog.h
        ${CMAKE_CURRENT_LIST_DIR}/calibration/calibration_dialog.cpp
        ${CMAKE_CURRENT_LIST_DIR}/calibration/calibration_feature.h
        ${CMAKE_CURRENT_LIST_DIR}/calibration/calibration_feature.cpp
    )
endif()

if(HSC_ENABLE_REFERENCE)
    list(APPEND FEATURES_SOURCES
        ${CMAKE_CURRENT_LIST_DIR}/reference/reference_dialog.h
        ${CMAKE_CURRENT_LIST_DIR}/reference/reference_dialog.cpp
        ${CMAKE_CURRENT_LIST_DIR}/reference/reference_feature.h
        ${CMAKE_CURRENT_LIST_DIR}/reference/reference_feature.cpp
    )
endif()

if(HSC_ENABLE_ANGLE_BLOCK)
    list(APPEND FEATURES_SOURCES
        ${CMAKE_CURRENT_LIST_DIR}/angle_block/measure_block.h
        ${CMAKE_CURRENT_LIST_DIR}/angle_block/measure_block.cpp
        ${CMAKE_CURRENT_LIST_DIR}/angle_block/angle_block_feature.h
        ${CMAKE_CURRENT_LIST_DIR}/angle_block/angle_block_feature.cpp
    )
endif()

if(HSC_ENABLE_SUMMARY)
    list(APPEND FEATURES_SOURCES
        ${CMAKE_CURRENT_LIST_DIR}/summary/summary_feature.h
        ${CMAKE_CURRENT_LIST_DIR}/summary/summary_feature.cpp
    )
endif()
