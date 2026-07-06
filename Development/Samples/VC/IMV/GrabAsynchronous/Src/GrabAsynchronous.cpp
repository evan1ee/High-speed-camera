/// \file
/// \~chinese
/// \brief 异步取帧例程
/// \example GrabAsynchronous.cpp
/// \~english
/// \Asynchronous frame retrieval sample
/// \example GrabAsynchronous.cpp

//**********************************************************************
// 本Demo为简单演示SDK的使用，没有附加修改相机IP的代码，在运行之前，请使
// 用相机客户端修改相机IP地址的网段与主机的网段一致         
// This Demo shows how to use GenICam API(C) to write a simple program.
// Please make sure that the camera and PC are in the same subnet before running the demo.
// If not, you can use camera client software to modify the IP address of camera to the same subnet with PC. 
//**********************************************************************
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <Windows.h>
#include <process.h>
#include <mutex>
#include "IMVApi.h"

#define snprintf	_snprintf

#define Max_Count 5       //存帧队列个数，可动态调节
std::mutex g_mutex;

unsigned int g_defaultImageLen = 0;
bool g_isExitThread = false;

class frameQueue
{
public:
	frameQueue() = default;

	~frameQueue()
	{
		delete[]Qframes;
	}

	int Init(int nBufCount)
	{
		int ret = IMV_OK;
		QMaxlen = nBufCount;
		Qframes = new FrameInfo[nBufCount];
		if (NULL == Qframes)
		{
			printf("Qframes new error!!\r\n");
			return IMV_ERROR;
		}

		for (int i = 0; i < nBufCount; i++)
		{
			ret = Qframes[i].Init();
			if (IMV_OK != ret)
			{
				return ret;
			}
		}

		return ret;
	}

	int push(uint64_t nBlockId, int nWidth, int nHeight, unsigned char *pData, int nFrameLen)
	{
		g_mutex.lock();
		if (QCurrentSize == QMaxlen)
		{
			g_mutex.unlock();
			return IMV_ERROR;
		}

		QCurrentSize++;
		Qframes[end].blockId = nBlockId;
		Qframes[end].height = nHeight;
		Qframes[end].width = nWidth;
		Qframes[end].size = nFrameLen;

		if (Qframes[end].nQMemberSize < nFrameLen)
		{
			g_mutex.unlock();
			printf("frame size error!!\r\n");
			return IMV_ERROR;
		}

		if (NULL != Qframes[end].data && NULL != pData)
		{
			memcpy(Qframes[end].data, pData, nFrameLen);
		}
		else{
			printf("data ptr invalid!!\r\n");
			g_mutex.unlock();
			return IMV_ERROR;
		}

		end = (end + 1) % QMaxlen;
		g_mutex.unlock();

		return IMV_OK;
	}

	int pop(uint64_t *pBlockId, int *nWidth, int *nHeight, unsigned char *pData, int *nFrameLen)
	{
		g_mutex.lock();
		if (QCurrentSize == 0)
		{
			g_mutex.unlock();
			return IMV_ERROR;
		}

		*pBlockId = Qframes[start].blockId;
		*nWidth = Qframes[start].width;
		*nHeight = Qframes[start].height;
		*nFrameLen = Qframes[start].size;

		if (NULL != Qframes[start].data && NULL != pData)
		{
			memcpy(pData, Qframes[start].data, Qframes[start].size);
		}
		else
		{
			printf("data ptr invalid!!\r\n");
			g_mutex.unlock();
			return IMV_ERROR;
		}

		QCurrentSize--;
		start = (start + 1) % QMaxlen;
		g_mutex.unlock();

		return IMV_OK;
	}

private:
	class FrameInfo {
	public:
		FrameInfo() = default;

		~FrameInfo()
		{
			if (data != NULL)
			{
				free(data);
			}
		}

		int Init()
		{
			if (NULL != data)
			{
				printf("data != NULL\n");
				free(data);
				data = NULL;
			}

			data = (unsigned char*)malloc(g_defaultImageLen);
			if (NULL == data)
			{
				printf("data malloc failed!!\r\n");
				return IMV_ERROR;
			}
			nQMemberSize = g_defaultImageLen;
			return IMV_OK;
		}

	public:
		uint64_t blockId = 0;
		int width = 0;
		int height = 0;
		int size = 0;
		unsigned char* data = NULL;

		int nQMemberSize = 0;
	};

	FrameInfo* Qframes = NULL;
	int QCurrentSize = 0;
	int start = 0;
	int end = 0;
	int QMaxlen = 0;
};

frameQueue *m_queue = NULL;

// 数据帧回调函敿
// Data frame callback function
static void onGetFrame(IMV_Frame* pFrame, void* pUser)
{
	int nRet = IMV_OK;

	if (pFrame == NULL)
	{
		printf("pFrame is NULL\n");
		return;
	}

	//将帧存入队列
	nRet = m_queue->push(pFrame->frameInfo.blockId, pFrame->frameInfo.width, pFrame->frameInfo.height, pFrame->pData, pFrame->frameInfo.size);
	if (IMV_OK != nRet)
	{
		printf("Add frame to list failed!! blockId is [%llu].\r\n", pFrame->frameInfo.blockId);
	}
	else
	{
		printf("Add frame to list success!! blockId is [%llu].\r\n", pFrame->frameInfo.blockId);
	}

	return;
}

unsigned int __stdcall getFrameProc(void* pUserData)
{
	int ret = IMV_OK;
	IMV_HANDLE devHandle = (IMV_HANDLE)pUserData;
	int width = 0;
	int height = 0;
	int frameSize = 0;

	if (NULL == devHandle)
	{
		printf("devHandle is NULL\r\n");
		return IMV_ERROR;
	}

	unsigned char *pOutData = (unsigned char *)malloc(g_defaultImageLen);
	if (NULL == pOutData)
	{
		printf("saveImageProc malloc size [%d] failed. \r\n", g_defaultImageLen);
		return  IMV_ERROR;
	}

	while (!g_isExitThread)
	{
		uint64_t blockId = 0;
		ret = m_queue->pop(&blockId, &width, &height, pOutData, &frameSize);
		if (IMV_OK != ret)
		{
			printf("Pop failed, maybe no data. \r\n");
			Sleep(2);
			continue;
		}
		else
		{
			printf("Pop success BlockId is [%d], width is [%d], height is [%d], frameSize is [%d].\r\n", blockId, width, height, frameSize);
		}
	}

	if (pOutData)
	{
		free(pOutData);
		pOutData = NULL;
	}

	return 0;
}

// 计算帧缓存大小
// Calculate frame cache size
static int getFrameSize(IMV_HANDLE devHandle)
{
	int ret = IMV_OK;
	int64_t widthVal = 0;
	int64_t heightVal = 0;

	ret = IMV_GetIntFeatureValue(devHandle, "Width", &widthVal);
	if (IMV_OK != ret)
	{
		printf("Get Width feature value failed! ErrorCode[%d]\n", ret);
		return ret;
	}

	ret = IMV_GetIntFeatureValue(devHandle, "Height", &heightVal);
	if (IMV_OK != ret)
	{
		printf("Get Height feature value failed! ErrorCode[%d]\n", ret);
		return ret;
	}

	g_defaultImageLen = (int)widthVal * (int)heightVal * 3;
	return IMV_OK;
}

// ***********开始： 这部分处理与SDK操作相机无关，用于显示设备列表***********
// ***********BEGIN: These functions are not related to API call and used to display device info***********
static void displayDeviceInfo(IMV_DeviceList deviceInfoList)
{
	IMV_DeviceInfo*	pDevInfo = NULL;
	unsigned int cameraIndex = 0;
	char vendorNameCat[11];
	char cameraNameCat[16];

	// 打印Title
	// Print title line 
	printf("\nIdx Type Vendor     Model      S/N             DeviceUserID    IP Address    \n");
	printf("------------------------------------------------------------------------------\n");

	for (cameraIndex = 0; cameraIndex < deviceInfoList.nDevNum; cameraIndex++)
	{
		pDevInfo = &deviceInfoList.pDevInfo[cameraIndex];
		// 设备列表的相机索引 最大表示字数：3
		// Camera index in device list, display in 3 characters 
		printf("%-3d", cameraIndex + 1);

		// 相机的设备类型（GigE，U3V，CL，PCIe)
		// Camera type 
		switch (pDevInfo->nCameraType)
		{
			case typeGigeCamera:printf(" GigE");break;
			case typeU3vCamera:printf(" U3V ");break;
			case typeCLCamera:printf(" CL  ");break;
			case typePCIeCamera:printf(" PCIe");break;
			default:printf("     ");break;
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

		// 相机的型号信号最大表示字数：10 
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

// ***********这部分处理与SDK操作相机无关，用于显示设备列表***********
// ***********END: These functions are not related to API call and used to display device info***********

int main()
{
	int ret = IMV_OK;
	unsigned int cameraIndex = 0;
	IMV_HANDLE devHandle = NULL;
	HANDLE threadHandle = NULL;

	//创建队列
	m_queue = new frameQueue();
	if (NULL == m_queue)
	{
		printf("m_queue new error!!\r\n");
		getchar();
		return -1;
	}

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

	// 打印相机基本信息（设备类型,制造商信息,型号,序列号,用户自定义ID,IP地址）
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
		// Open camera 
		ret = IMV_Open(devHandle);
		if (IMV_OK != ret)
		{
			printf("Open camera failed! ErrorCode[%d]\n", ret);
			break;
		}

		// 计算帧缓存大小
		// Calculate frame cache size
		ret = getFrameSize(devHandle);
		if (IMV_OK != ret)
		{
			break;
		}

		//初始化队列
		//Initiation queue
		ret = m_queue->Init(Max_Count);
		if (IMV_OK != ret)
		{
			printf("Init frameQueue failed! ErrorCode[%d]\n", ret);
			break;
		}

		// 注册数据帧回调函数
		// Register data frame callback function
		ret = IMV_AttachGrabbing(devHandle, onGetFrame, NULL);
		if (IMV_OK != ret)
		{
			printf("Attach grabbing failed! ErrorCode[%d]\n", ret);
			break;
		}

		// 创建从队列取帧线程
		// Create a frame retrieval thread from the queue 
		threadHandle = (HANDLE)_beginthreadex(NULL,
			0,
			getFrameProc,
			(void*)devHandle,
			CREATE_SUSPENDED,
			NULL);

		if (!threadHandle)
		{
			printf("Failed to create getFrame thread!\n");
			break;
		}

		ResumeThread(threadHandle);

		// 设置触发模式 
		// Set trigger mode to Off 
		ret = IMV_SetEnumFeatureSymbol(devHandle, "TriggerMode", "Off");
		if (IMV_OK != ret)
		{
			printf("Set triggerMode value failed! ErrorCode[%d]\n", ret);
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

		// 取图2秒
		// get frame 2 seconds
		Sleep(2000);

		// 退出取帧线程
		// Stop Framing thread 
		g_isExitThread = true;

		WaitForSingleObject(threadHandle, INFINITE);
		CloseHandle(threadHandle);

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

	if (NULL != m_queue)
	{
		delete m_queue;
	}

	printf("Press enter key to exit...\n");
	getchar();

	return 0;
}
