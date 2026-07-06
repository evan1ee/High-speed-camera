# -- coding: utf-8 --

import sys
from ctypes import *
import datetime
import numpy
import cv2
import gc
import threading
import time

sys.path.append("../MVSDK")
from IMVApi import *

isGrab = True

def frameGrabbingProc(cam):
    devHandle=cam.handle
    frame=IMV_Frame()
    if None==devHandle:
        return
        
    while isGrab :
        # 主动取图
        # get frame actively
        frame = IMV_Frame()
        stPixelConvertParam=IMV_PixelConvertParam()

        nRet = cam.IMV_GetFrame(frame, 1000)
        
        if  IMV_OK != nRet :
            print("getFrame fail! Timeout:[1000]ms")
            continue
        else:
            print("getFrame success BlockId = [" + str(frame.frameInfo.blockId) + "], get frame time: " + str(datetime.datetime.now()))
          
        if  None==byref(frame) :
            print("pFrame is NULL!")
            continue
        # 给转码所需的参数赋值
        # Assign values to the parameters required for transcoding
        if IMV_EPixelType.gvspPixelMono8==frame.frameInfo.pixelFormat:
            nDstBufSize=frame.frameInfo.width * frame.frameInfo.height
        else:
            nDstBufSize=frame.frameInfo.width * frame.frameInfo.height*3
        
        pDstBuf=(c_ubyte*nDstBufSize)()
        memset(byref(stPixelConvertParam), 0, sizeof(stPixelConvertParam))
        
        stPixelConvertParam.nWidth = frame.frameInfo.width
        stPixelConvertParam.nHeight = frame.frameInfo.height
        stPixelConvertParam.ePixelFormat = frame.frameInfo.pixelFormat
        stPixelConvertParam.pSrcData = frame.pData
        stPixelConvertParam.nSrcDataLen = frame.frameInfo.size
        stPixelConvertParam.nPaddingX = frame.frameInfo.paddingX
        stPixelConvertParam.nPaddingY = frame.frameInfo.paddingY
        stPixelConvertParam.eBayerDemosaic = IMV_EBayerDemosaic.demosaicEdgeSensing
        stPixelConvertParam.eDstPixelFormat = frame.frameInfo.pixelFormat
        stPixelConvertParam.pDstBuf = pDstBuf
        stPixelConvertParam.nDstBufSize = nDstBufSize
        
        # 释放驱动图像缓存
        # release frame resource at the end of use
        
        nRet = cam.IMV_ReleaseFrame(frame)
        if IMV_OK != nRet:
            print("Release frame failed! ErrorCode[%d]\n", nRet)
            sys.exit()
        
        # 如果图像格式是 Mono8 直接使用
        # no format conversion required for Mono8
        if stPixelConvertParam.ePixelFormat == IMV_EPixelType.gvspPixelMono8:
            imageBuff=stPixelConvertParam.pSrcData
            userBuff = c_buffer(b'\0', stPixelConvertParam.nDstBufSize)
        
            memmove(userBuff,imageBuff,stPixelConvertParam.nDstBufSize)
            grayByteArray = bytearray(userBuff)
            
            cvImage = numpy.array(grayByteArray).reshape(stPixelConvertParam.nHeight, stPixelConvertParam.nWidth)
            
        else:
            # 转码 => BGR24
            # convert to BGR24
            stPixelConvertParam.eDstPixelFormat=IMV_EPixelType.gvspPixelBGR8
            #stPixelConvertParam.nDstBufSize=nDstBufSize

            nRet=cam.IMV_PixelConvert(stPixelConvertParam)
            if IMV_OK!=nRet:
                print("image convert to failed! ErrorCode[%d]" % nRet)
                del pDstBuf
                sys.exit()
            rgbBuff = c_buffer(b'\0', stPixelConvertParam.nDstBufSize)
            memmove(rgbBuff,stPixelConvertParam.pDstBuf,stPixelConvertParam.nDstBufSize)
            colorByteArray = bytearray(rgbBuff)
            cvImage = numpy.array(colorByteArray).reshape(stPixelConvertParam.nHeight, stPixelConvertParam.nWidth, 3)
            if None!=pDstBuf:
                del pDstBuf
            
         # --- end if ---
        cv2.imshow('myWindow', cvImage)
        gc.collect()
        
        if (cv2.waitKey(1) >= 0):
            return

def displayDeviceInfo(deviceInfoList):  
    print("Idx  Type   Vendor              Model           S/N    IP Address")
    print("-------------------------------------------------------------------")
    for i in range(0, deviceInfoList.nDevNum):
        pDeviceInfo = deviceInfoList.pDevInfo[i]
        strType = ""
        strVendorName = pDeviceInfo.vendorName.decode("utf-8")
        strModeName = pDeviceInfo.modelName.decode("utf-8")
        strSerialNumber = pDeviceInfo.serialNumber.decode("utf-8")
        strIpAdress = pDeviceInfo.DeviceSpecificInfo.gigeDeviceInfo.ipAddress.decode("utf-8")
        if pDeviceInfo.nCameraType == typeGigeCamera:
            strType = "Gige"
        elif pDeviceInfo.nCameraType == typeU3vCamera:
            strType = "U3V"
        print ("[%d]  %s   %s    %s      %s           %s" % (i+1, strType,strVendorName,strModeName,strSerialNumber,strIpAdress))

if __name__ == "__main__":
    deviceList=IMV_DeviceList()
    interfaceType=IMV_EInterfaceType.interfaceTypeAll
    nWidth=c_uint()
    nHeight=c_uint()

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
    
   # 通用属性设置:设置触发模式为off
   # General attribute settings: Set trigger mode to off
    nRet=IMV_OK
    nRet=cam.IMV_SetEnumFeatureSymbol("TriggerSource","Software")
    if IMV_OK != nRet:
        print("Set triggerSource value failed! ErrorCode[%d]" % nRet)
        sys.exit()
        
    nRet=cam.IMV_SetEnumFeatureSymbol("TriggerSelector","FrameStart")
    if IMV_OK != nRet:
        print("Set triggerSelector value failed! ErrorCode[%d]" % nRet)
        sys.exit()

    nRet=cam.IMV_SetEnumFeatureSymbol("TriggerMode","Off")
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
    isGrab=False
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