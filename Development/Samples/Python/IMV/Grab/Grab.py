# -- coding: utf-8 --

import sys
import time
import threading

from ctypes import *

sys.path.append("../MVSDK")
from IMVApi import *

g_isRunThread = True

# 为线程定义一个函数
# Define a function for a thread
def frameGrabbingProc(cam):
    devHandle=cam.handle
    frame=IMV_Frame()
    if None==devHandle:
        return
    
    while g_isRunThread:
        nRet=cam.IMV_GetFrame(frame,500)
        if IMV_OK!=nRet:
            print("Get frame failed!ErrorCode[%d]" % nRet)
            continue
        print("Get frame blockId = [%d]"% frame.frameInfo.blockId)
        nRet=cam.IMV_ReleaseFrame(frame)
        if IMV_OK!=nRet:
            print("Release frame failed! ErrorCode[%d]" % nRet)

    return

def displayDeviceInfo(deviceInfoList):  
    print("Idx  Type   Vendor              Model           S/N    IP Address")
    print("-------------------------------------------------------------------")
    for i in range(0,deviceInfoList.nDevNum):
        pDeviceInfo=deviceInfoList.pDevInfo[i]
        strType=""
        strVendorName = pDeviceInfo.vendorName.decode("utf-8")
        strModeName = pDeviceInfo.modelName.decode("utf-8")
        strSerialNumber = pDeviceInfo.serialNumber.decode("utf-8")
        strIpAdress = pDeviceInfo.DeviceSpecificInfo.gigeDeviceInfo.ipAddress.decode("utf-8")
        if pDeviceInfo.nCameraType == typeGigeCamera:
            strType="Gige"
        elif pDeviceInfo.nCameraType == typeU3vCamera:
            strType="U3V"
        print ("[%d]  %s   %s    %s      %s           %s" % (i+1, strType,strVendorName,strModeName,strSerialNumber,strIpAdress))

if __name__ == "__main__":
    deviceList=IMV_DeviceList()
    interfaceType=IMV_EInterfaceType.interfaceTypeAll
    
    # 枚举设备
    # Enumerate device
    nRet=MvCamera.IMV_EnumDevices(deviceList,interfaceType)
    if IMV_OK != nRet:
        print("Enumeration devices failed! ErrorCode",nRet)
        sys.exit()
    if deviceList.nDevNum == 0:
        print ("find no device!")
        sys.exit()

    print("deviceList size is",deviceList.nDevNum)

    displayDeviceInfo(deviceList)

    nConnectionNum = input("Please input the camera index: ")

    if int(nConnectionNum) > deviceList.nDevNum:
        print ("intput error!")
        sys.exit()

    cam=MvCamera()
    # 创建设备句柄
    # Create device handle
    nRet=cam.IMV_CreateHandle(IMV_ECreateHandleMode.modeByIndex,byref(c_void_p(int(nConnectionNum)-1)))
    if IMV_OK != nRet:
        print("Create devHandle failed! ErrorCode",nRet)
        sys.exit()
        
    # 打开相机
    # Open the camera
    nRet=cam.IMV_Open()
    if IMV_OK != nRet:
        print("Open devHandle failed! ErrorCode",nRet)
        sys.exit()
      
    nRet = cam.IMV_SetEnumFeatureSymbol("TriggerMode", "Off")
    if IMV_OK != nRet:
        print("Set triggerMode value failed! ErrorCode[%d]" % nRet)
        sys.exit()

    # 开始拉流
    # Start grabbing
    nRet=cam.IMV_StartGrabbing()
    if IMV_OK != nRet:
        print("Start grabbing failed! ErrorCode",nRet)
        sys.exit()
    
    try:
        hThreadHandle = threading.Thread(target=frameGrabbingProc, args=(cam,))
        hThreadHandle.start()
    except:
        print ("error: unable to start thread")

    # 拉流2s
    # Get data for two seconds
    time.sleep(2)
    g_isRunThread=False
    hThreadHandle.join()

    # 停止拉流
    # Stop grabbing
    nRet=cam.IMV_StopGrabbing()
    if IMV_OK != nRet:
        print("Stop grabbing failed! ErrorCode",nRet)
        sys.exit()
    
    # 关闭相机
    # Close the camera
    nRet=cam.IMV_Close()
    if IMV_OK != nRet:
        print("Close camera failed! ErrorCode",nRet)
        sys.exit()
    
    # 销毁句柄
    # Destroy handle
    if(cam.handle):
        nRet=cam.IMV_DestroyHandle()
    
    print("---Demo end---")