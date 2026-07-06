/// \file
/// \~chinese
/// \brief 断线重连处理示例
/// \example ResumeConnect.cpp
/// \~english
/// \brief resume connect sample
/// \example ResumeConnect.cpp

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <Windows.h>
#include <process.h>
#include "IMVFGApi.h"
#include "IMVFGDefines.h"

static SYSTEMTIME sys;

typedef struct _User_Handle_Struct_
{
	IMV_FG_IF_HANDLE	ifHandle;
	IMV_FG_DEV_HANDLE	camHandle;
	std::string			camKey;
}UserHandleStruct;

static void onDeviceLinkNotify(const IMV_FG_SConnectArg* pConnectArg, void* pUser);

bool g_isMainThreadExit = false;

// 数据帧回调函数
// Data frame callback function
static void onGetFrame(IMV_FG_Frame* pFrame, void* pUser)
{
	IMV_FG_DEV_HANDLE camHandle = (IMV_FG_DEV_HANDLE)pUser;
	if (pFrame == NULL)
	{
		printf("pFrame is NULL\r\n");
		return;
	}

	printf("Get frame blockId = %llu timeStamp=%lld\r\n", pFrame->frameInfo.blockId, pFrame->frameInfo.timeStamp);

	return;
}

// 断线通知处理
// offLine notify processing
static void deviceOffLine(UserHandleStruct* userHandle)
{
	// 停止拉流 
	// Stop grabbing 
	IMV_FG_StopGrabbing(userHandle->ifHandle);

	return;
}

// 上线通知处理
// onLine notify processing
static void deviceOnLine(UserHandleStruct* userHandle)
{
	int ret = IMV_FG_OK;

	// 关闭相机
	// Close camera 
	IMV_FG_CloseDevice(userHandle->camHandle);

	do
	{
		if (g_isMainThreadExit)
		{
			return;
		}

		ret = IMV_FG_OpenDevice(IMV_FG_MODE_BY_CAMERAKEY, (void*)userHandle->camKey.c_str(), &userHandle->camHandle);
		if (IMV_FG_OK != ret)
		{
			printf("Retry open camera failed! ErrorCode[%d]\n", ret);
		}
		else
		{
			printf("Retry open camera successfully!\n");
			break;
		}

		Sleep(500);

	} while (true);

	printf("deviceOnLine if:[0x%p] dev:[0x%p] camKey[%s]\n", userHandle->ifHandle, userHandle->camHandle, userHandle->camKey.c_str());

	// 重新设备连接状态事件回调函数
	// Device connection status event callback function again
	ret = IMV_FG_SubscribeConnectArg(userHandle->camHandle, onDeviceLinkNotify, userHandle);
	if (IMV_FG_OK != ret)
	{
		printf("SubscribeConnectArg failed! ErrorCode[%d]\n", ret);
	}

	// 重新注册数据帧回调函数
	// Register data frame callback function again
	ret = IMV_FG_AttachGrabbing(userHandle->ifHandle, onGetFrame, userHandle->camHandle);
	if (IMV_FG_OK != ret)
	{
		printf("Attach grabbing failed! ErrorCode[%d]\n", ret);
	}

	printf("start grabbing\n");
	// 开始拉流 
	// Start grabbing 
	ret = IMV_FG_StartGrabbing(userHandle->ifHandle);
	if (IMV_FG_OK != ret)
	{
		printf("Start grabbing failed! ErrorCode[%d]\n", ret);
	}
	else
	{
		printf("Start grabbing successfully\n");
	}
}

// 连接事件通知回调函数
// Connect event notify callback function
static void onDeviceLinkNotify(const IMV_FG_SConnectArg* pConnectArg, void* pUser)
{
	UserHandleStruct userHandle = *((UserHandleStruct*)pUser);
	if (NULL == userHandle.ifHandle || NULL == userHandle.camHandle)
	{
		printf("userHandle if:[0x%p] dev:[0x%p] is NULL!", userHandle.ifHandle, userHandle.camHandle);
		return;
	}

	// 断线通知
	// offLine notify 
	if (IMV_FG_OFFLINE == pConnectArg->event)
	{
		printf("------cameraHandle[%s] : OffLine------\n", userHandle.camKey.c_str());
		deviceOffLine((UserHandleStruct*)pUser);
	}
	// 上线通知
	// onLine notify 
	else if (IMV_FG_ONLINE == pConnectArg->event)
	{
		printf("------cameraHandle[%s] : OnLine------\n", userHandle.camKey.c_str());
		deviceOnLine((UserHandleStruct*)pUser);
	}
}

#define STR_LEN 16
#define CAPTURECARD 0
#define CAM 1
// ***********开始： 这部分处理与SDK操作相机无关，用于显示设备列表 ***********
// ***********BEGIN: These functions are not related to API call and used to display device info***********
static void displayDeviceInfo(IMV_FG_INTERFACE_INFO_LIST interfaceInfoList, IMV_FG_DEVICE_INFO_LIST deviceInfoList)
{
	IMV_FG_DEVICE_INFO*	pDevInfo = NULL;
	unsigned int cameraIndex = 0;
	char strNameCat[STR_LEN] = { 0 };

	// 打印Title行 
	// Print title line 
	printf("nIdx  Type     Vendor          Model           S/N             DeviceUserID                \n");
	printf("-------------------------------------------------------------------------------------------\n");

	for (unsigned int index = 0; index < interfaceInfoList.nInterfaceNum; ++index)
	{
		// 设备列表的相机索引  最大表示字数：3
		// Camera index in device list, display in 3 characters 
		printf("%-3d", index + 1);

		// 接口类型（GigE，U3V，CL，PCIe）
		// Interface type 
		switch (interfaceInfoList.pInterfaceInfoList[index].nInterfaceType)
		{
		case typeGigEInterface:printf(" GigE Card  "); break;
		case typeU3vInterface:printf(" U3V Card  "); break;
		case typeCLInterface:printf(" CL Card  "); break;
		case typeCXPInterface:printf(" CXP Card  "); break;
		default:printf("     "); break;
		}

		// 制造商信息  最大表示字数：15 
		// Camera vendor name, display in 15 characters
		size_t strLen = STR_LEN;
		if (strlen(interfaceInfoList.pInterfaceInfoList[index].vendorName) > strLen - 4)
		{
			memcpy(strNameCat, interfaceInfoList.pInterfaceInfoList[index].vendorName, strLen - 4);
			strNameCat[strLen - 4] = '\0';
			strcat(strNameCat, "...");
			printf(" %-15.15s", strNameCat);
		}
		else
		{
			printf(" %-15.15s", interfaceInfoList.pInterfaceInfoList[index].vendorName);
		}

		// 相机的型号信息 最大表示字数：15 
		// Camera model name, display in 15 characters 
		printf(" %-15.15s", interfaceInfoList.pInterfaceInfoList[index].modelName);

		// 相机的序列号 最大表示字数：15 
		// Camera serial number, display in 15 characters 
		printf(" %-15.15s", interfaceInfoList.pInterfaceInfoList[index].serialNumber);

		// 自定义用户ID 最大表示字数：15 
		// Camera user id, display in 15 characters 
		if (strlen(interfaceInfoList.pInterfaceInfoList[index].interfaceName) > strLen - 1)
		{
			memcpy(strNameCat, interfaceInfoList.pInterfaceInfoList[index].interfaceName, strLen - 4);
			strNameCat[strLen - 4] = '\0';
			strcat(strNameCat, "...");
			printf(" %-15.15s", strNameCat);
		}
		else
		{
			printf(" %-15.15s", interfaceInfoList.pInterfaceInfoList[index].interfaceName);
		}
		printf("\n");

		bool isFind = false;
		for (unsigned int camIndex = 0; camIndex < deviceInfoList.nDevNum; ++camIndex)
		{
			cameraIndex = camIndex;
			pDevInfo = &deviceInfoList.pDeviceInfoList[cameraIndex];
			
			if (strcmp(pDevInfo->FGInterfaceInfo.interfaceKey, interfaceInfoList.pInterfaceInfoList[index].interfaceKey) == 0)
			{
				printf("    |--");
				printf("%-7d",camIndex+1);

				// 制造商信息  最大表示字数：15 
				// Camera vendor name, display in 15 characters 
				if (strlen(pDevInfo->vendorName) > strLen - 4)
				{
					memcpy(strNameCat, pDevInfo->vendorName, strLen - 4);
					strNameCat[strLen - 4] = '\0';
					strcat(strNameCat, "...");
					printf(" %-15.15s", strNameCat);
				}
				else
				{
					printf(" %-15.15s", pDevInfo->vendorName);
				}

				// 相机的型号信息 最大表示字数：15 
				// Camera model name, display in 15 characters 
				printf(" %-15.15s", pDevInfo->modelName);

				// 相机的序列号 最大表示字数：15 
				// Camera serial number, display in 15 characters 
				printf(" %-15.15s", pDevInfo->serialNumber);

				// 自定义用户ID 最大表示字数：15 
				// Camera user id, display in 15 characters 
				if (strlen(pDevInfo->cameraName) > strLen - 1)
				{
					memcpy(strNameCat, pDevInfo->cameraName, strLen - 4);
					strNameCat[strLen - 4] = '\0';
					strcat(strNameCat, "...");
					printf(" %-15.15s", strNameCat);
				}
				else
				{
					printf(" %-15.15s", pDevInfo->cameraName);
				}
				isFind = true;
				printf("\n");
			}
		}
		if (!isFind)
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

static unsigned int selectDevice(unsigned int interfaceCnt, unsigned int cameraCnt, int devType)
{
	char inputStr[256];
	char* pTrimStr;
	int inputIndex = -1;
	int ret = -1;
	char* find = NULL;
	
	if (CAPTURECARD == devType)
		printf("\nPlease input the interface index: ");
	else
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
			if (CAPTURECARD == devType)
			{
				if ((inputIndex >= 0) && (inputIndex < (int)interfaceCnt))
				{
					break;
				}
			}
			else
			{
				if ((inputIndex >= 0) && (inputIndex < (int)cameraCnt))
				{
					break;
				}
			}

		}

		if (CAPTURECARD == devType)
			printf("Input invalid! Please input the interface index: ");
		else
			printf("Input invalid! Please input the camera index: ");
	}

	return (unsigned int)inputIndex;
}

int main()
{
	printf("SDK Version:%s.\r\n", IMV_FG_GetVersion());

	int nRet = IMV_FG_OK;
	IMV_FG_INTERFACE_INFO_LIST interfaceList;
	IMV_FG_DEVICE_INFO_LIST camListPtr;
	UserHandleStruct userHandle;
	memset(&userHandle, 0, sizeof(UserHandleStruct));

	printf("Enum capture board interface info.\r\n");
	do
	{
		//枚举采集卡设备
		// Discover capture board device
		nRet = IMV_FG_EnumInterface(typeInterfaceAll, &interfaceList);
		if (IMV_FG_OK != nRet)
		{
			printf("Enumeration devices failed! errorCode:[%d]\r\n", nRet);
			break;
		}

		if (interfaceList.nInterfaceNum == 0)
		{
			printf("No board device find. board list size:%d.\r\n", interfaceList.nInterfaceNum);
			break;
		}

		printf("Enum camera device.\r\n");
		//枚举相机设备
		// discover camera 
		nRet = IMV_FG_EnumDevices(typeInterfaceAll, &camListPtr);
		if (IMV_FG_OK != nRet)
		{
			printf("Enumeration camera devices failed! errorCode:[%d]\r\n", nRet);
			break;
		}

		// 打印相机基本信息（序号,类型,制造商信息,型号,序列号,用户自定义ID)
		// Print camera info (Index, Type, Vendor, Model, Serial number, DeviceUserID) 
		displayDeviceInfo(interfaceList, camListPtr);

		// 选择需要连接的采集卡设备开流
		// Select one camera to connect to  
		unsigned int boardIndex = selectDevice(interfaceList.nInterfaceNum, camListPtr.nDevNum, CAPTURECARD);
		int cameraIndex = selectDevice(interfaceList.nInterfaceNum, camListPtr.nDevNum, CAM);

		printf("Open capture device.\r\n");
		// 打开采集卡设备
		// Open capture device 
		nRet = IMV_FG_OpenInterfaceEx(IMV_FG_MODE_BY_CAMERAKEY, (void*)interfaceList.pInterfaceInfoList[boardIndex].interfaceKey, &userHandle.ifHandle);
		if (IMV_FG_OK != nRet)
		{
			printf("Open interface failed! errorCode:[%d]\r\n", nRet);
			break;
		}

		printf("Open camera device.\r\n");
		// 打开采集卡相机设备 
		// Connect to camera 
		nRet = IMV_FG_OpenDevice(IMV_FG_MODE_BY_CAMERAKEY, (void*)camListPtr.pDeviceInfoList[cameraIndex].cameraKey, &userHandle.camHandle);
		if (IMV_FG_OK != nRet)
		{
			printf("Open camera failed! ErrorCode[%d]\n", nRet);
			break;
		}

		userHandle.camKey = camListPtr.pDeviceInfoList[cameraIndex].cameraKey;

		printf("Subscribe device state event.\r\n");
		// 设备连接状态事件回调函数
		// Device connection status event callback function
		nRet = IMV_FG_SubscribeConnectArg(userHandle.camHandle, onDeviceLinkNotify, &userHandle);
		if (IMV_FG_OK != nRet)
		{
			printf("SubscribeConnectArg failed! ErrorCode[%d]\n", nRet);
			break;
		}

		// 注册数据帧回调函数
		// Register data frame callback function
		nRet = IMV_FG_AttachGrabbing(userHandle.camHandle, onGetFrame, userHandle.camHandle);
		if (IMV_FG_OK != nRet)
		{
			printf("Attach grabbing failed! errorCode:[%d]\r\n", nRet);
			break;
		}

		// 设置触发模式 
		// Set trigger mode to Off 
		nRet = IMV_FG_SetEnumFeatureSymbol(userHandle.camHandle, "TriggerMode", "Off");
		if (IMV_FG_OK != nRet)
		{
			printf("Set triggerMode value failed! ErrorCode[%d]\n", nRet);
			break;
		}
		
		printf("Start grabbing 8s...\r\n");
		// 开始拉流 
		// Start grabbing 
		nRet = IMV_FG_StartGrabbing(userHandle.camHandle);
		if (IMV_FG_OK != nRet)
		{
			printf("Start grabbing failed! errorCode:[%d]\r\n", nRet);
			break;
		}

		getchar();

		g_isMainThreadExit = true;
		printf("Stop grabbing.\r\n");

		// 停止拉流 
		// Stop grabbing 
		nRet = IMV_FG_StopGrabbing(userHandle.camHandle);
		if (IMV_FG_OK != nRet)
		{
			printf("Stop grabbing failed! errorCode:[%d]\r\n", nRet);
			break;
		}
	} while (false);

	if (NULL != userHandle.camHandle)
	{
		printf("Close camera device.\r\n");
		//关闭相机
		//Close camera 
		nRet = IMV_FG_CloseDevice(userHandle.camHandle);
		if (IMV_FG_OK != nRet)
		{
			printf("Close camera failed! errorCode:[%d]\r\n", nRet);
		}
	}

	if (NULL != userHandle.ifHandle)
	{
		printf("Close capture device.\r\n");
		// 关闭采集卡
		// Close capture device 
		nRet = IMV_FG_CloseInterface(userHandle.ifHandle);
		if (IMV_FG_OK != nRet)
		{
			printf("Close interface failed! errorCode:[%d]\r\n", nRet);
		}
	}

	printf("Press enter key to exit...\r\n");
	getchar();
	return 0;
}
