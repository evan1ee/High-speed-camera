/// \file
/// \~chinese
/// \brief 帧数据转OpenCV示例
/// \example ToOpencvFormat.cpp
/// \~english
/// \brief frame data convert to OpenCV sample
/// \example ToOpencvFormat.cpp

//**********************************************************************
// 本Demo为简单演示SDK的使用，没有附加修改相机IP的代码，在运行之前，请使
// 用相机客户端修改相机IP地址的网段与主机的网段一致。                 
// This Demo shows how to use GenICam API(C) to write a simple program.
// Please make sure that the camera and PC are in the same subnet before running the demo.
// If not, you can use camera client software to modify the IP address of camera to the same subnet with PC. 
//**********************************************************************

#define _CRT_SECURE_NO_WARNINGS
#include <Windows.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "opencv2/core/core_c.h"
#include "opencv2/imgcodecs.hpp"
#include "opencv2/highgui.hpp"
#include "opencv2/imgproc.hpp"
#include "IMVApi.h"


// ***********开始： 这部分处理与SDK操作相机无关，用于显示设备列表 ***********
// ***********BEGIN: These functions are not related to API call and used to display device info***********
static void displayDeviceInfo(IMV_DeviceList deviceInfoList)
{
	IMV_DeviceInfo*	pDevInfo = NULL;
	unsigned int cameraIndex = 0;
	char vendorNameCat[11];
	char cameraNameCat[16];

	// 打印Title行 
	// Print title line 
	printf("\nIdx Type Vendor     Model      S/N             DeviceUserID    IP Address    \n");
	printf("------------------------------------------------------------------------------\n");

	for (cameraIndex = 0; cameraIndex < deviceInfoList.nDevNum; cameraIndex++)
	{
		pDevInfo = &deviceInfoList.pDevInfo[cameraIndex];
		// 设备列表的相机索引  最大表示字数：3
		// Camera index in device list, display in 3 characters 
		printf("%-3d", cameraIndex + 1);

		// 相机的设备类型（GigE，U3V，CL，PCIe）
		// Camera type 
		switch (pDevInfo->nCameraType)
		{
		case typeGigeCamera:printf(" GigE"); break;
		case typeU3vCamera:printf(" U3V "); break;
		case typeCLCamera:printf(" CL  "); break;
		case typePCIeCamera:printf(" PCIe"); break;
		default:printf("     "); break;
		}

		// 制造商信息  最大表示字数：10 
		// Camera vendor name, display in 10 characters 
		if (strlen(pDevInfo->vendorName) > 10)
		{
			memcpy(vendorNameCat, pDevInfo->vendorName, 7);
			vendorNameCat[7] = '\0';
			strcat(vendorNameCat, "...");
			printf(" %-10.10s", vendorNameCat);
		}
		else
		{
			printf(" %-10.10s", pDevInfo->vendorName);
		}

		// 相机的型号信息 最大表示字数：10 
		// Camera model name, display in 10 characters 
		printf(" %-10.10s", pDevInfo->modelName);

		// 相机的序列号 最大表示字数：15 
		// Camera serial number, display in 15 characters 
		printf(" %-15.15s", pDevInfo->serialNumber);

		// 自定义用户ID 最大表示字数：15 
		// Camera user id, display in 15 characters 
		if (strlen(pDevInfo->cameraName) > 15)
		{
			memcpy(cameraNameCat, pDevInfo->cameraName, 12);
			cameraNameCat[12] = '\0';
			strcat(cameraNameCat, "...");
			printf(" %-15.15s", cameraNameCat);
		}
		else
		{
			printf(" %-15.15s", pDevInfo->cameraName);
		}

		// GigE相机时获取IP地址 
		// IP address of GigE camera 
		if (pDevInfo->nCameraType == typeGigeCamera)
		{
			printf(" %s", pDevInfo->DeviceSpecificInfo.gigeDeviceInfo.ipAddress);
		}

		printf("\n");
	}

	return;
}

static char* trim(char* pStr)
{
	char* pDst = pStr;
	char* pTemStr = NULL;

	if (pDst != NULL)
	{
		pTemStr = pDst + strlen(pStr) - 1;
		while (*pDst == ' ')
		{
			pDst++;
		}
		while ((pTemStr > pDst) && (*pTemStr == ' '))
		{
			*pTemStr-- = '\0';
		}
	}

	return pDst;
}

static int isInputValid(char* pInpuStr)
{
	char numChar;
	char* pStr = pInpuStr;
	while (*pStr != '\0')
	{
		numChar = *pStr;
		if ((numChar > '9') || (numChar < '0'))
		{
			return -1;
		}
		pStr++;
	}

	return 0;
}

static unsigned int selectDevice(unsigned int cameraCnt)
{
	char inputStr[256];
	char* pTrimStr;
	int inputIndex = -1;
	int ret = -1;
	char* find = NULL;

	printf("\nPlease input the camera index: ");
	while (1)
	{
		memset(inputStr, 0, sizeof(inputStr));
		fgets(inputStr, sizeof(inputStr), stdin);
		// 清空输入缓存
		// clear flush
		fflush(stdin);

		// fgets比gets多吃一个换行符号，取出换行符号 
		// fgets eats one more line feed symbol than gets, and takes out the line feed symbol
		find = strchr(inputStr, '\n');
		if (find) { *find = '\0'; }

		pTrimStr = trim(inputStr);
		ret = isInputValid(pTrimStr);
		if (ret == 0)
		{
			inputIndex = atoi(pTrimStr);
			// 输入的序号从1开始 
			// Input index starts from 1 
			inputIndex -= 1;
			if ((inputIndex >= 0) && (inputIndex < (int)cameraCnt))
			{
				break;
			}
		}

		printf("Input invalid! Please input the camera index: ");
	}

	return (unsigned int)inputIndex;
}

// ***********结束： 这部分处理与SDK操作相机无关，用于显示设备列表 ***********
// ***********END: These functions are not related to API call and used to display device info***********

// 转换为Mat格式并保存图片 
// Convert to Mat format and save the image
bool Convert2Mat(IMV_HANDLE cam, IMV_Frame* frame)
{
	if (NULL == frame || NULL == frame->pData)
	{
		printf("NULL info or data.\n");
		return false;
	}

	cv::Mat srcImage;
	unsigned char* pDstData = NULL;

	if (gvspPixelMono8 == frame->frameInfo.pixelFormat)         
	{
		srcImage = cv::Mat(frame->frameInfo.height, frame->frameInfo.width, CV_8UC1, frame->pData);
	}
	else if (gvspPixelBGR8 == frame->frameInfo.pixelFormat)     
	{
		srcImage = cv::Mat(frame->frameInfo.height, frame->frameInfo.width, CV_8UC3, frame->pData);
	}
	// 其他彩色需要先转成BGR8
	// Other colors need to be converted to BGR8 first
	else
	{
		pDstData = (unsigned char*)malloc(frame->frameInfo.width * frame->frameInfo.height * 3);
		IMV_PixelConvertParam stPixelConvertParam = { 0 };
		stPixelConvertParam.nWidth = frame->frameInfo.width;
		stPixelConvertParam.nHeight = frame->frameInfo.height;
		stPixelConvertParam.ePixelFormat = frame->frameInfo.pixelFormat;
		stPixelConvertParam.pSrcData = frame->pData;
		stPixelConvertParam.nSrcDataLen = frame->frameInfo.size;
		stPixelConvertParam.nPaddingX = frame->frameInfo.paddingX;
		stPixelConvertParam.nPaddingY = frame->frameInfo.paddingY;
		stPixelConvertParam.eBayerDemosaic = demosaicEdgeSensing;
		stPixelConvertParam.eDstPixelFormat = gvspPixelBGR8;
		stPixelConvertParam.pDstBuf = pDstData;
		stPixelConvertParam.nDstBufSize = frame->frameInfo.width * frame->frameInfo.height * 3;
		int nRet = IMV_PixelConvert(cam, &stPixelConvertParam);
		if (nRet != IMV_OK)
		{
			printf("convert to BGR8 failed.\n");
			return false;
		}
		srcImage = cv::Mat(frame->frameInfo.height, frame->frameInfo.width, CV_8UC3, pDstData);
	}

	if (NULL == srcImage.data)
	{
		printf("Creat Mat failed.\n");
		return false;
	}

	try
	{
		cv::imwrite("MatImage.bmp", srcImage);
	}
	catch (cv::Exception& ex)
	{
		fprintf(stderr, "Exception in saving mat image: %s\n", ex.what());
	}

	srcImage.release();
	if (pDstData)
	{
		free(pDstData);
		pDstData = NULL;
	}
	return true;
}

// 转换为IplImage格式并保存图片
// Convert to IplImage format and save the image
bool Convert2Ipl(IMV_HANDLE cam, IMV_Frame* frame)
{
	if (NULL == frame || NULL == frame->pData)
	{
		printf("NULL info or data.\n");
		return false;
	}

	IplImage* srcImage = NULL;
	unsigned char* pDstData = NULL;

	if (gvspPixelMono8 == frame->frameInfo.pixelFormat)          
	{
		srcImage = cvCreateImage(cvSize(frame->frameInfo.width, frame->frameInfo.height), IPL_DEPTH_8U, 1);
		srcImage->imageData = (char *)frame->pData;
	}
	else if (gvspPixelBGR8 == frame->frameInfo.pixelFormat)     
	{
		srcImage = cvCreateImage(cvSize(frame->frameInfo.width, frame->frameInfo.height), IPL_DEPTH_8U, 3);
		srcImage->imageData = (char *)frame->pData;
	}
	// 其他彩色需要先转成BGR8
	// Other colors need to be converted to BGR8 first
	else 
	{
		pDstData = (unsigned char*)malloc(frame->frameInfo.width * frame->frameInfo.height * 3);
		IMV_PixelConvertParam stPixelConvertParam = { 0 };
		stPixelConvertParam.nWidth = frame->frameInfo.width;
		stPixelConvertParam.nHeight = frame->frameInfo.height;
		stPixelConvertParam.ePixelFormat = frame->frameInfo.pixelFormat;
		stPixelConvertParam.pSrcData = frame->pData;
		stPixelConvertParam.nSrcDataLen = frame->frameInfo.size;
		stPixelConvertParam.nPaddingX = frame->frameInfo.paddingX;
		stPixelConvertParam.nPaddingY = frame->frameInfo.paddingY;
		stPixelConvertParam.eBayerDemosaic = demosaicEdgeSensing;
		stPixelConvertParam.eDstPixelFormat = gvspPixelBGR8;
		stPixelConvertParam.pDstBuf = pDstData;
		stPixelConvertParam.nDstBufSize = frame->frameInfo.width * frame->frameInfo.height * 3;
		int nRet = IMV_PixelConvert(cam, &stPixelConvertParam);
		if (nRet != IMV_OK)
		{
			printf("convert to BGR8 failed.\n");
			return false;
		}
		srcImage = cvCreateImage(cvSize(frame->frameInfo.width, frame->frameInfo.height), IPL_DEPTH_8U, 3);
		srcImage->imageData = (char *)pDstData;

	}

	if (NULL == srcImage)
	{
		printf("Creat IplImage failed.\n");
		return false;
	}

	try
	{
		cv::Mat cConvertImage = cv::cvarrToMat(srcImage);
		cv::imwrite("IplImage.bmp", cConvertImage);

		cConvertImage.release();
	}
	catch (cv::Exception& ex)
	{
		fprintf(stderr, "Exception in saving IplImage: %s\n", ex.what());
	}

	cvReleaseImage(&srcImage);
	if (pDstData)
	{
		free(pDstData);
		pDstData = NULL;
	}
	return true;
}

int main()
{
	int ret = IMV_OK;
	unsigned int cameraIndex = 0;
	IMV_HANDLE devHandle = NULL;
	HANDLE threadHandle = NULL;

	// 发现设备 
	// discover camera 
	IMV_DeviceList deviceInfoList;
	ret = IMV_EnumDevices(&deviceInfoList, interfaceTypeAll);
	if (IMV_OK != ret)
	{
		printf("Enumeration devices failed! ErrorCode[%d]\n", ret);
		getchar();
		return -1;
	}

	if (deviceInfoList.nDevNum < 1)
	{
		printf("no camera\n");
		getchar();
		return -1;
	}

	// 打印相机基本信息（序号,类型,制造商信息,型号,序列号,用户自定义ID,IP地址） 
	// Print camera info (Index, Type, Vendor, Model, Serial number, DeviceUserID, IP Address) 
	displayDeviceInfo(deviceInfoList);

	// 选择需要连接的相机 
	// Select one camera to connect to  
	cameraIndex = selectDevice(deviceInfoList.nDevNum);

	do
	{
		// 创建设备句柄
		// Create Device Handle
		ret = IMV_CreateHandle(&devHandle, modeByIndex, (void*)&cameraIndex);
		if (IMV_OK != ret)
		{
			printf("Create devHandle failed! ErrorCode[%d]\n", ret);
			break;
		}

		// 打开相机 
		// Connect to camera 
		ret = IMV_Open(devHandle);
		if (IMV_OK != ret)
		{
			printf("Open camera failed! ErrorCode[%d]\n", ret);
			break;
		}

		// 关闭触发模式
		// set triggermode off
		ret = IMV_SetEnumFeatureSymbol(devHandle, "TriggerMode", "Off");
		if (IMV_OK != ret)
		{
			printf("Set TriggerMode failed! ErrorCode[%d]\n", ret);
			break;
		}

		// 开始拉流 
		// Start grabbing 
		ret = IMV_StartGrabbing(devHandle);
		if (IMV_OK != ret)
		{
			printf("Start grabbing failed! ErrorCode[%d]\n", ret);
			break;
		}

		IMV_Frame frame;
		// 获取一帧图像
		// Get a frame image
		ret = IMV_GetFrame(devHandle, &frame, 1000);
		if (IMV_OK != ret)
		{
			printf("Stop grabbing failed! ErrorCode[%d]\n", ret);
			break;
		}

		bool convertRes = Convert2Mat(devHandle, &frame);
		if (convertRes)
		{
			printf("convert to mat finished.\n");
		}
		else
		{
			printf("convert to mat failed.\n");
		}
		convertRes = Convert2Ipl(devHandle, &frame);
		if (convertRes)
		{
			printf("convert to Ipl finished.\n");
		}
		else
		{
			printf("convert to Ipl failed.\n");
		}

		// 释放图像缓存
		// Free image buffer
		ret = IMV_ReleaseFrame(devHandle, &frame);
		if (IMV_OK != ret)
		{
			printf("Release frame failed! ErrorCode[%d]\n", ret);
			break;
		}

		// 停止拉流 
		// Stop grabbing 
		ret = IMV_StopGrabbing(devHandle);
		if (IMV_OK != ret)
		{
			printf("Stop grabbing failed! ErrorCode[%d]\n", ret);
			break;
		}

		// 关闭相机
		// Close camera 
		ret = IMV_Close(devHandle);
		if (IMV_OK != ret)
		{
			printf("Close camera failed! ErrorCode[%d]\n", ret);
			break;
		}
	} while (false);

	if (devHandle != NULL)
	{
		// 销毁设备句柄
		// Destroy Device Handle
		IMV_DestroyHandle(devHandle);
	}

	printf("Press enter key to exit...\n");
	getchar();

	return 0;
}
