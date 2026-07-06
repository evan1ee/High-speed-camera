# -- coding: utf-8 --

import sys

sys.path.append("../MVSDK")
from IMVApi import *
import time

# ***********开始： 这部分处理与SDK操作相机无关，用于显示设备列表 ***********
# ***********BEGIN: These functions are not related to API call and used to display device info***********

def displayDeviceInfo(deviceInfoList):
    print("Idx  Type   Vendor              Model           S/N                 DeviceUserID    IP Address")
    print("------------------------------------------------------------------------------------------------")
    for i in range(0, deviceInfoList.nDevNum):
        pDeviceInfo = deviceInfoList.pDevInfo[i]
        strType = ""
        strVendorName = pDeviceInfo.vendorName.decode("utf-8")
        strModeName = pDeviceInfo.modelName.decode("utf-8")
        strSerialNumber = pDeviceInfo.serialNumber.decode("utf-8")
        strCameraname = pDeviceInfo.cameraName.decode("utf-8")
        strIpAdress = pDeviceInfo.DeviceSpecificInfo.gigeDeviceInfo.ipAddress.decode("utf-8")
        if pDeviceInfo.nCameraType == typeGigeCamera:
            strType = "Gige"
        elif pDeviceInfo.nCameraType == typeU3vCamera:
            strType = "U3V"
        print("[%d]  %s   %s    %s      %s     %s           %s" % (
        i + 1, strType, strVendorName, strModeName, strSerialNumber, strCameraname, strIpAdress))


def selectSaveFormat():
    print("--------------------------------------------")
    print("0.Save to BMP")
    print("1.Save to Jpeg")
    print("--------------------------------------------")
    inputstr = input("Please select the save format index: ")

    while True:
        if 0 <= int(inputstr) <= 3:
            break
        inputstr = input("Input invalid! Please select the save format index: ")

    if int(inputstr) == 0:
        print("select typeImageBmp", IMV_ESaveType.typeImageBmp)
        return IMV_ESaveType.typeImageBmp
    elif int(inputstr) == 1:
        print("select typeImageJpeg", IMV_ESaveType.typeImageJpeg)
        return IMV_ESaveType.typeImageJpeg
    else:
        print("select typeImageBmp", IMV_ESaveType.typeImageBmp)
        return IMV_ESaveType.typeImageBmp


def main():
    deviceList = IMV_DeviceList()
    interfaceType = IMV_EInterfaceType.interfaceTypeAll
    frame = IMV_Frame()

    # 枚举设备
    # Enumerate device
    nRet = MvCamera.IMV_EnumDevices(deviceList, interfaceType)
    if IMV_OK != nRet:
        print("Enumeration devices failed! ErrorCode", nRet)
        sys.exit()
    if deviceList.nDevNum == 0:
        print("find no device!")
        sys.exit()

    print("deviceList size is", deviceList.nDevNum)

    displayDeviceInfo(deviceList)

    nConnectionNum = input("Please input the camera index: ")

    if int(nConnectionNum) > deviceList.nDevNum:
        print("intput error!")
        sys.exit()

    cam = MvCamera()
    # 创建设备句柄
    # Create device handle
    nRet = cam.IMV_CreateHandle(IMV_ECreateHandleMode.modeByIndex, byref(c_void_p(int(nConnectionNum) - 1)))
    if IMV_OK != nRet:
        print("Create devHandle failed! ErrorCode", nRet)
        sys.exit()

    # 打开相机
    # Open the camera
    nRet = cam.IMV_Open()
    if IMV_OK != nRet:
        print("Open devHandle failed! ErrorCode", nRet)
        sys.exit()

    nRet = cam.IMV_SetEnumFeatureSymbol("TriggerMode", "Off")
    if IMV_OK != nRet:
        print("Set triggerMode value failed! ErrorCode[%d]" % nRet)
        sys.exit()

    # 开始拉流
    # Start grabbing
    nRet = cam.IMV_StartGrabbing()
    if IMV_OK != nRet:
        print("Start grabbing failed! ErrorCode", nRet)
        sys.exit()

    # 取一帧
    # Get one frame
    nRet = cam.IMV_GetFrame(frame, 500)
    if IMV_OK != nRet:
        print("Get frame failed!ErrorCode[%d]" % nRet)
        sys.exit()

    saveFormat = selectSaveFormat()
    saveImageParam = IMV_SaveImageParam()
    saveImageParam.eImageType = saveFormat
    saveImageParam.nWidth = frame.frameInfo.width
    saveImageParam.nHeight = frame.frameInfo.height
    saveImageParam.ePixelFormat = frame.frameInfo.pixelFormat
    saveImageParam.pSrcData = frame.pData
    saveImageParam.nSrcDataLen = frame.frameInfo.size
    saveImageParam.nBayerDemosaic = 2
    saveImageParam.nQuality = 90 
    saveImageParam.pDstBuf = (c_ubyte * (frame.frameInfo.width * frame.frameInfo.height * 4))()
    saveImageParam.nDstBufSize = frame.frameInfo.width * frame.frameInfo.height * 4

    print("start saveImage", saveImageParam.eImageType)
    nRet = cam.IMV_SaveImage(saveImageParam)
    if IMV_OK != nRet:
        print("IMV_SaveImage failed! ErrorCode", nRet)
        sys.exit()

    
    if sys.version_info.major == 2:
        pixel_bytes = ''.join(chr(i) for i in saveImageParam.pDstBuf[:saveImageParam.nDstDataLen])
    else:
        pixel_bytes = bytes(saveImageParam.pDstBuf[:saveImageParam.nDstDataLen])
    # 保存图像到文件
	# save image
    with open("Image." + ("bmp" if saveFormat == IMV_ESaveType.typeImageBmp else "jpg"), "wb+") as f:
        f.write(pixel_bytes)

    nRet = cam.IMV_ReleaseFrame(frame)
    if IMV_OK != nRet:
        print("IMV_ReleaseFrame failed! ErrorCode", nRet)
        sys.exit()

    # 停止拉流
    # Stop grabbing
    nRet = cam.IMV_StopGrabbing()
    if IMV_OK != nRet:
        print("Stop grabbing failed! ErrorCode", nRet)
        sys.exit()

    # 关闭相机
    # Close the camera
    nRet = cam.IMV_Close()
    if IMV_OK != nRet:
        print("Close camera failed! ErrorCode", nRet)
        sys.exit()

    # 销毁句柄
    # Destroy handle
    if (cam.handle):
        nRet = cam.IMV_DestroyHandle()

    print("---Demo end---")


if __name__ == "__main__":
    main()